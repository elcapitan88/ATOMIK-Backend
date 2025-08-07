# app/api/v1/endpoints/marketplace.py
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import List, Optional
import logging

from app.api import deps
from app.core.security import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.models.user import User
from app.models.webhook import Webhook
from app.models.strategy_pricing import StrategyPricing
from app.models.strategy_purchase import StrategyPurchase, PurchaseStatus, PurchaseType
from app.models.creator_profile import CreatorProfile
from app.models.creator_earnings import CreatorEarnings, PayoutStatus
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
        # Get strategy by token
        webhook = db.query(Webhook).filter(Webhook.token == token).first()
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
        # Get strategy by token
        webhook = db.query(Webhook).filter(Webhook.token == token).first()
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


@router.post("/strategies/{token}/create-checkout")
async def create_strategy_checkout_session(
    token: str,
    checkout_request: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Create a Stripe Checkout session for strategy purchase/subscription.
    Follows the same pattern as app subscriptions.
    """
    try:
        # Get strategy by token
        webhook = db.query(Webhook).filter(Webhook.token == token).first()
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
                detail="This strategy is free - no checkout required"
            )
        
        # Get creator profile for Stripe Connect account
        creator_profile = db.query(CreatorProfile).filter(
            CreatorProfile.user_id == webhook.user_id
        ).first()
        
        if not creator_profile or not creator_profile.stripe_connect_account_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Creator has not set up Stripe Connect account"
            )
        
        # Extract billing interval from request
        billing_interval = checkout_request.get('billing_interval', 'monthly')
        
        # Validate pricing type and billing interval
        if pricing.pricing_type == "subscription":
            if billing_interval not in ["monthly", "yearly"]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid billing interval for subscription"
                )
        elif pricing.pricing_type == "one_time":
            billing_interval = "lifetime"
        
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
        
        # Create checkout session using StripeConnectService
        checkout_url = await stripe_connect_service.create_strategy_checkout_session(
            strategy_name=webhook.name,
            strategy_description=webhook.details or f"Access to {webhook.name} trading strategy",
            pricing=pricing,
            billing_interval=billing_interval,
            connected_account_id=creator_profile.stripe_connect_account_id,
            customer_email=current_user.email,
            success_url=f"{settings.FRONTEND_URL}/marketplace/purchase-success?session_id={{CHECKOUT_SESSION_ID}}&strategy_token={token}",
            cancel_url=f"{settings.FRONTEND_URL}/marketplace?cancelled=true",
            metadata={
                'user_id': str(current_user.id),
                'webhook_id': str(webhook.id),
                'webhook_token': token,  # Add webhook token for proper linking
                'creator_id': str(creator_profile.id),
                'pricing_id': str(pricing.id),
                'strategy_token': token,
                'purchase_type': 'strategy_subscription' if pricing.pricing_type == "subscription" else 'strategy_purchase'
            }
        )
        
        logger.info(f"Created strategy checkout session for user {current_user.id} and strategy {webhook.id}")
        return {"checkout_url": checkout_url}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating strategy checkout session: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create checkout session"
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
        # Get strategy by token
        webhook = db.query(Webhook).filter(Webhook.token == token).first()
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


@router.post("/webhook")
async def handle_strategy_webhook(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Handle Stripe webhooks for strategy purchases.
    Similar to the main subscription webhook handler.
    """
    try:
        # Get the webhook signature from headers
        sig_header = request.headers.get('stripe-signature')
        if not sig_header:
            logger.error("No Stripe signature found in strategy webhook request")
            return {"status": "error", "message": "No signature header"}

        # Get the raw request body
        payload = await request.body()
        
        # Verify webhook signature using Stripe Connect
        try:
            import stripe
            # Use the webhook endpoint secret for strategy webhooks (if configured)
            webhook_secret = getattr(settings, 'STRIPE_STRATEGY_WEBHOOK_SECRET', settings.STRIPE_WEBHOOK_SECRET)
            event = stripe.Webhook.construct_event(
                payload, sig_header, webhook_secret
            )
        except Exception as e:
            logger.error(f"Strategy webhook signature verification failed: {str(e)}")
            return {"status": "error", "message": "Invalid signature"}

        # Log event for debugging
        logger.info(f"Processing strategy webhook event: {event['type']}")
        
        # Process different event types
        event_type = event['type']
        event_data = event['data']['object']

        # Handle checkout session completion for strategy purchases
        if event_type == "checkout.session.completed":
            await handle_strategy_checkout_completed(db, event_data)
        
        # Handle successful payments for one-time strategy purchases
        elif event_type == "payment_intent.succeeded":
            await handle_strategy_payment_succeeded(db, event_data)
        
        # Handle subscription events for recurring strategy purchases
        elif event_type == "invoice.payment_succeeded":
            await handle_strategy_subscription_payment(db, event_data)
        
        elif event_type == "customer.subscription.deleted":
            await handle_strategy_subscription_cancelled(db, event_data)

        return {"status": "success"}

    except Exception as e:
        logger.error(f"Strategy webhook processing error: {str(e)}")
        return {"status": "error", "message": str(e)}


async def handle_strategy_checkout_completed(db: Session, session_data: dict):
    """Handle successful checkout completion for strategy purchases."""
    try:
        metadata = session_data.get('metadata', {})
        user_id = metadata.get('user_id')
        webhook_id = metadata.get('webhook_id')
        webhook_token = metadata.get('webhook_token')  # Use webhook token for linking
        pricing_id = metadata.get('pricing_id')
        purchase_type = metadata.get('purchase_type')
        
        if not all([user_id, webhook_token, pricing_id]):
            logger.error("Missing required metadata in strategy checkout completion")
            return
        
        # Get user, webhook, and pricing records using webhook token
        user = db.query(User).filter(User.id == user_id).first()
        webhook = db.query(Webhook).filter(Webhook.token == webhook_token).first()
        pricing = db.query(StrategyPricing).filter(StrategyPricing.id == pricing_id).first()
        
        if not all([user, webhook, pricing]):
            logger.error(f"Could not find records for strategy purchase: user={user_id}, webhook_token={webhook_token}, pricing={pricing_id}")
            return
        
        # Check if purchase already exists - use webhook.id for linking
        existing_purchase = db.query(StrategyPurchase).filter(
            StrategyPurchase.user_id == user.id,
            StrategyPurchase.webhook_id == webhook.id,  # Use webhook.id (proper FK)
            StrategyPurchase.pricing_id == pricing.id
        ).first()
        
        if existing_purchase:
            logger.info(f"Strategy purchase already exists: {existing_purchase.id}")
            return
        
        # Calculate amounts
        if session_data.get('mode') == 'subscription':
            amount = pricing.base_amount if pricing.base_amount else pricing.yearly_amount
        else:
            amount = pricing.base_amount or 0
        
        # Get creator profile for fee calculation
        creator_profile = db.query(CreatorProfile).filter(
            CreatorProfile.user_id == webhook.user_id
        ).first()
        
        platform_fee = (amount * creator_profile.platform_fee) if creator_profile else (amount * 0.20)
        creator_payout = amount - platform_fee
        
        # Create strategy purchase record
        purchase = StrategyPurchase(
            user_id=user.id,
            webhook_id=webhook.id,  # Use webhook.id (proper FK)
            pricing_id=pricing.id,
            amount_paid=amount,
            platform_fee=platform_fee,
            creator_payout=creator_payout,
            purchase_type=PurchaseType.SUBSCRIPTION if purchase_type == 'strategy_subscription' else PurchaseType.ONE_TIME,
            status=PurchaseStatus.COMPLETED,
            stripe_payment_intent_id=session_data.get('payment_intent'),
            stripe_subscription_id=session_data.get('subscription')
        )
        
        db.add(purchase)
        db.commit()
        db.refresh(purchase)
        
        # Create earnings record for creator
        if creator_profile and creator_payout > 0:
            earnings = CreatorEarnings(
                creator_id=creator_profile.id,
                purchase_id=purchase.id,
                gross_amount=amount,
                platform_fee=platform_fee,
                net_amount=creator_payout,
                payout_status=PayoutStatus.PENDING
            )
            db.add(earnings)
            db.commit()
        
        logger.info(f"Created strategy purchase {purchase.id} for user {user.id} and strategy {webhook.id}")
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error handling strategy checkout completion: {str(e)}")


async def handle_strategy_payment_succeeded(db: Session, payment_intent_data: dict):
    """Handle successful one-time payments for strategies."""
    try:
        metadata = payment_intent_data.get('metadata', {})
        user_id = metadata.get('user_id')
        webhook_token = metadata.get('webhook_token')
        
        if not user_id or not webhook_token:
            logger.error("Missing user_id or webhook_token in payment intent metadata")
            return
        
        # Find webhook by token to get the ID
        webhook = db.query(Webhook).filter(Webhook.token == webhook_token).first()
        if not webhook:
            logger.error(f"Webhook not found with token: {webhook_token}")
            return
        
        # Update purchase status to completed
        purchase = db.query(StrategyPurchase).filter(
            StrategyPurchase.user_id == user_id,
            StrategyPurchase.webhook_id == webhook.id,  # Use webhook.id (proper FK)
            StrategyPurchase.stripe_payment_intent_id == payment_intent_data['id']
        ).first()
        
        if purchase:
            purchase.status = PurchaseStatus.COMPLETED
            db.commit()
            logger.info(f"Updated strategy purchase {purchase.id} to completed")
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error handling strategy payment success: {str(e)}")


async def handle_strategy_subscription_payment(db: Session, invoice_data: dict):
    """Handle recurring subscription payments for strategies."""
    try:
        subscription_id = invoice_data.get('subscription')
        if not subscription_id:
            return
        
        # Find purchase by subscription ID
        purchase = db.query(StrategyPurchase).filter(
            StrategyPurchase.stripe_subscription_id == subscription_id
        ).first()
        
        if purchase:
            purchase.status = PurchaseStatus.COMPLETED
            db.commit()
            logger.info(f"Updated strategy subscription {purchase.id} payment status")
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error handling strategy subscription payment: {str(e)}")


async def handle_strategy_subscription_cancelled(db: Session, subscription_data: dict):
    """Handle cancelled strategy subscriptions."""
    try:
        subscription_id = subscription_data.get('id')
        if not subscription_id:
            return
        
        # Find purchase by subscription ID
        purchase = db.query(StrategyPurchase).filter(
            StrategyPurchase.stripe_subscription_id == subscription_id
        ).first()
        
        if purchase:
            purchase.status = PurchaseStatus.CANCELLED
            db.commit()
            logger.info(f"Cancelled strategy subscription {purchase.id}")
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error handling strategy subscription cancellation: {str(e)}")


@router.get("/my-purchases")
async def get_user_purchases(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get all strategy purchases for the current user.
    Returns list of purchased strategies with their webhook tokens.
    """
    try:
        # Debug logging
        logger.info(f"Getting purchases for user: id={current_user.id}, email={current_user.email}")
        
        # Query all purchases for this user
        purchases = db.query(StrategyPurchase).filter(
            StrategyPurchase.user_id == current_user.id,
            StrategyPurchase.status.in_([PurchaseStatus.COMPLETED, PurchaseStatus.PENDING])
        ).all()
        
        logger.info(f"Found {len(purchases)} purchases for user {current_user.id}")
        
        # Build response with webhook tokens for easy frontend matching
        purchased_strategies = []
        for purchase in purchases:
            # Get webhook by joining with webhook_id (which should be webhook.id, not token)
            webhook = db.query(Webhook).filter(Webhook.id == purchase.webhook_id).first()
            if webhook:
                purchased_strategies.append({
                    "id": str(purchase.id),
                    "webhook_id": purchase.webhook_id,
                    "webhook_token": webhook.token,
                    "webhook_name": webhook.name,
                    "purchase_type": purchase.purchase_type.value if purchase.purchase_type else None,
                    "status": purchase.status.value if purchase.status else None,
                    "amount_paid": float(purchase.amount_paid) if purchase.amount_paid else 0,
                    "created_at": purchase.created_at.isoformat() if purchase.created_at else None,
                    "is_active": purchase.status == PurchaseStatus.COMPLETED,
                    "stripe_subscription_id": purchase.stripe_subscription_id,
                    "trial_ends_at": purchase.trial_ends_at.isoformat() if purchase.trial_ends_at else None
                })
        
        return {
            "purchases": purchased_strategies,
            "total": len(purchased_strategies),
            "debug_user_id": current_user.id,
            "debug_user_email": current_user.email
        }
        
    except Exception as e:
        logger.error(f"Error fetching user purchases: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch user purchases"
        )


@router.get("/strategies/{webhook_token}/access")
async def check_strategy_access(
    webhook_token: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Check if the current user has access to a specific strategy.
    Returns access status and purchase details if applicable.
    """
    try:
        # Find the webhook by token
        webhook = db.query(Webhook).filter(
            Webhook.token == webhook_token
        ).first()
        
        if not webhook:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Strategy not found"
            )
        
        # Check if user owns the strategy
        if webhook.user_id == current_user.id:
            return {
                "has_access": True,
                "access_type": "owner",
                "webhook_token": webhook_token
            }
        
        # Check if strategy is free (share_free intent)
        if webhook.usage_intent == "share_free":
            return {
                "has_access": True,
                "access_type": "free",
                "webhook_token": webhook_token
            }
        
        # Check if user has purchased the strategy
        purchase = db.query(StrategyPurchase).filter(
            StrategyPurchase.user_id == current_user.id,
            StrategyPurchase.webhook_id == webhook.id,  # Use webhook.id (proper FK)
            StrategyPurchase.status.in_([PurchaseStatus.COMPLETED, PurchaseStatus.PENDING])
        ).first()
        
        if purchase:
            return {
                "has_access": True,
                "access_type": "purchased",
                "webhook_token": webhook_token,
                "purchase_id": str(purchase.id),
                "purchase_type": purchase.purchase_type.value if purchase.purchase_type else None,
                "subscription_id": purchase.stripe_subscription_id,
                "trial_ends_at": purchase.trial_ends_at.isoformat() if purchase.trial_ends_at else None
            }
        
        # No access
        return {
            "has_access": False,
            "access_type": None,
            "webhook_token": webhook_token
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error checking strategy access: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to check strategy access"
        )


@router.get("/verify-purchase-session/{session_id}")
async def verify_purchase_session(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Verify a Stripe checkout session and associated purchase.
    Called by the frontend success page to confirm purchase completion.
    """
    try:
        import stripe
        
        # Retrieve the session from Stripe
        session = stripe.checkout.Session.retrieve(session_id)
        
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Checkout session not found"
            )
        
        # Check if payment was successful
        if session.payment_status != 'paid' and session.mode != 'subscription':
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Payment not completed"
            )
        
        # Get metadata from session
        metadata = session.metadata or {}
        user_id = metadata.get('user_id')
        webhook_id = metadata.get('webhook_id')
        
        # Verify the user owns this session
        if str(current_user.id) != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )
        
        # Check if purchase exists in database
        purchase = db.query(StrategyPurchase).filter(
            StrategyPurchase.user_id == current_user.id,
            StrategyPurchase.webhook_id == webhook_id
        ).first()
        
        webhook = db.query(Webhook).filter(Webhook.id == webhook_id).first()
        
        return {
            "success": True,
            "session_id": session_id,
            "payment_status": session.payment_status,
            "purchase_exists": purchase is not None,
            "strategy_name": webhook.name if webhook else None,
            "amount_paid": float(purchase.amount_paid) if purchase else None
        }
        
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error verifying session: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Stripe error: {str(e)}"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error verifying purchase session: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify purchase"
        )