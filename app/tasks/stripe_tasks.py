"""
Background tasks for Stripe webhook processing and reconciliation
"""
import logging
from datetime import datetime
from typing import Optional
from app.db.session import SessionLocal
from app.services.stripe_webhook_service import StripeWebhookService
from app.services.stripe_reconciliation_service import StripeReconciliationService

logger = logging.getLogger(__name__)

async def retry_failed_webhooks():
    """Background task to retry failed webhook events"""
    logger.info("Starting webhook retry task")

    db = SessionLocal()
    try:
        service = StripeWebhookService(db)
        await service.retry_failed_webhooks()
        logger.info("Webhook retry task completed")
    except Exception as e:
        logger.error(f"Error in webhook retry task: {e}")
    finally:
        db.close()

async def reconcile_stripe_subscriptions():
    """Background task to reconcile Stripe subscriptions with database"""
    logger.info("Starting Stripe reconciliation task")

    db = SessionLocal()
    try:
        service = StripeReconciliationService(db)
        results = await service.reconcile_subscriptions()

        logger.info(f"Reconciliation completed: {results['checked']} subscriptions checked")

        if results['missing']:
            logger.warning(f"Found {len(results['missing'])} missing purchase records")

        if results['fixed']:
            logger.info(f"Fixed {len(results['fixed'])} missing records")

    except Exception as e:
        logger.error(f"Error in reconciliation task: {e}")
    finally:
        db.close()

async def check_subscription_health():
    """Monitor subscription health and alert on issues"""
    logger.info("Checking subscription health")

    db = SessionLocal()
    try:
        # Check for subscriptions without purchases
        from sqlalchemy import text

        result = db.execute(text("""
            SELECT COUNT(DISTINCT sp.user_id) as affected_users,
                   COUNT(*) as missing_records
            FROM users u
            WHERE u.stripe_customer_id IS NOT NULL
            AND NOT EXISTS (
                SELECT 1 FROM strategy_purchases sp2
                WHERE sp2.user_id = u.id
                AND sp2.stripe_subscription_id IS NOT NULL
            )
        """))

        row = result.first()
        if row and row.missing_records > 0:
            logger.warning(f"Found {row.affected_users} users with Stripe customer IDs but no purchases")

            # Could send alert here

    except Exception as e:
        logger.error(f"Error checking subscription health: {e}")
    finally:
        db.close()