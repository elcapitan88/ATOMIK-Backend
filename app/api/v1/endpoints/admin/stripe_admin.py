"""
Admin endpoints for Stripe webhook management and reconciliation
"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Dict, Any, List
import logging

from app.db.session import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.services.stripe_webhook_service import StripeWebhookService
from app.services.stripe_reconciliation_service import StripeReconciliationService
from app.models.stripe_webhook_log import StripeWebhookLog
from app.tasks.stripe_tasks import retry_failed_webhooks, reconcile_stripe_subscriptions

router = APIRouter(prefix="/admin/stripe", tags=["admin-stripe"])
logger = logging.getLogger(__name__)

def require_admin(current_user: User = Depends(get_current_user)):
    """Require admin access"""
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user

@router.get("/webhook-logs")
async def get_webhook_logs(
    status: str = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin)
) -> List[Dict]:
    """Get recent webhook logs"""
    query = db.query(StripeWebhookLog)

    if status:
        query = query.filter(StripeWebhookLog.status == status)

    logs = query.order_by(StripeWebhookLog.received_at.desc()).limit(limit).all()

    return [
        {
            "id": log.id,
            "event_id": log.stripe_event_id,
            "event_type": log.event_type,
            "status": log.status,
            "retry_count": log.retry_count,
            "error_message": log.error_message,
            "received_at": log.received_at,
            "processed_at": log.processed_at,
            "user_id": log.user_id,
            "webhook_id": log.webhook_id
        }
        for log in logs
    ]

@router.post("/retry-webhooks")
async def trigger_webhook_retry(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin)
) -> Dict:
    """Manually trigger webhook retry for failed events"""
    # Count failed webhooks
    failed_count = db.query(StripeWebhookLog).filter(
        StripeWebhookLog.status == 'failed',
        StripeWebhookLog.retry_count < StripeWebhookLog.max_retries
    ).count()

    # Add to background tasks
    background_tasks.add_task(retry_failed_webhooks)

    return {
        "status": "triggered",
        "failed_webhooks": failed_count,
        "message": f"Retrying {failed_count} failed webhooks in background"
    }

@router.post("/reconcile")
async def trigger_reconciliation(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin)
) -> Dict:
    """Manually trigger Stripe subscription reconciliation"""
    background_tasks.add_task(reconcile_stripe_subscriptions)

    return {
        "status": "triggered",
        "message": "Reconciliation started in background"
    }

@router.get("/check-user/{user_id}")
async def check_user_subscriptions(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin)
) -> Dict:
    """Check specific user's subscription status"""
    service = StripeReconciliationService(db)
    result = await service.check_user_subscription(user_id)
    return result

@router.post("/fix-user/{user_id}")
async def fix_user_subscription(
    user_id: int,
    stripe_subscription_id: str,
    webhook_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin)
) -> Dict:
    """Manually fix a user's missing purchase record"""
    service = StripeReconciliationService(db)
    success = await service.fix_specific_user(
        user_id=user_id,
        stripe_subscription_id=stripe_subscription_id,
        webhook_id=webhook_id
    )

    if success:
        return {
            "status": "success",
            "message": f"Fixed purchase record for user {user_id}"
        }
    else:
        raise HTTPException(
            status_code=500,
            detail="Failed to fix user subscription"
        )

@router.get("/subscription-health")
async def get_subscription_health(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin)
) -> Dict:
    """Get overall subscription health metrics"""
    from sqlalchemy import text

    # Get various health metrics
    metrics = {}

    # Count missing purchase records
    result = db.execute(text("""
        SELECT COUNT(*) as count
        FROM users u
        WHERE u.stripe_customer_id IS NOT NULL
        AND NOT EXISTS (
            SELECT 1 FROM strategy_purchases sp
            WHERE sp.user_id = u.id
            AND sp.stripe_subscription_id IS NOT NULL
        )
    """)).first()

    metrics['users_with_stripe_but_no_purchase'] = result.count if result else 0

    # Count failed webhooks
    failed_webhooks = db.query(StripeWebhookLog).filter(
        StripeWebhookLog.status.in_(['failed', 'failed_permanent'])
    ).count()

    metrics['failed_webhooks'] = failed_webhooks

    # Count orphaned purchases (purchase exists but no user subscription)
    result = db.execute(text("""
        SELECT COUNT(*) as count
        FROM strategy_purchases sp
        WHERE sp.stripe_subscription_id IS NOT NULL
        AND sp.status = 'active'
        AND NOT EXISTS (
            SELECT 1 FROM webhook_subscriptions ws
            WHERE ws.user_id = sp.user_id
            AND ws.webhook_id = sp.webhook_id
        )
    """)).first()

    metrics['orphaned_purchases'] = result.count if result else 0

    # Overall health score (0-100)
    issues = (
        metrics['users_with_stripe_but_no_purchase'] +
        metrics['failed_webhooks'] +
        metrics['orphaned_purchases']
    )

    if issues == 0:
        health_score = 100
    elif issues < 5:
        health_score = 90
    elif issues < 10:
        health_score = 70
    else:
        health_score = 50

    return {
        "health_score": health_score,
        "metrics": metrics,
        "status": "healthy" if health_score > 80 else "needs_attention"
    }