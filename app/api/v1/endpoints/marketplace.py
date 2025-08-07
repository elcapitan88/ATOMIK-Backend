# app/api/v1/endpoints/marketplace.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
import logging

from app.api import deps
from app.core.security import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.webhook import Webhook
from app.models.strategy_pricing import StrategyPricing
from app.models.strategy_purchase import StrategyPurchase
from app.schemas.marketplace import (
    StrategyPricingCreate,
    StrategyPricingUpdate,
    StrategyPricingResponse,
    StrategyPurchaseRequest,
    StrategyPurchaseResponse,
    SubscriptionRequest,
    SubscriptionResponse,
    PricingOptionsResponse
)
from app.services.marketplace_service import MarketplaceService
from app.services.stripe_connect_service import StripeConnectService

logger = logging.getLogger(__name__)
router = APIRouter()

marketplace_service = MarketplaceService()
stripe_connect_service = StripeConnectService()


def convert_pricing_options_to_strategy_pricing(pricing_options: List[dict], webhook_id: int) -> StrategyPricingCreate:
    """
    Convert old pricing_options format to new StrategyPricingCreate format.
    
    Old format: [{"price_type": "monthly", "amount": 50, "billing_interval": "month", "trial_period_days": 7}]
    New format: StrategyPricingCreate with single pricing model
    """
    if not pricing_options:
        raise ValueError("No pricing options provided")
    
    # Convert old price types to new pricing types
    monthly_option = None
    yearly_option = None
    lifetime_option = None
    setup_option = None
    
    for option in pricing_options:
        price_type = option.get('price_type')
        if price_type == 'monthly':
            monthly_option = option
        elif price_type == 'yearly':
            yearly_option = option
        elif price_type == 'lifetime':
            lifetime_option = option
        elif price_type == 'setup':
            setup_option = option
    
    # Determine the new pricing type based on available options
    if setup_option and (monthly_option or yearly_option):
        # Setup fee + subscription = initiation_plus_sub
        pricing_type = "initiation_plus_sub"
        billing_interval = "monthly" if monthly_option else "yearly"
        base_amount = monthly_option['amount'] if monthly_option else None
        yearly_amount = yearly_option['amount'] if yearly_option else None
        setup_fee = setup_option['amount']
        trial_days = monthly_option.get('trial_period_days', 0) if monthly_option else yearly_option.get('trial_period_days', 0)
        
    elif monthly_option or yearly_option:
        # Subscription only
        pricing_type = "subscription"
        billing_interval = "monthly"  # Default to monthly display
        base_amount = monthly_option['amount'] if monthly_option else None
        yearly_amount = yearly_option['amount'] if yearly_option else None
        setup_fee = None
        trial_days = monthly_option.get('trial_period_days', 0) if monthly_option else yearly_option.get('trial_period_days', 0)
        
    elif lifetime_option:
        # One-time payment
        pricing_type = "one_time"
        billing_interval = None
        base_amount = lifetime_option['amount']
        yearly_amount = None
        setup_fee = None
        trial_days = 0
        
    else:
        raise ValueError("Invalid pricing options - no supported pricing model found")
    
    return StrategyPricingCreate(
        webhook_id=webhook_id,
        pricing_type=pricing_type,
        billing_interval=billing_interval,
        base_amount=base_amount,
        yearly_amount=yearly_amount,
        setup_fee=setup_fee,
        trial_days=trial_days,
        is_trial_enabled=trial_days > 0
    )


