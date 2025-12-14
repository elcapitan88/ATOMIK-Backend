from fastapi import APIRouter, Depends, HTTPException, Header, Response, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.exc import SQLAlchemyError
from typing import List, Union, Optional, Dict, Any
import logging
import traceback
import json
from pydantic import ValidationError
from app.core.config import settings
from decimal import Decimal

from app.core.security import get_current_user
from app.services.strategy_service import StrategyProcessor
from app.db.session import get_db
from app.models.strategy import ActivatedStrategy, strategy_follower_quantities 
from app.models.webhook import Webhook, WebhookSubscription
from app.models.strategy_purchase import StrategyPurchase
from app.services.subscription_service import SubscriptionService
from app.models.subscription import Subscription
from app.models.broker import BrokerAccount
from app.core.upgrade_prompts import add_upgrade_headers, UpgradeReason, upgrade_exception
from app.schemas.strategy import (
    SingleStrategyCreate,
    MultipleStrategyCreate,
    StrategyUpdate,
    StrategyInDB,
    StrategyResponse,
    StrategyType,
    StrategyStats,
    EngineStrategyCreate,
    EngineStrategyResponse,
    EngineStrategyUpdate,
    ExecutionType
)
from app.models.strategy_code import StrategyCode
from app.utils.ticker_utils import get_display_ticker, validate_ticker
from app.core.permissions import (
    check_subscription,
    check_resource_limit,
    check_feature_access,
    require_tier
)
from app.core.market_hours import is_market_open, get_market_info, get_next_market_event
from app.services.strategy_scheduler_service import override_scheduled_state

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/{strategy_id}/execute")
@check_subscription
async def execute_strategy_manually(
    strategy_id: int,
    action_data: Dict[str, Any],
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Execute a strategy manually from the UI"""
    try:
        strategy = db.query(ActivatedStrategy).filter(
            ActivatedStrategy.id == strategy_id,
            ActivatedStrategy.user_id == current_user.id
        ).first()
        
        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")
        
        # Create signal data from action
        signal_data = {
            "action": action_data["action"],
            "order_type": "MARKET",
            "time_in_force": "GTC"
        }
        
        # Use existing strategy processor
        strategy_processor = StrategyProcessor(db)
        result = await strategy_processor.execute_strategy(strategy, signal_data)
        
        return result
    except Exception as e:
        logger.error(f"Manual strategy execution error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to execute strategy: {str(e)}"
        )

@router.post("/activate", response_model=StrategyResponse)
@check_subscription
async def activate_strategy(
    *,
    db: Session = Depends(get_db),
    strategy: Union[SingleStrategyCreate, MultipleStrategyCreate],
    current_user = Depends(get_current_user),
    response: Response = None,  # Added Response parameter
    idempotency_key: Optional[str] = Header(None)
):
    try:
        logger.info(f"Creating strategy for user {current_user.id}")
        logger.debug(f"Strategy data received: {strategy.dict()}")

        # Determine execution type and validate strategy source
        webhook = None
        strategy_code = None
        execution_type = 'webhook'
        is_owner = False
        
        if strategy.webhook_id:
            # Webhook-based strategy validation
            webhook = db.query(Webhook).filter(
                Webhook.token == str(strategy.webhook_id)
            ).first()

            if not webhook:
                raise HTTPException(status_code=404, detail="Webhook not found")

            # Check if user has access to this webhook
            is_owner = webhook.user_id == current_user.id
            
            # Check free subscription access
            is_subscriber = db.query(WebhookSubscription).filter(
                WebhookSubscription.webhook_id == webhook.id,
                WebhookSubscription.user_id == current_user.id
            ).first() is not None
            
            # Check purchased strategy access (for monetized strategies)
            has_purchase = db.query(StrategyPurchase).filter(
                StrategyPurchase.webhook_id == webhook.id,
                StrategyPurchase.user_id == current_user.id,
                StrategyPurchase.status == "COMPLETED"
            ).first() is not None

            if not (is_owner or is_subscriber or has_purchase):
                raise HTTPException(
                    status_code=403,
                    detail="You don't have access to this webhook"
                )

            # SPECIAL CASE: Break N Enter should use engine execution
            if webhook.id == 117:  # Break N Enter webhook ID
                logger.info("Converting Break N Enter activation to engine execution")

                # Find the corresponding strategy_code
                # StrategyCode is already imported at the top
                strategy_code = db.query(StrategyCode).filter(
                    StrategyCode.name == 'break_and_enter',
                    StrategyCode.is_active == True,
                    StrategyCode.is_validated == True
                ).first()

                if strategy_code:
                    logger.info(f"Found strategy_code {strategy_code.id} for Break N Enter")
                    execution_type = 'engine'
                else:
                    logger.warning("Break N Enter strategy_code not found, falling back to webhook")
                    execution_type = 'webhook'
            else:
                execution_type = 'webhook'
            
        elif strategy.strategy_code_id:
            # Engine-based strategy validation
            # StrategyCode is already imported at the top
            strategy_code = db.query(StrategyCode).filter(
                StrategyCode.id == strategy.strategy_code_id,
                StrategyCode.is_active == True,
                StrategyCode.is_validated == True
            ).first()
            
            if not strategy_code:
                raise HTTPException(
                    status_code=404, 
                    detail="Engine strategy not found or not available"
                )
            
            # Check if user has access to this engine strategy
            is_owner = strategy_code.user_id == current_user.id
            
            # Check engine strategy subscription access
            is_subscriber = db.query(WebhookSubscription).filter(
                WebhookSubscription.strategy_code_id == strategy.strategy_code_id,
                WebhookSubscription.user_id == current_user.id,
                WebhookSubscription.strategy_type == 'engine'
            ).first() is not None
            
            if not (is_owner or is_subscriber):
                raise HTTPException(
                    status_code=403,
                    detail="You don't have access to this engine strategy. Please subscribe first."
                )
            
            execution_type = 'engine'

        # Check resource limits based on ownership
        resource_type = "active_strategies_owned" if is_owner else "active_strategies_subscribed"
        subscription_service = SubscriptionService(db)
        can_add, message = subscription_service.can_add_resource(
            current_user.id, 
            resource_type
        )
        
        if not can_add and not settings.SKIP_SUBSCRIPTION_CHECK:
            # Add upgrade headers if response object available
            if response:
                # Get user's subscription tier
                user_tier = subscription_service.get_user_tier(current_user.id)
                
                # Map reason
                reason = UpgradeReason.STRATEGY_LIMIT
                add_upgrade_headers(response, user_tier, reason)
            
            raise HTTPException(status_code=403, detail=message)

        # Validate and convert ticker to display format
        valid, _ = validate_ticker(strategy.ticker)
        if not valid:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid ticker format: {strategy.ticker}"
            )
        
        # Convert to display ticker (e.g., ESU5 -> ES, or ES -> ES)
        display_ticker = get_display_ticker(strategy.ticker)
        logger.info(f"Converted ticker {strategy.ticker} to display ticker {display_ticker}")

        try:
            if isinstance(strategy, SingleStrategyCreate):
                logger.info("Processing single account strategy")
                
                # Validate broker account
                broker_account = db.query(BrokerAccount).filter(
                    BrokerAccount.account_id == str(strategy.account_id),
                    BrokerAccount.user_id == current_user.id,
                    BrokerAccount.is_active == True
                ).first()
                
                if not broker_account:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Broker account {strategy.account_id} not found or inactive"
                    )

                # Check for existing strategy with same source and account
                if execution_type == 'webhook':
                    existing_strategy = db.query(ActivatedStrategy).filter(
                        ActivatedStrategy.webhook_id == str(strategy.webhook_id),
                        ActivatedStrategy.account_id == str(strategy.account_id),
                        ActivatedStrategy.user_id == current_user.id
                    ).first()
                    error_detail = "A strategy with this webhook and account already exists"
                else:  # engine
                    # For engine mode, check against strategy_code_id
                    strategy_code_to_check = strategy_code.id if strategy_code else strategy.strategy_code_id
                    existing_strategy = db.query(ActivatedStrategy).filter(
                        ActivatedStrategy.strategy_code_id == strategy_code_to_check,
                        ActivatedStrategy.account_id == str(strategy.account_id),
                        ActivatedStrategy.user_id == current_user.id
                    ).first()
                    error_detail = "A strategy with this strategy code and account already exists"

                if existing_strategy:
                    raise HTTPException(status_code=400, detail=error_detail)

                # Create single account strategy with appropriate execution type
                # For Break N Enter engine mode, use strategy_code_id instead of webhook_id
                final_webhook_id = str(strategy.webhook_id) if strategy.webhook_id and execution_type == 'webhook' else None
                final_strategy_code_id = strategy_code.id if strategy_code else (strategy.strategy_code_id if strategy.strategy_code_id else None)

                db_strategy = ActivatedStrategy(
                    user_id=current_user.id,
                    strategy_type="single",
                    execution_type=execution_type,
                    webhook_id=final_webhook_id,
                    strategy_code_id=final_strategy_code_id,
                    ticker=display_ticker,
                    account_id=str(strategy.account_id),
                    quantity=strategy.quantity,
                    is_active=True
                )

                # Handle market schedule if provided
                if hasattr(strategy, 'market_schedule') and strategy.market_schedule:
                    db_strategy.market_schedule = strategy.market_schedule
                    # Set initial schedule state - ON if ANY market is open
                    if '24/7' not in strategy.market_schedule:
                        any_market_open = any(is_market_open(market) for market in strategy.market_schedule)
                        db_strategy.schedule_active_state = any_market_open
                    else:
                        db_strategy.schedule_active_state = None
                
                db.add(db_strategy)
                db.flush()

                logger.debug(f"Created strategy object with ID: {db_strategy.id}")

                # Create empty stats for new strategy
                stats = StrategyStats.create_empty()
                
                # Prepare response data
                strategy_data = {
                    "id": db_strategy.id,
                    "strategy_type": db_strategy.strategy_type,
                    "webhook_id": db_strategy.webhook_id,
                    "ticker": db_strategy.ticker,
                    "is_active": db_strategy.is_active,
                    "created_at": db_strategy.created_at,
                    "last_triggered": db_strategy.last_triggered,
                    "account_id": broker_account.account_id,
                    "quantity": db_strategy.quantity,
                    "broker_account": {
                        "account_id": broker_account.account_id,
                        "name": broker_account.name,
                        "broker_id": broker_account.broker_id
                    },
                    "webhook": {
                        "name": webhook.name,
                        "source_type": webhook.source_type
                    },
                    "stats": stats.to_summary_dict()
                }

            else:  # MultipleStrategyCreate
                logger.info("Processing multiple account strategy")

                # Check if user has access to group strategies
                subscription_service = SubscriptionService(db)
                has_access, message = subscription_service.is_feature_available(
                    current_user.id, 
                    "group_strategies_allowed"
                )
                
                if not has_access and not settings.SKIP_SUBSCRIPTION_CHECK:
                    # Get user's tier
                    user_tier = subscription_service.get_user_tier(current_user.id)
                    
                    # Add upgrade headers
                    if response:
                        add_upgrade_headers(response, user_tier, UpgradeReason.GROUP_STRATEGY)
                    
                    # Raise exception with detailed upgrade info
                    raise upgrade_exception(
                        reason=UpgradeReason.GROUP_STRATEGY,
                        current_tier=user_tier,
                        detail="Group strategies require Pro tier or higher"
                    )
                
                # Validate leader account
                leader_account = db.query(BrokerAccount).filter(
                    BrokerAccount.account_id == strategy.leader_account_id,
                    BrokerAccount.user_id == current_user.id,
                    BrokerAccount.is_active == True
                ).first()
                
                if not leader_account:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Leader account {strategy.leader_account_id} not found or inactive"
                    )

                # Validate follower accounts
                if len(strategy.follower_account_ids) != len(strategy.follower_quantities):
                    raise HTTPException(
                        status_code=400,
                        detail="Number of follower accounts must match number of quantities"
                    )

                follower_accounts = []
                existing_account_ids = {leader_account.account_id}

                for follower_id in strategy.follower_account_ids:
                    if follower_id in existing_account_ids:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Duplicate account ID: {follower_id}"
                        )
                    existing_account_ids.add(follower_id)

                    follower = db.query(BrokerAccount).filter(
                        BrokerAccount.account_id == follower_id,
                        BrokerAccount.user_id == current_user.id,
                        BrokerAccount.is_active == True
                    ).first()

                    if not follower:
                        raise HTTPException(
                            status_code=404,
                            detail=f"Follower account {follower_id} not found or inactive"
                        )

                    follower_accounts.append(follower)

                # Create multiple account strategy with appropriate execution type
                db_strategy = ActivatedStrategy(
                    user_id=current_user.id,
                    strategy_type="multiple",
                    execution_type=execution_type,
                    webhook_id=str(strategy.webhook_id) if strategy.webhook_id else None,
                    strategy_code_id=strategy.strategy_code_id if strategy.strategy_code_id else None,
                    ticker=display_ticker,
                    leader_account_id=leader_account.account_id,
                    leader_quantity=strategy.leader_quantity,
                    group_name=strategy.group_name,
                    is_active=True
                )

                # Handle market schedule if provided
                if hasattr(strategy, 'market_schedule') and strategy.market_schedule:
                    db_strategy.market_schedule = strategy.market_schedule
                    # Set initial schedule state - ON if ANY market is open
                    if '24/7' not in strategy.market_schedule:
                        any_market_open = any(is_market_open(market) for market in strategy.market_schedule)
                        db_strategy.schedule_active_state = any_market_open
                    else:
                        db_strategy.schedule_active_state = None

                db.add(db_strategy)
                db.flush()

                # Add follower relationships
                for idx, follower in enumerate(follower_accounts):
                    db.execute(
                        strategy_follower_quantities.insert().values(
                            strategy_id=db_strategy.id,
                            account_id=follower.account_id,
                            quantity=strategy.follower_quantities[idx]
                        )
                    )

                stats = StrategyStats.create_empty()

                # Prepare response data for multiple strategy
                strategy_data = {
                    "id": db_strategy.id,
                    "strategy_type": db_strategy.strategy_type,
                    "webhook_id": db_strategy.webhook_id,
                    "ticker": db_strategy.ticker,
                    "is_active": db_strategy.is_active,
                    "created_at": db_strategy.created_at,
                    "last_triggered": db_strategy.last_triggered,
                    "group_name": db_strategy.group_name,
                    "leader_account_id": leader_account.account_id,
                    "leader_quantity": db_strategy.leader_quantity,
                    "leader_broker_account": {
                        "account_id": leader_account.account_id,
                        "name": leader_account.name,
                        "broker_id": leader_account.broker_id
                    },
                    "follower_accounts": [
                        {
                            "account_id": acc.account_id,
                            "quantity": strategy.follower_quantities[idx]
                        }
                        for idx, acc in enumerate(follower_accounts)
                    ],
                    "webhook": {
                        "name": webhook.name,
                        "source_type": webhook.source_type
                    },
                    "stats": stats.to_summary_dict()
                }
                
            # Update subscription counter
            subscription = db.query(Subscription).filter(
                Subscription.user_id == current_user.id
            ).first()

            if subscription:
                subscription.active_strategies_count = (subscription.active_strategies_count or 0) + 1

            db.commit()
            logger.info(f"Successfully created strategy with ID: {db_strategy.id}")
            
            return StrategyResponse(**strategy_data)

        except HTTPException:
            db.rollback()
            raise
        except Exception as e:
            db.rollback()
            logger.error(f"Database error: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Error creating strategy: {str(e)}"
            )

    except ValidationError as ve:
        logger.error(f"Validation error: {str(ve)}")
        raise HTTPException(
            status_code=422,
            detail=str(ve)
        )
    except HTTPException as he:
        logger.error(f"HTTP Exception in activate_strategy: {he.status_code}: {he.detail}")
        raise he
    except Exception as e:
        logger.error(f"Error activating strategy: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to activate strategy: {str(e)}"
        )
    
@router.get("/list", response_model=List[StrategyResponse])
@check_subscription
async def list_strategies(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
    response: Response = None  # Added Response parameter
):
    try:
        logger.info(f"Fetching strategies for user {current_user.id}")
        
        strategies = (
            db.query(ActivatedStrategy)
            .filter(ActivatedStrategy.user_id == current_user.id)
            .options(
                joinedload(ActivatedStrategy.broker_account),
                joinedload(ActivatedStrategy.leader_broker_account),
                joinedload(ActivatedStrategy.webhook)
            )
            .all()
        )

        # Add upgrade suggestion if approaching strategy limits
        if not settings.SKIP_SUBSCRIPTION_CHECK:
            subscription = db.query(Subscription).filter(
                Subscription.user_id == current_user.id
            ).first()
            
            if subscription:
                user_tier = subscription.tier
                max_strategies = float('inf')
                
                if user_tier == "starter":
                    max_strategies = 1
                elif user_tier == "pro":
                    max_strategies = 5
                    
                # Add upgrade headers if approaching limit
                if len(strategies) >= max_strategies - 1 and user_tier != "elite":
                    # Add standardized upgrade headers
                    add_upgrade_headers(response, user_tier, UpgradeReason.STRATEGY_LIMIT)

        response_strategies = []
        for strategy in strategies:
            try:
                strategy_data = {
                    "id": strategy.id,
                    "strategy_type": strategy.strategy_type,
                    "webhook_id": strategy.webhook_id,
                    "ticker": strategy.ticker,
                    "is_active": strategy.is_active,
                    "created_at": strategy.created_at,
                    "last_triggered": strategy.last_triggered,
                    "webhook": {
                        "name": strategy.webhook.name if strategy.webhook else None,
                        "source_type": strategy.webhook.source_type if strategy.webhook else "custom"
                    }
                }

                if strategy.strategy_type == "single":
                    # Add single strategy specific fields
                    strategy_data.update({
                        "account_id": strategy.account_id,
                        "quantity": strategy.quantity,
                        "broker_account": {
                            "account_id": strategy.broker_account.account_id,
                            "name": strategy.broker_account.name,
                            "broker_id": strategy.broker_account.broker_id
                        } if strategy.broker_account else None,
                        "leader_account_id": None,
                        "leader_quantity": None,
                        "leader_broker_account": None,
                        "follower_accounts": [],
                        "group_name": None
                    })
                else:
                    # Multiple strategy fields remain the same
                    strategy_data.update({
                        "group_name": strategy.group_name,
                        "leader_account_id": strategy.leader_account_id,
                        "leader_quantity": strategy.leader_quantity,
                        "leader_broker_account": {
                            "account_id": strategy.leader_broker_account.account_id,
                            "name": strategy.leader_broker_account.name,
                            "broker_id": strategy.leader_broker_account.broker_id
                        } if strategy.leader_broker_account else None,
                        "follower_accounts": strategy.get_follower_accounts(),
                        "account_id": None,
                        "quantity": None
                    })

                # Add stats
                strategy_data["stats"] = {
                    "total_trades": strategy.total_trades,
                    "successful_trades": strategy.successful_trades,
                    "failed_trades": strategy.failed_trades,
                    "total_pnl": float(strategy.total_pnl) if strategy.total_pnl else 0,
                    "win_rate": float(strategy.win_rate) if strategy.win_rate else None,
                    "average_trade_pnl": None  # Add calculation if needed
                }

                response_strategies.append(strategy_data)

            except Exception as strategy_error:
                logger.error(f"Error processing strategy {strategy.id}: {str(strategy_error)}")
                continue

        return response_strategies

    except Exception as e:
        logger.error(f"Error in list_strategies: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail="An error occurred while fetching strategies"
        )


@router.get("/user-activated", response_model=Dict[str, Any])
@check_subscription
async def get_user_activated_strategies(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Get user's activated strategies - strategies they have subscribed to or activated that are currently trading.
    Returns detailed information including webhook names, follower accounts, performance metrics, etc.
    This replaces the problematic /list endpoint with proper data enrichment.
    """
    try:
        user_strategies = []
        
        # Get user's activated strategies with proper joins
        activated_strategies = (
            db.query(ActivatedStrategy)
            .filter(ActivatedStrategy.user_id == current_user.id)
            .options(
                joinedload(ActivatedStrategy.broker_account),
                joinedload(ActivatedStrategy.leader_broker_account),
                joinedload(ActivatedStrategy.webhook),
                joinedload(ActivatedStrategy.strategy_code)
            )
            .all()
        )
        
        for strategy in activated_strategies:
            # Base strategy data
            strategy_data = {
                "id": strategy.id,
                "user_id": strategy.user_id,
                "strategy_type": strategy.strategy_type,
                "execution_type": strategy.execution_type,
                "ticker": strategy.ticker,
                "account_id": strategy.account_id,
                "quantity": strategy.quantity,
                "is_active": strategy.is_active,
                "created_at": strategy.created_at.isoformat() if strategy.created_at else None,
                "last_triggered": strategy.last_triggered.isoformat() if strategy.last_triggered else None,
                
                # Performance metrics
                "total_trades": strategy.total_trades or 0,
                "successful_trades": strategy.successful_trades or 0,
                "failed_trades": strategy.failed_trades or 0,
                "total_pnl": float(strategy.total_pnl) if strategy.total_pnl else 0.0,
                "win_rate": float(strategy.win_rate) if strategy.win_rate else 0.0,
                
                # Group/Leader info
                "leader_account_id": strategy.leader_account_id,
                "leader_quantity": strategy.leader_quantity,
                "group_name": strategy.group_name,
                
                # Broker account info
                "broker_account": {
                    "account_id": strategy.broker_account.account_id,
                    "name": strategy.broker_account.name,
                    "broker_id": strategy.broker_account.broker_id
                } if strategy.broker_account else None,
                
                # Default values
                "name": "Unknown Strategy",
                "description": "Strategy details unavailable",
                "category": "Unknown"
            }
            
            # Enrich with webhook data if it's a webhook strategy
            if strategy.webhook_id and strategy.execution_type == "webhook":
                try:
                    # Parse webhook_id for database lookup
                    webhook_id = int(strategy.webhook_id) if isinstance(strategy.webhook_id, str) else strategy.webhook_id
                    webhook = db.query(Webhook).filter(Webhook.id == webhook_id).first()
                    
                    if webhook:
                        strategy_data.update({
                            "name": webhook.name,
                            "description": webhook.details or f"{webhook.name} trading strategy",
                            "category": "TradingView Webhook",
                            "source_type": webhook.source_type,
                            "webhook_token": webhook.token,
                            "creator_id": webhook.user_id,
                            "subscriber_count": webhook.subscriber_count or 0
                        })
                    else:
                        logger.warning(f"Webhook {webhook_id} not found for activated strategy {strategy.id}")
                        strategy_data["name"] = f"Webhook Strategy (ID: {webhook_id})"
                        
                except (ValueError, TypeError) as e:
                    logger.error(f"Invalid webhook_id '{strategy.webhook_id}' for strategy {strategy.id}: {e}")
                    strategy_data["name"] = f"Invalid Webhook ({strategy.webhook_id})"
            
            # Enrich with strategy code data if it's an engine strategy
            elif strategy.strategy_code_id and strategy.execution_type == "engine":
                # Use the preloaded relationship instead of making another query
                strategy_code = strategy.strategy_code

                if strategy_code:
                    strategy_data.update({
                        "name": strategy_code.name,
                        "description": strategy_code.description or f"{strategy_code.name} algorithmic trading strategy",
                        "category": "Strategy Engine", 
                        "source_type": "algorithm",
                        "symbols": strategy_code.symbols_list if hasattr(strategy_code, 'symbols_list') else [],
                        "is_validated": strategy_code.is_validated,
                        "signals_generated": strategy_code.signals_generated if hasattr(strategy_code, 'signals_generated') else 0,
                        "creator_id": strategy_code.user_id
                    })
                else:
                    logger.warning(f"Strategy code {strategy.strategy_code_id} not found for activated strategy {strategy.id}")
                    strategy_data["name"] = f"Strategy Engine (ID: {strategy.strategy_code_id})"
            
            # Handle follower accounts for group strategies
            if strategy.strategy_type == "multiple":
                try:
                    follower_accounts = strategy.get_follower_accounts() if hasattr(strategy, 'get_follower_accounts') else []
                    strategy_data["follower_accounts"] = follower_accounts
                    strategy_data["leader_broker_account"] = {
                        "account_id": strategy.leader_broker_account.account_id,
                        "name": strategy.leader_broker_account.name,
                        "broker_id": strategy.leader_broker_account.broker_id
                    } if strategy.leader_broker_account else None
                except Exception as e:
                    logger.error(f"Error getting follower accounts for strategy {strategy.id}: {e}")
                    strategy_data["follower_accounts"] = []
                    strategy_data["leader_broker_account"] = None
            
            user_strategies.append(strategy_data)
        
        # Sort by most recently triggered/created
        user_strategies.sort(
            key=lambda x: x.get("last_triggered") or x.get("created_at") or "", 
            reverse=True
        )
        
        logger.info(f"Returning {len(user_strategies)} activated strategies for user {current_user.id}")
        
        return {
            "strategies": user_strategies,
            "total": len(user_strategies),
            "user_id": current_user.id,
            "active_count": sum(1 for s in user_strategies if s.get("is_active", False))
        }
        
    except Exception as e:
        logger.error(f"Error getting user activated strategies: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch user activated strategies: {str(e)}"
        )


@router.post("/{strategy_id}/toggle")
@check_subscription
async def toggle_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    try:
        strategy = db.query(ActivatedStrategy).filter(
            ActivatedStrategy.id == strategy_id,
            ActivatedStrategy.user_id == current_user.id
        ).options(
            joinedload(ActivatedStrategy.webhook),
            joinedload(ActivatedStrategy.strategy_code)
        ).first()
        
        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")
        
        # Check if trying to activate and if at limit
        if not strategy.is_active:
            # Determine if owned or subscribed
            is_owned = False
            if strategy.execution_type == 'webhook' and strategy.webhook:
                if strategy.webhook.user_id == current_user.id:
                    is_owned = True
            elif strategy.execution_type == 'engine' and strategy.strategy_code:
                if strategy.strategy_code.user_id == current_user.id:
                    is_owned = True
            
            limit_type = "active_strategies_owned" if is_owned else "active_strategies_subscribed"

            # Only check limits when activating (not when deactivating)
            subscription_service = SubscriptionService(db)
            can_add, message = subscription_service.can_add_resource(
                current_user.id, 
                limit_type
            )
            
            if not can_add and not settings.SKIP_SUBSCRIPTION_CHECK:
                raise HTTPException(status_code=403, detail=message)
        
        # Toggle the active status
        old_status = strategy.is_active
        strategy.is_active = not strategy.is_active

        # Handle manual override for scheduled strategies
        if strategy.market_schedule:
            await override_scheduled_state(strategy_id, strategy.is_active, db)
            logger.info(f"Manual override applied to scheduled strategy {strategy_id}")

        # Update subscription counter
        subscription = db.query(Subscription).filter(
            Subscription.user_id == current_user.id
        ).first()

        if subscription:
            if strategy.is_active and not old_status:  # Being activated
                subscription.active_strategies_count = (subscription.active_strategies_count or 0) + 1
            elif not strategy.is_active and old_status:  # Being deactivated
                if subscription.active_strategies_count > 0:
                    subscription.active_strategies_count -= 1

        db.commit()
        db.refresh(strategy)
        
        # Return the complete strategy object
        return strategy
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error toggling strategy: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to toggle strategy: {str(e)}"
        )

