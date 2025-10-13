"""
Enhanced Stripe webhook service with retry logic and monitoring
"""
import stripe
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from fastapi import HTTPException

from app.models.stripe_webhook_log import StripeWebhookLog
from app.models.strategy_purchase import StrategyPurchase
from app.models.strategy_pricing import StrategyPricing
from app.models.user import User
from app.core.config import settings

logger = logging.getLogger(__name__)

class StripeWebhookService:
    """Enhanced Stripe webhook handler with retry and monitoring"""

    def __init__(self, db: Session):
        self.db = db
        stripe.api_key = settings.STRIPE_SECRET_KEY

    async def process_webhook(self, payload: bytes, signature: str) -> Dict[str, Any]:
        """Process incoming Stripe webhook with logging and retry logic"""
        try:
            # Verify webhook signature
            event = stripe.Webhook.construct_event(
                payload, signature, settings.STRIPE_WEBHOOK_SECRET
            )
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid payload")
        except stripe.SignatureVerificationError:
            raise HTTPException(status_code=400, detail="Invalid signature")

        # Check if we've already processed this event
        existing_log = self.db.query(StripeWebhookLog).filter(
            StripeWebhookLog.stripe_event_id == event['id']
        ).first()

        if existing_log and existing_log.status == 'success':
            logger.info(f"Event {event['id']} already processed successfully")
            return {"status": "already_processed"}

        # Create or update webhook log
        if not existing_log:
            webhook_log = StripeWebhookLog(
                stripe_event_id=event['id'],
                event_type=event['type'],
                webhook_endpoint='strategy_webhooks',
                event_data=event,
                status='processing'
            )
            self.db.add(webhook_log)
        else:
            webhook_log = existing_log
            webhook_log.status = 'processing'
            webhook_log.retry_count += 1

        self.db.commit()

        try:
            # Process different event types
            result = await self._process_event(event, webhook_log)

            # Mark as successful
            webhook_log.status = 'success'
            webhook_log.processed_at = datetime.utcnow()
            self.db.commit()

            return result

        except Exception as e:
            # Log the error
            webhook_log.status = 'failed'
            webhook_log.error_message = str(e)
            webhook_log.error_details = {
                'exception_type': type(e).__name__,
                'traceback': str(e)
            }

            # Schedule retry if not exceeded max retries
            if webhook_log.retry_count < webhook_log.max_retries:
                webhook_log.next_retry_at = datetime.utcnow() + timedelta(
                    minutes=5 * webhook_log.retry_count  # Exponential backoff
                )

            self.db.commit()

            logger.error(f"Error processing webhook {event['id']}: {e}")
            raise

    async def _process_event(self, event: Dict, log: StripeWebhookLog) -> Dict[str, Any]:
        """Process specific event types"""
        event_type = event['type']
        event_data = event['data']['object']

        logger.info(f"Processing webhook event: {event_type} ({event['id']})")

        if event_type == 'checkout.session.completed':
            return await self._handle_checkout_completed(event_data, log)
        elif event_type == 'payment_intent.succeeded':
            return await self._handle_payment_succeeded(event_data, log)
        elif event_type == 'invoice.payment_succeeded':
            return await self._handle_subscription_payment(event_data, log)
        elif event_type == 'customer.subscription.deleted':
            return await self._handle_subscription_cancelled(event_data, log)
        else:
            logger.info(f"Unhandled event type: {event_type}")
            return {"status": "unhandled"}

    async def _handle_checkout_completed(self, session_data: Dict, log: StripeWebhookLog) -> Dict:
        """Handle successful checkout completion with proper purchase record creation"""
        try:
            metadata = session_data.get('metadata', {})

            # Extract critical information
            user_id = metadata.get('user_id')
            webhook_id = metadata.get('webhook_id')
            pricing_id = metadata.get('pricing_id')
            stripe_subscription_id = session_data.get('subscription')
            stripe_customer_id = session_data.get('customer')

            # Log metadata for debugging
            log.user_id = int(user_id) if user_id else None
            log.webhook_id = int(webhook_id) if webhook_id else None
            log.customer_id = stripe_customer_id
            log.subscription_id = stripe_subscription_id

            if not all([user_id, webhook_id]):
                raise ValueError(f"Missing required metadata: user_id={user_id}, webhook_id={webhook_id}")

            # Get pricing information
            if not pricing_id:
                # Try to find active pricing for this webhook
                pricing = self.db.query(StrategyPricing).filter(
                    StrategyPricing.webhook_id == int(webhook_id),
                    StrategyPricing.is_active == True
                ).first()

                if not pricing:
                    raise ValueError(f"No active pricing found for webhook {webhook_id}")

                pricing_id = pricing.id
            else:
                pricing = self.db.query(StrategyPricing).filter(
                    StrategyPricing.id == pricing_id
                ).first()

            # Check if purchase already exists
            existing_purchase = self.db.query(StrategyPurchase).filter(
                StrategyPurchase.user_id == int(user_id),
                StrategyPurchase.webhook_id == int(webhook_id),
                StrategyPurchase.stripe_subscription_id == stripe_subscription_id
            ).first()

            if existing_purchase:
                logger.info(f"Purchase already exists for user {user_id}, webhook {webhook_id}")
                return {"status": "already_exists"}

            # Calculate amounts
            amount_paid = float(session_data.get('amount_total', 0)) / 100  # Convert from cents
            platform_fee_percent = 15.0  # 15% platform fee
            platform_fee = amount_paid * (platform_fee_percent / 100)
            creator_payout = amount_paid - platform_fee

            # Create purchase record
            purchase = StrategyPurchase(
                user_id=int(user_id),
                webhook_id=int(webhook_id),
                pricing_id=pricing_id,
                stripe_payment_intent_id=session_data.get('payment_intent'),
                stripe_subscription_id=stripe_subscription_id,
                amount_paid=amount_paid,
                platform_fee=platform_fee,
                creator_payout=creator_payout,
                purchase_type='subscription' if stripe_subscription_id else 'one_time',
                status='active' if stripe_subscription_id else 'COMPLETED'
            )

            self.db.add(purchase)
            self.db.commit()

            logger.info(f"Created purchase record for user {user_id}, webhook {webhook_id}, sub {stripe_subscription_id}")

            # Update user's Stripe customer ID if needed
            user = self.db.query(User).filter(User.id == int(user_id)).first()
            if user and not user.stripe_customer_id:
                user.stripe_customer_id = stripe_customer_id
                self.db.commit()

            return {"status": "success", "purchase_id": purchase.id}

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error handling checkout completion: {e}")
            raise

    async def _handle_payment_succeeded(self, payment_intent: Dict, log: StripeWebhookLog) -> Dict:
        """Handle successful payment intent"""
        # This might be a one-time purchase or first subscription payment
        # The checkout.session.completed event usually handles this
        logger.info(f"Payment intent succeeded: {payment_intent.get('id')}")
        return {"status": "success"}

    async def _handle_subscription_payment(self, invoice_data: Dict, log: StripeWebhookLog) -> Dict:
        """Handle recurring subscription payment"""
        subscription_id = invoice_data.get('subscription')

        if not subscription_id:
            return {"status": "no_subscription"}

        # Update purchase status if needed
        purchase = self.db.query(StrategyPurchase).filter(
            StrategyPurchase.stripe_subscription_id == subscription_id
        ).first()

        if purchase:
            purchase.status = 'active'
            self.db.commit()
            logger.info(f"Updated purchase status for subscription {subscription_id}")

        return {"status": "success"}

    async def _handle_subscription_cancelled(self, subscription_data: Dict, log: StripeWebhookLog) -> Dict:
        """Handle subscription cancellation"""
        subscription_id = subscription_data.get('id')

        purchase = self.db.query(StrategyPurchase).filter(
            StrategyPurchase.stripe_subscription_id == subscription_id
        ).first()

        if purchase:
            purchase.status = 'cancelled'
            self.db.commit()
            logger.info(f"Cancelled subscription {subscription_id}")

        return {"status": "success"}

    async def retry_failed_webhooks(self):
        """Retry failed webhook events (run as background job)"""
        failed_logs = self.db.query(StripeWebhookLog).filter(
            StripeWebhookLog.status == 'failed',
            StripeWebhookLog.retry_count < StripeWebhookLog.max_retries,
            StripeWebhookLog.next_retry_at <= datetime.utcnow()
        ).all()

        for log in failed_logs:
            try:
                logger.info(f"Retrying webhook {log.stripe_event_id} (attempt {log.retry_count + 1})")

                # Re-process the event
                await self._process_event(log.event_data, log)

                # Mark as successful
                log.status = 'success'
                log.processed_at = datetime.utcnow()
                self.db.commit()

            except Exception as e:
                logger.error(f"Retry failed for {log.stripe_event_id}: {e}")
                log.retry_count += 1
                log.error_message = str(e)

                if log.retry_count < log.max_retries:
                    log.next_retry_at = datetime.utcnow() + timedelta(
                        minutes=5 * log.retry_count
                    )
                else:
                    log.status = 'failed_permanent'

                self.db.commit()