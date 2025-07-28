# fastapi_backend/app/api/v1/endpoints/strategy_monetization.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Dict, Any

from ....db.session import get_db
from ....core.security import get_current_user
from ....core.config import settings
from ....models.user import User
from ....models.webhook import Webhook
from ....models.strategy_monetization import StrategyMonetization
from ....schemas.strategy_monetization import (
    MonetizationSetupRequest,
    StrategyMonetizationResponse,
    MonetizationUpdateRequest,
    StrategyPricingQuery,
    MonetizationStatsResponse,
    PurchaseRequest,
    PurchaseResponse
)
from ....services.strategy_monetization_service import StrategyMonetizationService
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/{webhook_id}/setup-monetization", response_model=StrategyMonetizationResponse)
async def setup_strategy_monetization(
    webhook_id: int,
    request: MonetizationSetupRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Set up monetization for a strategy by automatically creating Stripe products and prices.
    This replaces the manual Stripe dashboard work.
    """
    try:
        # Verify webhook ownership
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
        
        # Initialize monetization service
        monetization_service = StrategyMonetizationService(db)
        
        # Set up monetization
        result = await monetization_service.setup_strategy_monetization(
            webhook_id=webhook_id,
            creator_user_id=current_user.id,
            pricing_options=request.pricing_options
        )
        
        logger.info(f"Successfully set up monetization for strategy {webhook_id} by user {current_user.id}")
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error setting up monetization for strategy {webhook_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to set up monetization: {str(e)}"
        )

@router.get("/{webhook_id}/monetization", response_model=StrategyMonetizationResponse)
async def get_strategy_monetization(
    webhook_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get existing monetization data for a strategy.
    """
    try:
        # Verify webhook ownership
        webhook = db.query(Webhook).filter(
            Webhook.id == webhook_id,
            Webhook.user_id == current_user.id
        ).first()
        
        if not webhook:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Strategy not found or access denied"
            )
        
        # Get monetization data
        monetization_service = StrategyMonetizationService(db)
        result = await monetization_service.get_strategy_monetization(
            webhook_id=webhook_id,
            creator_user_id=current_user.id
        )
        
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Monetization not found for this strategy"
            )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting monetization for strategy {webhook_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get monetization data: {str(e)}"
        )

