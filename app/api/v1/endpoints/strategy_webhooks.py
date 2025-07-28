# fastapi_backend/app/api/v1/endpoints/strategy_webhooks.py
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
import stripe
import logging
from typing import Dict, Any

from ....db.session import get_db
from ....core.config import settings
from ....models.webhook import Webhook
from ....models.user import User
from ....models.strategy_monetization import StrategyMonetization
from ....models.strategy_purchases import StrategyPurchase
from ....services.stripe_connect_service import StripeConnectService

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/stripe-webhook")
async def handle_strategy_stripe_webhook(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Handle Stripe webhooks for strategy purchases and subscriptions.
    """
    try:
        payload = await request.body()
        sig_header = request.headers.get('stripe-signature')
        
        if not sig_header:
            raise HTTPException(status_code=400, detail="Missing signature")
        
        try:
            # Verify webhook signature
            event = stripe.Webhook.construct_event(
                payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
            )
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid payload")
        except stripe.error.SignatureVerificationError:
            raise HTTPException(status_code=400, detail="Invalid signature")
        
        # Handle different event types
        event_type = event['type']
        event_data = event['data']['object']
        
        logger.info(f"Processing strategy webhook event: {event_type}")
        
        if event_type == 'checkout.session.completed':
            await handle_checkout_completed(event_data, db)
        elif event_type == 'invoice.payment_succeeded':
            await handle_subscription_payment(event_data, db)
        elif event_type == 'customer.subscription.deleted':
            await handle_subscription_cancelled(event_data, db)
        elif event_type == 'customer.subscription.trial_will_end':
            await handle_trial_ending(event_data, db)
        elif event_type == 'invoice.payment_failed':
            await handle_payment_failed(event_data, db)
        
        return {"status": "success"}
        
    except Exception as e:
        logger.error(f"Error processing strategy webhook: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

async def handle_checkout_completed(session_data: Dict[str, Any], db: Session):
    """
    Handle successful checkout session completion.
    """
    try:
        session_id = session_data.get('id')
        customer_id = session_data.get('customer')
        subscription_id = session_data.get('subscription')
        metadata = session_data.get('metadata', {})
        
        webhook_id = metadata.get('webhook_id')
        user_id = metadata.get('user_id')
        price_type = metadata.get('price_type')
        creator_user_id = metadata.get('creator_user_id')
        platform_fee_percent = float(metadata.get('platform_fee_percent', 15.0))
        
        if not all([webhook_id, user_id, price_type]):
            logger.error(f"Missing required metadata in checkout session {session_id}")
            return
        
        # Get pricing information
        pricing = db.query(StrategyMonetization).filter(
            StrategyMonetization.webhook_id == webhook_id
        ).first()
        
        if not pricing:
            logger.error(f"No pricing found for webhook {webhook_id}")
            return
        
        # Find the specific price
        strategy_price = None
        for price in pricing.prices:
            if price.price_type == price_type:
                strategy_price = price
                break
        
        if not strategy_price:
            logger.error(f"No price found for type {price_type}")
            return
        
        # Calculate amounts
        amount_paid = strategy_price.amount
        platform_fee = amount_paid * (platform_fee_percent / 100)
        creator_payout = amount_paid - platform_fee
        
        # Create purchase record
        purchase = StrategyPurchase(
            user_id=user_id,
            webhook_id=webhook_id,
            pricing_id=strategy_price.id,
            stripe_payment_intent_id=session_data.get('payment_intent'),
            stripe_subscription_id=subscription_id,
            amount_paid=amount_paid,
            platform_fee=platform_fee,
            creator_payout=creator_payout,
            purchase_type=price_type,
            status='active' if subscription_id else 'completed',
            trial_ends_at=None  # Will be set from subscription data if applicable
        )
        
        db.add(purchase)
        
        # Update strategy subscriber count
        pricing.total_subscribers += 1
        
        db.commit()
        
        logger.info(f"Created purchase record for session {session_id}")
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error handling checkout completion: {str(e)}")
        raise

async def handle_subscription_payment(invoice_data: Dict[str, Any], db: Session):
    """
    Handle successful subscription payment.
    """
    try:
        subscription_id = invoice_data.get('subscription')
        
        if not subscription_id:
            return
        
        # Find the purchase record
        purchase = db.query(StrategyPurchase).filter(
            StrategyPurchase.stripe_subscription_id == subscription_id
        ).first()
        
        if not purchase:
            logger.warning(f"No purchase found for subscription {subscription_id}")
            return
        
        # Update purchase status if it was trialing
        if purchase.status == 'trialing':
            purchase.status = 'active'
            db.commit()
            logger.info(f"Trial converted to active for subscription {subscription_id}")
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error handling subscription payment: {str(e)}")
        raise

async def handle_subscription_cancelled(subscription_data: Dict[str, Any], db: Session):
    """
    Handle subscription cancellation.
    """
    try:
        subscription_id = subscription_data.get('id')
        
        # Find the purchase record
        purchase = db.query(StrategyPurchase).filter(
            StrategyPurchase.stripe_subscription_id == subscription_id
        ).first()
        
        if not purchase:
            logger.warning(f"No purchase found for cancelled subscription {subscription_id}")
            return
        
        # Update purchase status
        purchase.status = 'cancelled'
        
        # Decrease subscriber count
        pricing = db.query(StrategyMonetization).filter(
            StrategyMonetization.webhook_id == purchase.webhook_id
        ).first()
        
        if pricing and pricing.total_subscribers > 0:
            pricing.total_subscribers -= 1
        
        db.commit()
        
        logger.info(f"Cancelled subscription {subscription_id}")
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error handling subscription cancellation: {str(e)}")
        raise

async def handle_trial_ending(subscription_data: Dict[str, Any], db: Session):
    """
    Handle trial period ending notification.
    """
    try:
        subscription_id = subscription_data.get('id')
        
        # Find the purchase record
        purchase = db.query(StrategyPurchase).filter(
            StrategyPurchase.stripe_subscription_id == subscription_id
        ).first()
        
        if purchase:
            # Here you could send notifications to the user about trial ending
            logger.info(f"Trial ending for subscription {subscription_id}")
        
    except Exception as e:
        logger.error(f"Error handling trial ending: {str(e)}")

async def handle_payment_failed(invoice_data: Dict[str, Any], db: Session):
    """
    Handle failed payment attempts.
    """
    try:
        subscription_id = invoice_data.get('subscription')
        
        if not subscription_id:
            return
        
        # Find the purchase record
        purchase = db.query(StrategyPurchase).filter(
            StrategyPurchase.stripe_subscription_id == subscription_id
        ).first()
        
        if purchase:
            # Update status to indicate payment issues
            purchase.status = 'past_due'
            db.commit()
            
            # Here you could send notifications to the user about payment failure
            logger.info(f"Payment failed for subscription {subscription_id}")
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error handling payment failure: {str(e)}")
        raise