@router.put("/{strategy_id}", response_model=StrategyResponse)
@check_subscription
async def update_strategy(
    strategy_id: int,
    strategy_update: StrategyUpdate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Update an existing strategy"""
    try:
        logger.info(f"Updating strategy {strategy_id} for user {current_user.id}")
        
        # Get the strategy with joins for response
        strategy = (
            db.query(ActivatedStrategy)
            .options(
                joinedload(ActivatedStrategy.broker_account),
                joinedload(ActivatedStrategy.leader_broker_account),
                joinedload(ActivatedStrategy.webhook)
            )
            .filter(
                ActivatedStrategy.id == strategy_id,
                ActivatedStrategy.user_id == current_user.id
            )
            .first()
        )
        
        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")
        
        # Track if any changes were made
        changes_made = False
        
        # Update fields if provided
        if strategy_update.is_active is not None:
            # Check limits if trying to activate a currently inactive strategy
            if strategy_update.is_active and not strategy.is_active:
                subscription_service = SubscriptionService(db)
                can_add, message = subscription_service.can_add_resource(
                    current_user.id, 
                    "active_strategies"
                )
                
                if not can_add and not settings.SKIP_SUBSCRIPTION_CHECK:
                    raise HTTPException(status_code=403, detail=message)
            
            # Track old status for counter updates
            old_status = strategy.is_active
            strategy.is_active = strategy_update.is_active
            changes_made = True
            logger.info(f"Updated is_active to {strategy_update.is_active}")
            
            # Update subscription counter
            subscription = db.query(Subscription).filter(
                Subscription.user_id == current_user.id
            ).first()
            
            if subscription:
                if strategy.is_active and not old_status:  # Being activated
                    subscription.active_strategies_count = (subscription.active_strategies_count or 0) + 1
                elif not strategy.is_active and old_status:  # Being deactivated
                    if subscription.active_strategies_count > 0:
                        subscription.active_strategies_count -= 1
        
        if strategy.strategy_type == "single":
            # Handle single strategy updates
            if strategy_update.quantity is not None:
                strategy.quantity = strategy_update.quantity
                changes_made = True
                logger.info(f"Updated quantity to {strategy_update.quantity}")
                
            # Log warning if trying to update multi-account fields on single strategy
            if strategy_update.leader_quantity is not None:
                logger.warning(f"Ignoring leader_quantity update on single strategy")
            if strategy_update.follower_quantities is not None:
                logger.warning(f"Ignoring follower_quantities update on single strategy")
                
        elif strategy.strategy_type == "multiple":
            # Handle multiple strategy updates
            if strategy_update.leader_quantity is not None:
                strategy.leader_quantity = strategy_update.leader_quantity
                changes_made = True
                logger.info(f"Updated leader_quantity to {strategy_update.leader_quantity}")
            
            if strategy_update.follower_quantities is not None:
                # Get current follower accounts
                current_followers = strategy.get_follower_accounts()
                
                if len(strategy_update.follower_quantities) != len(current_followers):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Number of quantities ({len(strategy_update.follower_quantities)}) must match number of follower accounts ({len(current_followers)})"
                    )
                
                # Delete existing follower quantities
                db.execute(
                    strategy_follower_quantities.delete().where(
                        strategy_follower_quantities.c.strategy_id == strategy_id
                    )
                )
                
                # Insert new quantities
                for idx, follower in enumerate(current_followers):
                    db.execute(
                        strategy_follower_quantities.insert().values(
                            strategy_id=strategy_id,
                            account_id=follower["account_id"],
                            quantity=strategy_update.follower_quantities[idx]
                        )
                    )
                changes_made = True
                logger.info(f"Updated follower quantities: {strategy_update.follower_quantities}")
            
            # Log warning if trying to update single-account fields on multi strategy
            if strategy_update.quantity is not None:
                logger.warning(f"Ignoring quantity update on multiple strategy")
        
        if not changes_made:
            raise HTTPException(
                status_code=400,
                detail="No valid fields provided for update"
            )
        
        # Update the updated_at timestamp
        from datetime import datetime
        strategy.updated_at = datetime.utcnow()
        
        # Commit changes
        db.commit()
        db.refresh(strategy)
        
        logger.info(f"Successfully updated strategy {strategy_id}")
        
        # Prepare response data similar to list_strategies
        strategy_data = {
            "id": strategy.id,
            "strategy_type": strategy.strategy_type,
            "webhook_id": strategy.webhook_id,
            "ticker": strategy.ticker,
            "is_active": strategy.is_active,
            "created_at": strategy.created_at,
            "last_triggered": strategy.last_triggered,
            "webhook": {
                "name": strategy.webhook.name if strategy.webhook else None,
                "source_type": strategy.webhook.source_type if strategy.webhook else "custom"
            }
        }

        if strategy.strategy_type == "single":
            strategy_data.update({
                "account_id": strategy.account_id,
                "quantity": strategy.quantity,
                "broker_account": {
                    "account_id": strategy.broker_account.account_id,
                    "name": strategy.broker_account.name,
                    "broker_id": strategy.broker_account.broker_id
                } if strategy.broker_account else None,
                "leader_account_id": None,
                "leader_quantity": None,
                "leader_broker_account": None,
                "follower_accounts": [],
                "group_name": None
            })
        else:
            strategy_data.update({
                "group_name": strategy.group_name,
                "leader_account_id": strategy.leader_account_id,
                "leader_quantity": strategy.leader_quantity,
                "leader_broker_account": {
                    "account_id": strategy.leader_broker_account.account_id,
                    "name": strategy.leader_broker_account.name,
                    "broker_id": strategy.leader_broker_account.broker_id
                } if strategy.leader_broker_account else None,
                "follower_accounts": strategy.get_follower_accounts(),
                "account_id": None,
                "quantity": None
            })

        # Add stats
        strategy_data["stats"] = {
            "total_trades": strategy.total_trades,
            "successful_trades": strategy.successful_trades,
            "failed_trades": strategy.failed_trades,
            "total_pnl": float(strategy.total_pnl) if strategy.total_pnl else 0,
            "win_rate": float(strategy.win_rate) if strategy.win_rate else None,
            "average_trade_pnl": None
        }

        return StrategyResponse(**strategy_data)
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating strategy {strategy_id}: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update strategy: {str(e)}"
        )

@router.delete("/{strategy_id}")
@check_subscription
async def delete_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Delete a strategy"""
    try:
        # Get the strategy
        strategy = (
            db.query(ActivatedStrategy)
            .filter(
                ActivatedStrategy.id == strategy_id,
                ActivatedStrategy.user_id == current_user.id
            )
            .first()
        )
        
        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")
        
        # Get subscription before deleting
        subscription = db.query(Subscription).filter(
            Subscription.user_id == current_user.id
        ).first()
        
        # Delete strategy
        db.delete(strategy)
        
        # Update counter
        if subscription and subscription.active_strategies_count > 0:
            subscription.active_strategies_count -= 1
            
        db.commit()
        
        return {"status": "success", "message": "Strategy deleted successfully"}
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting strategy: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete strategy: {str(e)}"
        )