@router.post("/strategies/{token}/purchase", response_model=StrategyPurchaseResponse)
async def purchase_strategy(
    token: str,
    purchase_request: StrategyPurchaseRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Purchase a strategy with one-time payment.
    """
    try:
        # Get strategy by token (using webhook_token field for compatibility)
        webhook = db.query(Webhook).filter(Webhook.webhook_token == token).first()
        if not webhook:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Strategy not found"
            )
        
        # Get pricing information
        pricing = db.query(StrategyPricing).filter(
            StrategyPricing.webhook_id == webhook.id,
            StrategyPricing.is_active == True
        ).first()
        
        if not pricing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Strategy pricing not found"
            )
        
        if pricing.pricing_type == "free":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This strategy is free - no purchase required"
            )
        
        # Check if user already has active purchase
        existing_purchase = db.query(StrategyPurchase).filter(
            StrategyPurchase.user_id == current_user.id,
            StrategyPurchase.webhook_id == webhook.id,
            StrategyPurchase.status.in_(["pending", "completed"])
        ).first()
        
        if existing_purchase:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You already have an active purchase for this strategy"
            )
        
        # Process purchase
        purchase = await marketplace_service.process_strategy_purchase(
            db=db,
            user=current_user,
            webhook=webhook,
            pricing=pricing,
            payment_method_id=purchase_request.payment_method_id,
            trial_requested=purchase_request.start_trial
        )
        
        logger.info(f"Strategy purchase created: {purchase.id} for user {current_user.id}")
        return purchase
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing strategy purchase: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process strategy purchase"
        )


@router.post("/strategies/{token}/subscribe", response_model=SubscriptionResponse)
async def subscribe_to_strategy(
    token: str,
    subscription_request: SubscriptionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Subscribe to a paid strategy with recurring payments.
    """
    try:
        # Get strategy by token (using webhook_token field for compatibility)
        webhook = db.query(Webhook).filter(Webhook.webhook_token == token).first()
        if not webhook:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Strategy not found"
            )
        
        # Get pricing information
        pricing = db.query(StrategyPricing).filter(
            StrategyPricing.webhook_id == webhook.id,
            StrategyPricing.is_active == True
        ).first()
        
        if not pricing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Strategy pricing not found"
            )
        
        if pricing.pricing_type not in ["subscription", "initiation_plus_sub"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This strategy is not available for subscription"
            )
        
        # Check if user already has active subscription
        existing_subscription = db.query(StrategyPurchase).filter(
            StrategyPurchase.user_id == current_user.id,
            StrategyPurchase.webhook_id == webhook.id,
            StrategyPurchase.status.in_(["pending", "completed"]),
            StrategyPurchase.purchase_type == "subscription"
        ).first()
        
        if existing_subscription:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You already have an active subscription for this strategy"
            )
        
        # Process subscription
        subscription = await marketplace_service.process_strategy_subscription(
            db=db,
            user=current_user,
            webhook=webhook,
            pricing=pricing,
            payment_method_id=subscription_request.payment_method_id,
            billing_interval=subscription_request.billing_interval,
            trial_requested=subscription_request.start_trial
        )
        
        logger.info(f"Strategy subscription created: {subscription.id} for user {current_user.id}")
        return subscription
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing strategy subscription: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process strategy subscription"
        )


@router.get("/strategies/{token}/pricing", response_model=PricingOptionsResponse)
async def get_strategy_pricing(
    token: str,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(deps.get_current_user_optional)
):
    """
    Get pricing options for a strategy.
    """
    try:
        # Get strategy by token (using webhook_token field for compatibility)
        webhook = db.query(Webhook).filter(Webhook.webhook_token == token).first()
        if not webhook:
            logger.error(f"Strategy not found for token: {token}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Strategy not found"
            )
        
        logger.info(f"Found webhook {webhook.id} for token {token}")
        
        # Get pricing information
        pricing = db.query(StrategyPricing).filter(
            StrategyPricing.webhook_id == webhook.id,
            StrategyPricing.is_active == True
        ).first()
        
        if not pricing:
            logger.info(f"No pricing found for webhook {webhook.id}, returning free pricing")
            # Return free pricing if no pricing set
            return PricingOptionsResponse(
                webhook_id=webhook.id,
                pricing_type="free",
                is_free=True,
                user_has_access=True,
                user_purchase=None
            )
        
        logger.info(f"Found pricing {pricing.id} for webhook {webhook.id}")
        
        # Check user's current access
        user_purchase = None
        user_has_access = pricing.pricing_type == "free"
        
        if current_user:
            user_purchase = db.query(StrategyPurchase).filter(
                StrategyPurchase.user_id == current_user.id,
                StrategyPurchase.webhook_id == webhook.id,
                StrategyPurchase.status.in_(["pending", "completed"])
            ).first()
            
            if user_purchase:
                user_has_access = True
        
        return PricingOptionsResponse(
            webhook_id=webhook.id,
            pricing_type=pricing.pricing_type,
            base_amount=pricing.base_amount,
            yearly_amount=pricing.yearly_amount,
            setup_fee=pricing.setup_fee,
            trial_days=pricing.trial_days,
            is_trial_enabled=pricing.is_trial_enabled,
            billing_intervals=["monthly", "yearly"] if pricing.pricing_type in ["subscription", "initiation_plus_sub"] else [],
            is_free=pricing.pricing_type == "free",
            user_has_access=user_has_access,
            user_purchase=user_purchase
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting pricing for token {token}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get pricing information: {str(e)}"
        )


