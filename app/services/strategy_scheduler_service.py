"""
Strategy scheduling service for automatic market-based activation
"""
import logging
from datetime import datetime
from typing import List
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.db.session import SessionLocal
from app.models.strategy import ActivatedStrategy
from app.core.market_hours import is_market_open

logger = logging.getLogger(__name__)


async def check_strategy_schedules():
    """
    Check all strategies with market schedules and toggle as needed.
    Strategy is ON if ANY selected market is open.
    This function is called every minute by the scheduler.
    """
    db = SessionLocal()

    try:
        # Get all strategies with market schedules
        scheduled_strategies = db.query(ActivatedStrategy).filter(
            ActivatedStrategy.market_schedule.isnot(None)
        ).all()

        if not scheduled_strategies:
            return

        logger.info(f"Checking {len(scheduled_strategies)} scheduled strategies")

        toggles_made = 0

        for strategy in scheduled_strategies:
            try:
                markets = strategy.market_schedule

                # Skip if no markets or null
                if not markets:
                    continue

                # Handle JSON array of markets
                if isinstance(markets, list):
                    # Check if 24/7 is in the list
                    if '24/7' in markets:
                        continue  # Always on, no scheduling needed

                    # Check if ANY market is open
                    any_market_open = any(is_market_open(market) for market in markets)
                else:
                    # Backward compatibility: single string value
                    if markets == '24/7':
                        continue
                    any_market_open = is_market_open(markets)

                # Determine if we need to toggle
                should_toggle = False
                new_state = None

                if any_market_open and not strategy.is_active:
                    # At least one market is open but strategy is off - turn it on
                    should_toggle = True
                    new_state = True
                    markets_str = ', '.join(markets) if isinstance(markets, list) else markets
                    logger.info(f"Activating strategy {strategy.id} - market(s) open: {markets_str}")

                elif not any_market_open and strategy.is_active:
                    # All markets are closed but strategy is on - turn it off
                    # Only if it was previously toggled by scheduler or is newly scheduled
                    if strategy.schedule_active_state is not False:
                        should_toggle = True
                        new_state = False
                        markets_str = ', '.join(markets) if isinstance(markets, list) else markets
                        logger.info(f"Deactivating strategy {strategy.id} - all markets closed: {markets_str}")

                if should_toggle:
                    # Update strategy state
                    strategy.is_active = new_state
                    strategy.schedule_active_state = new_state
                    strategy.last_scheduled_toggle = datetime.utcnow()
                    toggles_made += 1

                    # Log the scheduled action
                    action = "activated" if new_state else "deactivated"
                    markets_str = ', '.join(markets) if isinstance(markets, list) else markets
                    logger.info(
                        f"Strategy {strategy.id} {action} by scheduler "
                        f"(markets: {markets_str}, user: {strategy.user_id})"
                    )

            except Exception as e:
                logger.error(f"Error processing scheduled strategy {strategy.id}: {e}")
                continue

        # Commit all changes
        db.commit()
        logger.info(f"Scheduler run complete: {toggles_made} strategies toggled")

    except Exception as e:
        logger.error(f"Error in strategy scheduler: {e}")
        db.rollback()
    finally:
        db.close()


async def override_scheduled_state(strategy_id: int, new_state: bool, db: Session):
    """
    Handle manual override of a scheduled strategy.
    When user manually toggles, we respect their choice until next scheduled event.

    Args:
        strategy_id: ID of the strategy being manually toggled
        new_state: The new active state set by the user
        db: Database session
    """
    strategy = db.query(ActivatedStrategy).filter(
        ActivatedStrategy.id == strategy_id
    ).first()

    if strategy and strategy.market_schedule:
        # Clear the schedule active state to indicate manual override
        strategy.schedule_active_state = None
        logger.info(
            f"Strategy {strategy_id} manually overridden to {new_state} "
            f"(scheduled for {strategy.market_schedule})"
        )