# Strategy Engine Endpoints

@router.post("/engine/configure", response_model=EngineStrategyResponse)
@check_subscription
@check_resource_limit("active_strategies")
async def configure_engine_strategy(
    *,
    db: Session = Depends(get_db),
    strategy: EngineStrategyCreate,
    current_user = Depends(get_current_user),
    response: Response = None
):
    """
    Configure a Strategy Engine strategy for automated execution.
    Links a StrategyCode to broker accounts with trading parameters.
    """
    try:
        logger.info(f"Configuring Engine strategy for user {current_user.id}")
        
        # Validate strategy code exists and user has access (owner or subscriber)
        strategy_code = db.query(StrategyCode).filter(
            StrategyCode.id == strategy.strategy_code_id
        ).first()
        
        if not strategy_code:
            raise HTTPException(
                status_code=404,
                detail="Strategy code not found"
            )
        
        # Check if user is owner OR subscriber
        is_owner = strategy_code.user_id == current_user.id
        
        subscription = None
        if not is_owner:
            # Check if user has subscription to this strategy
            subscription = db.query(WebhookSubscription).filter(
                WebhookSubscription.user_id == current_user.id,
                WebhookSubscription.strategy_type == 'engine',
                WebhookSubscription.strategy_code_id == strategy.strategy_code_id
            ).first()
            
            if not subscription:
                raise HTTPException(
                    status_code=403,
                    detail="Access denied - you must own or be subscribed to this strategy"
                )
        
        if not strategy_code.is_validated:
            raise HTTPException(
                status_code=400,
                detail="Strategy code must be validated before activation"
            )
        
        # Validate ticker format
        valid, _ = validate_ticker(strategy.ticker)
        if not valid:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid ticker format: {strategy.ticker}"
            )
        
        display_ticker = get_display_ticker(strategy.ticker)
        
        # Check for existing active strategy for same code + ticker
        existing_strategy = db.query(ActivatedStrategy).filter(
            ActivatedStrategy.strategy_code_id == strategy.strategy_code_id,
            ActivatedStrategy.ticker == display_ticker,
            ActivatedStrategy.user_id == current_user.id,
            ActivatedStrategy.is_active == True
        ).first()
        
        if existing_strategy:
            raise HTTPException(
                status_code=400,
                detail=f"Strategy '{strategy_code.name}' is already active for {display_ticker}"
            )
        
        # Validate broker accounts based on strategy type
        if strategy.strategy_type == StrategyType.SINGLE:
            if not strategy.account_id or not strategy.quantity:
                raise HTTPException(
                    status_code=400,
                    detail="Single strategy requires account_id and quantity"
                )
            
            # Validate broker account
            broker_account = db.query(BrokerAccount).filter(
                BrokerAccount.account_id == strategy.account_id,
                BrokerAccount.user_id == current_user.id,
                BrokerAccount.is_active == True
            ).first()
            
            if not broker_account:
                raise HTTPException(
                    status_code=404,
                    detail=f"Broker account {strategy.account_id} not found or inactive"
                )
        
        elif strategy.strategy_type == StrategyType.MULTIPLE:
            if not strategy.leader_account_id or not strategy.leader_quantity:
                raise HTTPException(
                    status_code=400,
                    detail="Multiple strategy requires leader_account_id and leader_quantity"
                )
            
            # Validate leader account
            leader_account = db.query(BrokerAccount).filter(
                BrokerAccount.account_id == strategy.leader_account_id,
                BrokerAccount.user_id == current_user.id,
                BrokerAccount.is_active == True
            ).first()
            
            if not leader_account:
                raise HTTPException(
                    status_code=404,
                    detail=f"Leader account {strategy.leader_account_id} not found or inactive"
                )
        
        # Create engine settings JSON
        engine_settings = {
            "enable_paper_trading": strategy.enable_paper_trading,
            "enable_live_trading": strategy.enable_live_trading,
            "max_signals_per_day": strategy.max_signals_per_day,
        }
        
        # Create new ActivatedStrategy for Strategy Engine
        new_strategy = ActivatedStrategy(
            user_id=current_user.id,
            strategy_type=strategy.strategy_type.value,
            execution_type='engine',  # Key difference from webhook strategies
            webhook_id=None,  # Explicitly None for engine strategies
            strategy_code_id=strategy.strategy_code_id,
            ticker=display_ticker,
            
            # Single strategy fields
            account_id=strategy.account_id,
            quantity=strategy.quantity,
            
            # Multiple strategy fields
            leader_account_id=strategy.leader_account_id,
            leader_quantity=strategy.leader_quantity,
            group_name=strategy.group_name,
            
            # Risk management
            max_position_size=strategy.max_position_size,
            stop_loss_percent=strategy.stop_loss_percent,
            take_profit_percent=strategy.take_profit_percent,
            max_daily_loss=strategy.max_daily_loss,
            
            # Engine settings
            engine_settings=json.dumps(engine_settings),
            
            # Status
            is_active=True,
            description=f"Strategy Engine: {strategy_code.name}",
            notes=f"Automated strategy: {strategy_code.name}",
        )
        
        db.add(new_strategy)
        
        # Update subscription counter
        subscription = db.query(Subscription).filter(
            Subscription.user_id == current_user.id
        ).first()
        
        if subscription:
            subscription.active_strategies_count = (subscription.active_strategies_count or 0) + 1
        
        db.commit()
        db.refresh(new_strategy)
        
        # Build response
        return EngineStrategyResponse(
            id=new_strategy.id,
            strategy_type=StrategyType(new_strategy.strategy_type),
            execution_type=ExecutionType(new_strategy.execution_type),
            strategy_code_id=new_strategy.strategy_code_id,
            ticker=new_strategy.ticker,
            is_active=new_strategy.is_active,
            created_at=new_strategy.created_at,
            last_triggered=new_strategy.last_triggered,
            strategy_code={
                "id": strategy_code.id,
                "name": strategy_code.name,
                "description": strategy_code.description,
                "symbols": strategy_code.symbols_list
            },
            account_id=new_strategy.account_id,
            quantity=new_strategy.quantity,
            leader_account_id=new_strategy.leader_account_id,
            leader_quantity=new_strategy.leader_quantity,
            group_name=new_strategy.group_name,
            max_position_size=new_strategy.max_position_size,
            stop_loss_percent=float(new_strategy.stop_loss_percent) if new_strategy.stop_loss_percent else None,
            take_profit_percent=float(new_strategy.take_profit_percent) if new_strategy.take_profit_percent else None,
            max_daily_loss=float(new_strategy.max_daily_loss) if new_strategy.max_daily_loss else None,
            engine_settings=new_strategy.get_engine_settings(),
            stats=StrategyStats(
                total_trades=new_strategy.total_trades or 0,
                successful_trades=new_strategy.successful_trades or 0,
                failed_trades=new_strategy.failed_trades or 0,
                total_pnl=new_strategy.total_pnl or Decimal('0'),
                win_rate=float(new_strategy.win_rate) if new_strategy.win_rate else None,
                max_drawdown=new_strategy.max_drawdown,
                sharpe_ratio=float(new_strategy.sharpe_ratio) if new_strategy.sharpe_ratio else None,
                average_win=new_strategy.average_win,
                average_loss=new_strategy.average_loss
            )
        )
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error configuring Engine strategy: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to configure strategy: {str(e)}"
        )