@router.post("/webhook-pricing", response_model=StrategyPricingResponse)
async def create_strategy_pricing(
    pricing_data: StrategyPricingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Create pricing configuration for a strategy.
    """
    try:
        # Verify user owns the webhook
        webhook = db.query(Webhook).filter(
            Webhook.id == pricing_data.webhook_id,
            Webhook.user_id == current_user.id
        ).first()
        
        if not webhook:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Strategy not found or access denied"
            )
        
        # Check if pricing already exists
        existing_pricing = db.query(StrategyPricing).filter(
            StrategyPricing.webhook_id == webhook.id
        ).first()
        
        if existing_pricing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Pricing already exists for this strategy. Use PUT to update."
            )
        
        # Create pricing
        pricing = await marketplace_service.create_strategy_pricing(
            db=db,
            webhook=webhook,
            pricing_data=pricing_data
        )
        
        # Mark webhook as monetized
        webhook.is_monetized = pricing_data.pricing_type != "free"
        db.commit()
        
        logger.info(f"Strategy pricing created: {pricing.id} for webhook {webhook.id}")
        return pricing
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating strategy pricing: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create strategy pricing"
        )


@router.put("/webhook-pricing/{pricing_id}", response_model=StrategyPricingResponse)
async def update_strategy_pricing(
    pricing_id: str,
    pricing_update: StrategyPricingUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Update pricing configuration for a strategy.
    """
    try:
        # Get pricing and verify ownership
        pricing = db.query(StrategyPricing).filter(
            StrategyPricing.id == pricing_id
        ).first()
        
        if not pricing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Pricing configuration not found"
            )
        
        # Verify user owns the webhook
        webhook = db.query(Webhook).filter(
            Webhook.id == pricing.webhook_id,
            Webhook.user_id == current_user.id
        ).first()
        
        if not webhook:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Strategy not found or access denied"
            )
        
        # Update pricing
        updated_pricing = await marketplace_service.update_strategy_pricing(
            db=db,
            pricing=pricing,
            update_data=pricing_update
        )
        
        # Update webhook monetization status
        webhook.is_monetized = updated_pricing.pricing_type != "free"
        db.commit()
        
        logger.info(f"Strategy pricing updated: {pricing.id}")
        return updated_pricing
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating strategy pricing: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update strategy pricing"
        )


@router.post("/strategies/{webhook_id}/setup-monetization", response_model=StrategyPricingResponse)
async def setup_strategy_monetization(
    webhook_id: int,
    request: dict,  # Accept any format for compatibility
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Set up monetization for a strategy (replacement for old system).
    Creates pricing configuration and Stripe products automatically.
    """
    try:
        # Verify user owns the webhook
        webhook = db.query(Webhook).filter(
            Webhook.id == webhook_id,
            Webhook.user_id == current_user.id
        ).first()
        
        if not webhook:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Strategy not found or access denied"
            )
        
        # Verify creator profile and Stripe Connect account
        if not current_user.creator_profile:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Creator profile required for monetization"
            )
            
        if not current_user.creator_profile.stripe_connect_account_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Stripe Connect account required for monetization"
            )
        
        # Convert old pricing_options format to new StrategyPricingCreate format
        if 'pricing_options' in request:
            try:
                pricing_data = convert_pricing_options_to_strategy_pricing(request['pricing_options'], webhook_id)
            except Exception as e:
                logger.error(f"Error converting pricing options: {str(e)}")
                # Create default subscription pricing if conversion fails
                pricing_data = StrategyPricingCreate(
                    webhook_id=webhook_id,
                    pricing_type="subscription",
                    billing_interval="monthly",
                    base_amount=request['pricing_options'][0].get('amount', 50.0) if request['pricing_options'] else 50.0,
                    trial_days=0,
                    is_trial_enabled=False
                )
        else:
            # Direct StrategyPricingCreate format
            pricing_data = StrategyPricingCreate(**request)
            pricing_data.webhook_id = webhook_id
        
        # Check if pricing already exists (update if exists)
        existing_pricing = db.query(StrategyPricing).filter(
            StrategyPricing.webhook_id == webhook.id
        ).first()
        
        if existing_pricing:
            # Update existing pricing
            updated_pricing = await marketplace_service.update_strategy_pricing(
                db=db,
                pricing=existing_pricing,
                update_data=pricing_data
            )
            pricing = updated_pricing
        else:
            # Create new pricing
            pricing = await marketplace_service.create_strategy_pricing(
                db=db,
                webhook=webhook,
                pricing_data=pricing_data
            )
        
        # Mark webhook as monetized and share to marketplace
        # Use the pricing result to determine monetization status
        webhook.is_monetized = pricing.pricing_type != "free"
        webhook.usage_intent = 'monetize'
        webhook.is_shared = True  # Auto-share monetized strategies to marketplace
        db.commit()
        
        logger.info(f"Strategy monetization setup: {pricing.id} for webhook {webhook.id}")
        
        # Convert response to dict to ensure JSON serializable
        return StrategyPricingResponse(
            id=str(pricing.id),
            webhook_id=pricing.webhook_id,
            pricing_type=pricing.pricing_type,
            billing_interval=pricing.billing_interval,
            base_amount=pricing.base_amount,
            yearly_amount=pricing.yearly_amount,
            setup_fee=pricing.setup_fee,
            trial_days=pricing.trial_days,
            is_trial_enabled=pricing.is_trial_enabled,
            stripe_price_id=pricing.stripe_price_id,
            stripe_yearly_price_id=pricing.stripe_yearly_price_id,
            is_active=pricing.is_active,
            created_at=pricing.created_at,
            updated_at=pricing.updated_at
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error setting up monetization: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to set up monetization"
        )