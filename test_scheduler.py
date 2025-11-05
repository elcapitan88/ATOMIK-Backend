"""
Test script to verify strategy scheduler is working correctly
"""
import asyncio
import logging
from datetime import datetime
from sqlalchemy.orm import Session

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def test_scheduler():
    """Test the scheduler functionality"""

    # Test 1: Check if scheduler can be initialized
    logger.info("=" * 60)
    logger.info("TEST 1: Initializing scheduler...")
    try:
        from app.core.scheduler import setup_scheduler, scheduler
        setup_scheduler()
        logger.info("✅ Scheduler initialized successfully")

        # List all jobs
        jobs = scheduler.get_jobs()
        logger.info(f"✅ Found {len(jobs)} scheduled jobs:")
        for job in jobs:
            logger.info(f"   - {job.id}: {job.name} (Next run: {job.next_run_time})")
    except Exception as e:
        logger.error(f"❌ Failed to initialize scheduler: {e}")
        return

    # Test 2: Check market hours
    logger.info("\n" + "=" * 60)
    logger.info("TEST 2: Testing market hours...")
    try:
        from app.core.market_hours import is_market_open, get_market_info

        markets = ['NYSE', 'LONDON', 'ASIA']
        for market in markets:
            is_open = is_market_open(market)
            info = get_market_info(market)
            status = "🟢 OPEN" if is_open else "🔴 CLOSED"
            logger.info(f"{market}: {status}")
            logger.info(f"   Name: {info['name']}")
            logger.info(f"   Hours: {info['display_hours']}")
    except Exception as e:
        logger.error(f"❌ Failed to test market hours: {e}")

    # Test 3: Check database for scheduled strategies
    logger.info("\n" + "=" * 60)
    logger.info("TEST 3: Checking database for scheduled strategies...")
    try:
        from app.db.session import SessionLocal
        from app.models.strategy import ActivatedStrategy

        db = SessionLocal()
        try:
            # Count all strategies
            total_strategies = db.query(ActivatedStrategy).count()
            logger.info(f"Total strategies in database: {total_strategies}")

            # Count scheduled strategies
            scheduled_strategies = db.query(ActivatedStrategy).filter(
                ActivatedStrategy.market_schedule.isnot(None)
            ).all()

            logger.info(f"Scheduled strategies: {len(scheduled_strategies)}")

            if scheduled_strategies:
                for strategy in scheduled_strategies[:5]:  # Show first 5
                    logger.info(f"\nStrategy ID: {strategy.id}")
                    logger.info(f"   Ticker: {strategy.ticker}")
                    logger.info(f"   Active: {strategy.is_active}")
                    logger.info(f"   Market Schedule: {strategy.market_schedule}")
                    logger.info(f"   Schedule State: {strategy.schedule_active_state}")
                    logger.info(f"   Last Toggle: {strategy.last_scheduled_toggle}")
            else:
                logger.warning("⚠️ No scheduled strategies found in database")
                logger.info("To test scheduling, create a strategy with market hours enabled")

        finally:
            db.close()
    except Exception as e:
        logger.error(f"❌ Failed to check database: {e}")

    # Test 4: Run scheduler check manually
    logger.info("\n" + "=" * 60)
    logger.info("TEST 4: Running scheduler check manually...")
    try:
        from app.services.strategy_scheduler_service import check_strategy_schedules

        logger.info("Executing check_strategy_schedules()...")
        await check_strategy_schedules()
        logger.info("✅ Scheduler check completed")
    except Exception as e:
        logger.error(f"❌ Failed to run scheduler check: {e}")
        import traceback
        logger.error(traceback.format_exc())

    # Test 5: Create a test scheduled strategy
    logger.info("\n" + "=" * 60)
    logger.info("TEST 5: Creating test scheduled strategy...")
    try:
        from app.db.session import SessionLocal
        from app.models.strategy import ActivatedStrategy
        from app.models.user import User

        db = SessionLocal()
        try:
            # Find a test user
            user = db.query(User).first()
            if not user:
                logger.warning("⚠️ No users found in database to create test strategy")
            else:
                # Check if test strategy already exists
                test_strategy = db.query(ActivatedStrategy).filter(
                    ActivatedStrategy.ticker == "TEST_SCHEDULER"
                ).first()

                if not test_strategy:
                    # Create a new test strategy
                    test_strategy = ActivatedStrategy(
                        user_id=user.id,
                        strategy_type="single",
                        ticker="TEST_SCHEDULER",
                        webhook_id="test-webhook-scheduler",
                        account_id="TEST_ACCOUNT",
                        quantity=1,
                        is_active=True,
                        market_schedule=["NYSE", "LONDON"],  # Multiple markets
                        schedule_active_state=None
                    )
                    db.add(test_strategy)
                    db.commit()
                    logger.info(f"✅ Created test scheduled strategy with ID: {test_strategy.id}")
                    logger.info(f"   Markets: NYSE, LONDON")
                    logger.info(f"   Strategy will auto-toggle based on market hours")
                else:
                    logger.info(f"✅ Test strategy already exists with ID: {test_strategy.id}")
                    logger.info(f"   Current state: {'Active' if test_strategy.is_active else 'Inactive'}")
                    logger.info(f"   Market schedule: {test_strategy.market_schedule}")
                    logger.info(f"   Last toggle: {test_strategy.last_scheduled_toggle}")
        finally:
            db.close()
    except Exception as e:
        logger.error(f"❌ Failed to create test strategy: {e}")
        import traceback
        logger.error(traceback.format_exc())

    # Cleanup
    logger.info("\n" + "=" * 60)
    logger.info("Shutting down scheduler...")
    from app.core.scheduler import shutdown_scheduler
    shutdown_scheduler()
    logger.info("✅ Scheduler shutdown complete")

    logger.info("\n" + "=" * 60)
    logger.info("SCHEDULER TEST SUMMARY:")
    logger.info("1. Scheduler should be running with strategy_scheduler job")
    logger.info("2. Market hours are being calculated correctly")
    logger.info("3. Check database for scheduled strategies")
    logger.info("4. Scheduler can check strategies manually")
    logger.info("5. Test strategy created for monitoring")
    logger.info("\nTo monitor scheduler in production:")
    logger.info("- Check logs for 'Checking X scheduled strategies' every minute")
    logger.info("- Watch for 'Strategy Y activated/deactivated by scheduler' messages")
    logger.info("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_scheduler())