@router.get("/engine/list", response_model=List[EngineStrategyResponse])
@check_subscription
async def list_engine_strategies(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
    active_only: bool = Query(True, description="Show only active strategies")
):
    """List all Strategy Engine configurations for the current user."""
    try:
        query = db.query(ActivatedStrategy).filter(
            ActivatedStrategy.user_id == current_user.id,
            ActivatedStrategy.execution_type == 'engine'
        ).options(joinedload(ActivatedStrategy.strategy_code))
        
        if active_only:
            query = query.filter(ActivatedStrategy.is_active == True)
        
        strategies = query.order_by(ActivatedStrategy.created_at.desc()).all()
        
        # Build response list
        response = []
        for strategy in strategies:
            strategy_code = strategy.strategy_code
            
            response.append(EngineStrategyResponse(
                id=strategy.id,
                strategy_type=StrategyType(strategy.strategy_type),
                execution_type=ExecutionType(strategy.execution_type),
                strategy_code_id=strategy.strategy_code_id,
                ticker=strategy.ticker,
                is_active=strategy.is_active,
                created_at=strategy.created_at,
                last_triggered=strategy.last_triggered,
                strategy_code={
                    "id": strategy_code.id,
                    "name": strategy_code.name,
                    "description": strategy_code.description,
                    "symbols": strategy_code.symbols_list
                } if strategy_code else None,
                account_id=strategy.account_id,
                quantity=strategy.quantity,
                leader_account_id=strategy.leader_account_id,
                leader_quantity=strategy.leader_quantity,
                group_name=strategy.group_name,
                max_position_size=strategy.max_position_size,
                stop_loss_percent=float(strategy.stop_loss_percent) if strategy.stop_loss_percent else None,
                take_profit_percent=float(strategy.take_profit_percent) if strategy.take_profit_percent else None,
                max_daily_loss=float(strategy.max_daily_loss) if strategy.max_daily_loss else None,
                engine_settings=strategy.get_engine_settings(),
                stats=StrategyStats(
                    total_trades=strategy.total_trades or 0,
                    successful_trades=strategy.successful_trades or 0,
                    failed_trades=strategy.failed_trades or 0,
                    total_pnl=strategy.total_pnl or Decimal('0'),
                    win_rate=float(strategy.win_rate) if strategy.win_rate else None,
                    max_drawdown=strategy.max_drawdown,
                    sharpe_ratio=float(strategy.sharpe_ratio) if strategy.sharpe_ratio else None,
                    average_win=strategy.average_win,
                    average_loss=strategy.average_loss
                )
            ))
        
        return response
        
    except Exception as e:
        logger.error(f"Error listing Engine strategies: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list strategies: {str(e)}"
        )


