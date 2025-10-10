"""
Background task scheduler for periodic jobs
"""
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from app.tasks.stripe_tasks import (
    retry_failed_webhooks,
    reconcile_stripe_subscriptions,
    check_subscription_health
)
from app.services.strategy_scheduler_service import check_strategy_schedules

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

def setup_scheduler():
    """Configure and start the background scheduler"""

    # Retry failed webhooks every 15 minutes
    scheduler.add_job(
        retry_failed_webhooks,
        IntervalTrigger(minutes=15),
        id='retry_webhooks',
        name='Retry failed Stripe webhooks',
        replace_existing=True
    )

    # Reconcile Stripe subscriptions every 6 hours
    scheduler.add_job(
        reconcile_stripe_subscriptions,
        IntervalTrigger(hours=6),
        id='reconcile_stripe',
        name='Reconcile Stripe subscriptions',
        replace_existing=True
    )

    # Check subscription health every hour
    scheduler.add_job(
        check_subscription_health,
        IntervalTrigger(hours=1),
        id='check_health',
        name='Check subscription health',
        replace_existing=True
    )

    # Check strategy schedules every minute
    scheduler.add_job(
        check_strategy_schedules,
        IntervalTrigger(minutes=1),
        id='strategy_scheduler',
        name='Toggle strategies based on market hours',
        replace_existing=True
    )

    scheduler.start()
    logger.info("Background scheduler started")

def shutdown_scheduler():
    """Gracefully shutdown the scheduler"""
    scheduler.shutdown()
    logger.info("Background scheduler stopped")