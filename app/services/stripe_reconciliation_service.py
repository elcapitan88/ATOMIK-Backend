"""
Stripe reconciliation service to sync database with Stripe subscriptions
"""
import stripe
import logging
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.models.user import User
from app.models.strategy_purchase import StrategyPurchase
from app.models.webhook import Webhook
from app.models.strategy_pricing import StrategyPricing
from app.core.config import settings
from app.services.email.email_notification import send_email

logger = logging.getLogger(__name__)

class StripeReconciliationService:
    """Service to reconcile Stripe subscriptions with database records"""

    def __init__(self, db: Session):
        self.db = db
        stripe.api_key = settings.STRIPE_SECRET_KEY

    async def reconcile_subscriptions(self) -> Dict[str, any]:
        """Main reconciliation job - compare Stripe with database"""
        results = {
            'checked': 0,
            'missing': [],
            'fixed': [],
            'errors': []
        }

        try:
            # Get all active Stripe subscriptions
            subscriptions = stripe.Subscription.list(
                status='active',
                limit=100  # Adjust as needed
            )

            for subscription in subscriptions.auto_paging_iter():
                results['checked'] += 1

                # Check if we have a matching purchase record
                purchase = self.db.query(StrategyPurchase).filter(
                    StrategyPurchase.stripe_subscription_id == subscription.id
                ).first()

                if not purchase:
                    # Missing purchase record!
                    missing_info = await self._handle_missing_purchase(subscription)
                    results['missing'].append(missing_info)

                    if missing_info.get('fixed'):
                        results['fixed'].append(missing_info)

        except Exception as e:
            logger.error(f"Reconciliation error: {e}")
            results['errors'].append(str(e))

        # Send alert if issues found
        if results['missing']:
            await self._send_reconciliation_alert(results)

        return results

    async def _handle_missing_purchase(self, subscription: stripe.Subscription) -> Dict:
        """Handle a Stripe subscription without database record"""
        info = {
            'subscription_id': subscription.id,
            'customer_id': subscription.customer,
            'status': subscription.status,
            'created': datetime.fromtimestamp(subscription.created),
            'fixed': False
        }

        try:
            # Try to extract metadata
            metadata = subscription.metadata or {}

            # Get customer email
            customer = stripe.Customer.retrieve(subscription.customer)
            info['customer_email'] = customer.email

            # Find user by email or stripe customer ID
            user = self.db.query(User).filter(
                or_(
                    User.email == customer.email,
                    User.stripe_customer_id == subscription.customer
                )
            ).first()

            if not user:
                info['issue'] = 'User not found'
                return info

            info['user_id'] = user.id

            # Extract webhook/strategy info from metadata
            webhook_id = metadata.get('webhook_id')
            pricing_id = metadata.get('pricing_id')

            if not webhook_id:
                # Try to find from subscription items
                if subscription.items:
                    item = subscription.items.data[0]
                    price_id = item.price.id

                    # Find pricing by stripe price ID
                    pricing = self.db.query(StrategyPricing).filter(
                        or_(
                            StrategyPricing.stripe_price_id_monthly == price_id,
                            StrategyPricing.stripe_price_id_yearly == price_id
                        )
                    ).first()

                    if pricing:
                        webhook_id = pricing.webhook_id
                        pricing_id = pricing.id

            if not webhook_id:
                info['issue'] = 'Cannot determine strategy/webhook'
                return info

            info['webhook_id'] = webhook_id

            # Find pricing if not already found
            if not pricing_id:
                pricing = self.db.query(StrategyPricing).filter(
                    StrategyPricing.webhook_id == webhook_id,
                    StrategyPricing.is_active == True
                ).first()

                if pricing:
                    pricing_id = pricing.id

            # Create the missing purchase record
            amount = subscription.items.data[0].price.unit_amount / 100 if subscription.items else 0
            platform_fee = amount * 0.15  # 15% platform fee
            creator_payout = amount - platform_fee

            purchase = StrategyPurchase(
                user_id=user.id,
                webhook_id=webhook_id,
                pricing_id=pricing_id,
                stripe_subscription_id=subscription.id,
                stripe_payment_intent_id=f'reconciled_{subscription.id}',
                amount_paid=amount,
                platform_fee=platform_fee,
                creator_payout=creator_payout,
                purchase_type='subscription',
                status='active'
            )

            self.db.add(purchase)
            self.db.commit()

            info['fixed'] = True
            info['action'] = 'Created missing purchase record'

            logger.info(f"Reconciled subscription {subscription.id} for user {user.id}")

        except Exception as e:
            info['error'] = str(e)
            logger.error(f"Failed to reconcile subscription {subscription.id}: {e}")

        return info

    async def check_user_subscription(self, user_id: int) -> Dict:
        """Check specific user's subscriptions"""
        results = {
            'user_id': user_id,
            'stripe_subscriptions': [],
            'database_purchases': [],
            'issues': []
        }

        try:
            # Get user
            user = self.db.query(User).filter(User.id == user_id).first()
            if not user:
                results['issues'].append('User not found')
                return results

            # Get Stripe subscriptions
            if user.stripe_customer_id:
                subscriptions = stripe.Subscription.list(
                    customer=user.stripe_customer_id
                )

                for sub in subscriptions.data:
                    results['stripe_subscriptions'].append({
                        'id': sub.id,
                        'status': sub.status,
                        'created': datetime.fromtimestamp(sub.created)
                    })

            # Get database purchases
            purchases = self.db.query(StrategyPurchase).filter(
                StrategyPurchase.user_id == user_id
            ).all()

            for purchase in purchases:
                results['database_purchases'].append({
                    'webhook_id': purchase.webhook_id,
                    'status': purchase.status,
                    'stripe_sub_id': purchase.stripe_subscription_id
                })

            # Compare
            stripe_sub_ids = {s['id'] for s in results['stripe_subscriptions']}
            db_sub_ids = {p['stripe_sub_id'] for p in results['database_purchases'] if p['stripe_sub_id']}

            missing_in_db = stripe_sub_ids - db_sub_ids
            missing_in_stripe = db_sub_ids - stripe_sub_ids

            if missing_in_db:
                results['issues'].append(f"Subscriptions in Stripe but not database: {missing_in_db}")

            if missing_in_stripe:
                results['issues'].append(f"Subscriptions in database but not Stripe: {missing_in_stripe}")

        except Exception as e:
            results['issues'].append(f"Error: {e}")

        return results

    async def _send_reconciliation_alert(self, results: Dict):
        """Send alert email about reconciliation issues"""
        if not results['missing']:
            return

        subject = f"[ALERT] Stripe Reconciliation: {len(results['missing'])} Missing Records"

        body = f"""
        <h2>Stripe Reconciliation Alert</h2>
        <p>The following Stripe subscriptions have no database records:</p>
        <ul>
        """

        for item in results['missing']:
            body += f"""
            <li>
                Subscription: {item['subscription_id']}<br>
                Customer: {item.get('customer_email', 'Unknown')}<br>
                User ID: {item.get('user_id', 'Not found')}<br>
                Status: {item.get('fixed') and 'FIXED' or item.get('issue', 'Unknown issue')}<br>
            </li>
            """

        body += """
        </ul>
        <p>Please review and fix any remaining issues.</p>
        """

        # Send to admin email
        if settings.ADMIN_EMAIL:
            await send_email(
                to_email=settings.ADMIN_EMAIL,
                subject=subject,
                body=body
            )

    async def fix_specific_user(self, user_id: int, stripe_subscription_id: str, webhook_id: int) -> bool:
        """Manually fix a specific user's missing purchase record"""
        try:
            # Get user
            user = self.db.query(User).filter(User.id == user_id).first()
            if not user:
                logger.error(f"User {user_id} not found")
                return False

            # Get pricing
            pricing = self.db.query(StrategyPricing).filter(
                StrategyPricing.webhook_id == webhook_id,
                StrategyPricing.is_active == True
            ).first()

            if not pricing:
                logger.error(f"No active pricing for webhook {webhook_id}")
                return False

            # Get subscription details from Stripe
            try:
                subscription = stripe.Subscription.retrieve(stripe_subscription_id)
                amount = subscription.items.data[0].price.unit_amount / 100
            except:
                amount = 29.99  # Default amount

            # Create purchase record
            platform_fee = amount * 0.15
            creator_payout = amount - platform_fee

            purchase = StrategyPurchase(
                user_id=user_id,
                webhook_id=webhook_id,
                pricing_id=pricing.id,
                stripe_subscription_id=stripe_subscription_id,
                stripe_payment_intent_id=f'manual_fix_{stripe_subscription_id}',
                amount_paid=amount,
                platform_fee=platform_fee,
                creator_payout=creator_payout,
                purchase_type='subscription',
                status='active'
            )

            self.db.add(purchase)
            self.db.commit()

            logger.info(f"Fixed missing purchase for user {user_id}, subscription {stripe_subscription_id}")
            return True

        except Exception as e:
            logger.error(f"Error fixing user {user_id}: {e}")
            self.db.rollback()
            return False