@router.put("/{webhook_id}/update-pricing", response_model=StrategyMonetizationResponse)
async def update_strategy_pricing(
    webhook_id: int,
    request: MonetizationUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Update strategy pricing by creating new prices and optionally deactivating old ones.
    """
    try:
        # Verify webhook ownership
        webhook = db.query(Webhook).filter(
            Webhook.id == webhook_id,
            Webhook.user_id == current_user.id
        ).first()
        
        if not webhook:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Strategy not found or access denied"
            )
        
        # Verify existing monetization
        existing_monetization = db.query(StrategyMonetization).filter(
            StrategyMonetization.webhook_id == webhook_id
        ).first()
        
        if not existing_monetization:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Monetization not found. Set up monetization first."
            )
        
        # Initialize monetization service and update
        monetization_service = StrategyMonetizationService(db)
        
        # For updates, we use the same setup method which handles existing monetization
        result = await monetization_service.setup_strategy_monetization(
            webhook_id=webhook_id,
            creator_user_id=current_user.id,
            pricing_options=request.pricing_options
        )
        
        logger.info(f"Successfully updated pricing for strategy {webhook_id} by user {current_user.id}")
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating pricing for strategy {webhook_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update pricing: {str(e)}"
        )

@router.get("/{webhook_token}/pricing", response_model=List[Dict[str, Any]])
async def get_strategy_pricing_options(
    webhook_token: str,
    db: Session = Depends(get_db)
):
    """
    Get pricing options for a strategy by webhook token.
    This is used by the public marketplace and purchase flow.
    Replaces environment variable lookups with database queries.
    """
    try:
        monetization_service = StrategyMonetizationService(db)
        pricing_options = await monetization_service.get_strategy_pricing_options(webhook_token)
        
        if not pricing_options:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Pricing options not found for this strategy"
            )
        
        return pricing_options
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting pricing options for token {webhook_token}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get pricing options: {str(e)}"
        )

@router.get("/{webhook_id}/stats", response_model=MonetizationStatsResponse)
async def get_monetization_stats(
    webhook_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get monetization statistics for a strategy.
    """
    try:
        # Verify webhook ownership
        webhook = db.query(Webhook).filter(
            Webhook.id == webhook_id,
            Webhook.user_id == current_user.id
        ).first()
        
        if not webhook:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Strategy not found or access denied"
            )
        
        # Get monetization data
        monetization = db.query(StrategyMonetization).filter(
            StrategyMonetization.webhook_id == webhook_id
        ).first()
        
        if not monetization:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Monetization not found for this strategy"
            )
        
        # Calculate total revenue from all prices
        total_revenue = sum(
            float(price.total_revenue) if hasattr(price, 'total_revenue') else 0.0 
            for price in monetization.prices
        )
        
        active_prices = len([price for price in monetization.prices if price.is_active])
        
        return MonetizationStatsResponse(
            total_subscribers=monetization.total_subscribers,
            estimated_monthly_revenue=float(monetization.estimated_monthly_revenue),
            active_pricing_options=active_prices,
            total_revenue_to_date=total_revenue,
            platform_fee_percentage=15.0,
            creator_revenue_percentage=85.0
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting stats for strategy {webhook_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get monetization stats: {str(e)}"
        )

@router.delete("/{webhook_id}/monetization")
async def disable_strategy_monetization(
    webhook_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Disable monetization for a strategy (deactivate all prices).
    """
    try:
        # Verify webhook ownership
        webhook = db.query(Webhook).filter(
            Webhook.id == webhook_id,
            Webhook.user_id == current_user.id
        ).first()
        
        if not webhook:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Strategy not found or access denied"
            )
        
        # Get monetization data
        monetization = db.query(StrategyMonetization).filter(
            StrategyMonetization.webhook_id == webhook_id
        ).first()
        
        if not monetization:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Monetization not found for this strategy"
            )
        
        # Deactivate monetization and all prices
        monetization.is_active = False
        for price in monetization.prices:
            price.is_active = False
        
        # Update webhook to remove monetization status
        webhook.is_monetized = False
        webhook.usage_intent = 'personal'  # Reset to personal use
        
        db.commit()
        
        logger.info(f"Disabled monetization for strategy {webhook_id} by user {current_user.id}")
        
        return {
            "status": "success",
            "message": "Monetization disabled successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error disabling monetization for strategy {webhook_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to disable monetization: {str(e)}"
        )

@router.post("/{webhook_token}/purchase", response_model=PurchaseResponse)
async def create_purchase_session(
    webhook_token: str,
    request: PurchaseRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Create a Stripe checkout session for strategy purchase.
    """
    try:
        # Get webhook/strategy by token
        webhook = db.query(Webhook).filter(Webhook.webhook_token == webhook_token).first()
        
        if not webhook:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Strategy not found"
            )
        
        # Get strategy monetization data
        monetization = db.query(StrategyMonetization).filter(
            StrategyMonetization.webhook_id == webhook.id
        ).first()
        
        if not monetization or not monetization.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This strategy is not available for purchase"
            )
        
        # Find the requested price
        strategy_price = None
        for price in monetization.prices:
            if price.price_type == request.price_type and price.is_active:
                strategy_price = price
                break
        
        if not strategy_price:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Price type '{request.price_type}' not found for this strategy"
            )
        
        # Get creator's Stripe account
        creator = db.query(User).filter(User.id == monetization.creator_user_id).first()
        if not creator or not creator.creator_profile or not creator.creator_profile.stripe_connect_account_id:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Creator account not properly configured"
            )
        
        stripe_account_id = creator.creator_profile.stripe_connect_account_id
        
        # Calculate platform fee based on creator tier
        platform_fee_percent = creator.creator_profile.platform_fee
        
        # Initialize Stripe service
        from ....services.stripe_connect_service import StripeConnectService
        stripe_service = StripeConnectService()
        
        # Create checkout session
        success_url = f"{settings.FRONTEND_URL}/strategy/{webhook.id}?purchase=success&session_id={{CHECKOUT_SESSION_ID}}"
        cancel_url = f"{settings.FRONTEND_URL}/strategy/{webhook.id}?purchase=cancelled"
        
        checkout_session = await stripe_service.create_checkout_session(
            price_id=strategy_price.stripe_price_id,
            success_url=success_url,
            cancel_url=cancel_url,
            customer_email=request.customer_email or current_user.email,
            stripe_account_id=stripe_account_id,
            metadata={
                "webhook_id": str(webhook.id),
                "user_id": str(current_user.id),
                "price_type": request.price_type,
                "creator_user_id": str(creator.id),
                "platform_fee_percent": str(platform_fee_percent)
            },
            application_fee_percent=platform_fee_percent
        )
        
        logger.info(f"Created checkout session {checkout_session.id} for strategy {webhook.id}")
        
        return PurchaseResponse(
            checkout_url=checkout_session.url,
            session_id=checkout_session.id
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating purchase session for token {webhook_token}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create checkout session: {str(e)}"
        )