@router.put("/engine/{strategy_id}", response_model=EngineStrategyResponse)
@check_subscription
async def update_engine_strategy(
    strategy_id: int,
    strategy_update: EngineStrategyUpdate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Update a Strategy Engine configuration."""
    try:
        strategy = db.query(ActivatedStrategy).filter(
            ActivatedStrategy.id == strategy_id,
            ActivatedStrategy.user_id == current_user.id,
            ActivatedStrategy.execution_type == 'engine'
        ).options(joinedload(ActivatedStrategy.strategy_code)).first()
        
        if not strategy:
            raise HTTPException(
                status_code=404,
                detail="Engine strategy not found"
            )
        
        # Update fields
        if strategy_update.is_active is not None:
            strategy.is_active = strategy_update.is_active
        
        if strategy_update.quantity is not None:
            strategy.quantity = strategy_update.quantity
            
        if strategy_update.leader_quantity is not None:
            strategy.leader_quantity = strategy_update.leader_quantity
        
        # Update risk management
        if strategy_update.stop_loss_percent is not None:
            strategy.stop_loss_percent = Decimal(str(strategy_update.stop_loss_percent))
            
        if strategy_update.take_profit_percent is not None:
            strategy.take_profit_percent = Decimal(str(strategy_update.take_profit_percent))
            
        if strategy_update.max_daily_loss is not None:
            strategy.max_daily_loss = Decimal(str(strategy_update.max_daily_loss))
        
        # Update engine settings
        engine_settings = strategy.get_engine_settings()
        
        if strategy_update.enable_paper_trading is not None:
            engine_settings['enable_paper_trading'] = strategy_update.enable_paper_trading
            
        if strategy_update.enable_live_trading is not None:
            engine_settings['enable_live_trading'] = strategy_update.enable_live_trading
            
        if strategy_update.max_signals_per_day is not None:
            engine_settings['max_signals_per_day'] = strategy_update.max_signals_per_day
        
        strategy.set_engine_settings(engine_settings)
        strategy.updated_at = datetime.utcnow()
        
        db.commit()
        db.refresh(strategy)
        
        # Build response (reuse logic from list endpoint)
        strategy_code = strategy.strategy_code
        
        return EngineStrategyResponse(
            id=strategy.id,
            strategy_type=StrategyType(strategy.strategy_type),
            execution_type=ExecutionType(strategy.execution_type),
            strategy_code_id=strategy.strategy_code_id,
            ticker=strategy.ticker,
            is_active=strategy.is_active,
            created_at=strategy.created_at,
            last_triggered=strategy.last_triggered,
            strategy_code={
                "id": strategy_code.id,
                "name": strategy_code.name,
                "description": strategy_code.description,
                "symbols": strategy_code.symbols_list
            } if strategy_code else None,
            account_id=strategy.account_id,
            quantity=strategy.quantity,
            leader_account_id=strategy.leader_account_id,
            leader_quantity=strategy.leader_quantity,
            group_name=strategy.group_name,
            max_position_size=strategy.max_position_size,
            stop_loss_percent=float(strategy.stop_loss_percent) if strategy.stop_loss_percent else None,
            take_profit_percent=float(strategy.take_profit_percent) if strategy.take_profit_percent else None,
            max_daily_loss=float(strategy.max_daily_loss) if strategy.max_daily_loss else None,
            engine_settings=strategy.get_engine_settings(),
            stats=StrategyStats(
                total_trades=strategy.total_trades or 0,
                successful_trades=strategy.successful_trades or 0,
                failed_trades=strategy.failed_trades or 0,
                total_pnl=strategy.total_pnl or Decimal('0'),
                win_rate=float(strategy.win_rate) if strategy.win_rate else None,
                max_drawdown=strategy.max_drawdown,
                sharpe_ratio=float(strategy.sharpe_ratio) if strategy.sharpe_ratio else None,
                average_win=strategy.average_win,
                average_loss=strategy.average_loss
            )
        )
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating Engine strategy: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update strategy: {str(e)}"
        )


@router.delete("/engine/{strategy_id}")
@check_subscription
async def delete_engine_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Delete a Strategy Engine configuration."""
    try:
        strategy = db.query(ActivatedStrategy).filter(
            ActivatedStrategy.id == strategy_id,
            ActivatedStrategy.user_id == current_user.id,
            ActivatedStrategy.execution_type == 'engine'
        ).first()
        
        if not strategy:
            raise HTTPException(
                status_code=404,
                detail="Engine strategy not found"
            )
        
        # Update subscription counter
        subscription = db.query(Subscription).filter(
            Subscription.user_id == current_user.id
        ).first()
        
        if subscription and subscription.active_strategies_count:
            subscription.active_strategies_count -= 1
        
        db.delete(strategy)
        db.commit()
        
        return {"status": "success", "message": "Engine strategy deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting Engine strategy: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete strategy: {str(e)}"
        )


# ==================== STRATEGY SCHEDULING ENDPOINTS ====================

@router.get("/{strategy_id}/schedule")
async def get_strategy_schedule(
    strategy_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Get schedule information for a strategy"""
    strategy = db.query(ActivatedStrategy).filter(
        ActivatedStrategy.id == strategy_id,
        ActivatedStrategy.user_id == current_user.id
    ).first()

    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    if not strategy.market_schedule:
        return {
            "scheduled": False,
            "market": None
        }

    market_info = get_market_info(strategy.market_schedule)
    next_event = get_next_market_event(strategy.market_schedule)

    return {
        "scheduled": True,
        "market": strategy.market_schedule,
        "market_info": market_info,
        "next_event": next_event,
        "last_scheduled_toggle": strategy.last_scheduled_toggle,
        "manual_override": strategy.schedule_active_state is None
    }


@router.put("/{strategy_id}/schedule")
async def update_strategy_schedule(
    strategy_id: int,
    schedule_data: dict,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Update schedule settings for a strategy"""
    strategy = db.query(ActivatedStrategy).filter(
        ActivatedStrategy.id == strategy_id,
        ActivatedStrategy.user_id == current_user.id
    ).first()

    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    market_schedule = schedule_data.get('market_schedule')

    # Validate market schedule
    valid_markets = ['NYSE', 'LONDON', 'ASIA', '24/7', None]
    if market_schedule not in valid_markets:
        raise HTTPException(status_code=400, detail="Invalid market schedule")

    strategy.market_schedule = market_schedule

    # Reset schedule state when schedule changes
    if market_schedule and market_schedule != '24/7':
        strategy.schedule_active_state = is_market_open(market_schedule)
    else:
        strategy.schedule_active_state = None

    db.commit()
    db.refresh(strategy)

    logger.info(f"Strategy {strategy_id} schedule updated to {market_schedule}")

    return {
        "message": "Schedule updated successfully",
        "market_schedule": market_schedule,
        "schedule_active_state": strategy.schedule_active_state
    }


@router.delete("/{strategy_id}/schedule")
async def remove_strategy_schedule(
    strategy_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Remove scheduling from a strategy (make it always-on)"""
    strategy = db.query(ActivatedStrategy).filter(
        ActivatedStrategy.id == strategy_id,
        ActivatedStrategy.user_id == current_user.id
    ).first()

    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    strategy.market_schedule = None
    strategy.schedule_active_state = None
    strategy.last_scheduled_toggle = None

    db.commit()

    logger.info(f"Strategy {strategy_id} schedule removed, now always-on")

    return {
        "message": "Schedule removed successfully",
        "market_schedule": None
    }