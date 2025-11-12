"""
Unified strategy endpoints that handle both webhook and engine strategies.
This replaces the separate /strategies and /strategies/engine endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException, Response, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.exc import SQLAlchemyError
from typing import List, Optional, Dict, Any, Union
import logging
from datetime import datetime

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.strategy import ActivatedStrategy, strategy_follower_quantities
from app.models.webhook import Webhook, WebhookSubscription
from app.models.strategy_code import StrategyCode
from app.models.strategy_purchase import StrategyPurchase
from app.models.broker import BrokerAccount
from app.models.subscription import Subscription
from app.schemas.strategy_unified import (
    UnifiedStrategyCreate,
    UnifiedStrategyUpdate,
    UnifiedStrategyResponse,
    StrategyValidationRequest,
    StrategyValidationResponse,
    StrategyToggleResponse,
    StrategyListFilters,
    StrategyBatchOperation,
    StrategyType,
    ExecutionType,
    FollowerAccount
)
# Import legacy schemas for backward compatibility
from app.schemas.strategy import (
    SingleStrategyCreate,
    MultipleStrategyCreate,
    EngineStrategyCreate,
    EngineStrategyUpdate
)
from app.services.subscription_service import SubscriptionService
from app.core.permissions import check_subscription, check_resource_limit
from app.utils.ticker_utils import get_display_ticker, validate_ticker

router = APIRouter(tags=["unified-strategies"])
logger = logging.getLogger(__name__)


@router.get("/all")  # NEW WORKING ENDPOINT AT /api/v1/strategies/all
async def list_all_strategies(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Working endpoint at /strategies/all instead of broken root path.
    TODO: Remove this once root path "/" is fixed - see Phase 2.1
    """
    try:
        from app.models.strategy import ActivatedStrategy
        strategies = db.query(ActivatedStrategy).filter(
            ActivatedStrategy.user_id == current_user.id
        ).all()

        logger.info(f"Found {len(strategies)} strategies for user {current_user.id}")

        # Return simple list that frontend can use
        return [
            {
                "id": s.id,
                "ticker": s.ticker,
                "strategy_type": s.strategy_type.value if s.strategy_type else None,
                "execution_type": s.execution_type.value if s.execution_type else None,
                "is_active": s.is_active,
                "quantity": s.quantity,
                "account_id": s.account_id,
                "webhook_id": s.webhook_id,
                "strategy_code_id": s.strategy_code_id,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "updated_at": s.updated_at.isoformat() if s.updated_at else None
            }
            for s in strategies
        ]
    except Exception as e:
        logger.error(f"Error in /all endpoint: {str(e)}", exc_info=True)
        return {"error": str(e)}


# Helper Functions
def validate_webhook_access(webhook_id: str, user, db: Session) -> bool:
    """Check if user has access to webhook"""
    webhook = db.query(Webhook).filter(Webhook.token == webhook_id).first()
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")

    # Check access: owner, subscriber, or purchased
    is_owner = webhook.user_id == user.id

    is_subscriber = db.query(WebhookSubscription).filter(
        WebhookSubscription.webhook_id == webhook.id,
        WebhookSubscription.user_id == user.id
    ).first() is not None

    has_purchase = db.query(StrategyPurchase).filter(
        StrategyPurchase.webhook_id == webhook.id,
        StrategyPurchase.user_id == user.id,
        StrategyPurchase.status == "COMPLETED"
    ).first() is not None

    if not (is_owner or is_subscriber or has_purchase):
        raise HTTPException(status_code=403, detail="No access to this webhook")

    return True


def validate_strategy_code_access(strategy_code_id: int, user, db: Session) -> bool:
    """Check if user has access to strategy code"""
    strategy_code = db.query(StrategyCode).filter(
        StrategyCode.id == strategy_code_id,
        StrategyCode.is_active == True,
        StrategyCode.is_validated == True
    ).first()

    if not strategy_code:
        raise HTTPException(status_code=404, detail="Strategy code not found or not available")

    # Check access: owner or subscriber
    is_owner = strategy_code.user_id == user.id

    is_subscriber = db.query(WebhookSubscription).filter(
        WebhookSubscription.strategy_code_id == strategy_code_id,
        WebhookSubscription.user_id == user.id,
        WebhookSubscription.strategy_type == 'engine'
    ).first() is not None

    if not (is_owner or is_subscriber):
        raise HTTPException(status_code=403, detail="No access to this strategy code")

    return True


def validate_account_ownership(account_id: str, user, db: Session) -> bool:
    """Check if user owns the broker account"""
    account = db.query(BrokerAccount).filter(
        BrokerAccount.account_id == account_id,
        BrokerAccount.user_id == user.id,
        BrokerAccount.is_active == True
    ).first()

    if not account:
        raise HTTPException(
            status_code=404,
            detail=f"Account {account_id} not found or inactive"
        )

    return True


def check_duplicate_strategy(strategy_data: UnifiedStrategyCreate, user_id: int, db: Session) -> bool:
    """Check if a strategy with the same parameters already exists"""
    query = db.query(ActivatedStrategy).filter(
        ActivatedStrategy.user_id == user_id,
        ActivatedStrategy.ticker == strategy_data.ticker
    )

    if strategy_data.execution_type == ExecutionType.WEBHOOK:
        query = query.filter(ActivatedStrategy.webhook_id == strategy_data.webhook_id)
    else:
        query = query.filter(ActivatedStrategy.strategy_code_id == strategy_data.strategy_code_id)

    if strategy_data.strategy_type == StrategyType.SINGLE:
        query = query.filter(ActivatedStrategy.account_id == strategy_data.account_id)
    else:
        query = query.filter(ActivatedStrategy.leader_account_id == strategy_data.leader_account_id)

    return query.first() is not None


def create_single_strategy(data: UnifiedStrategyCreate, user_id: int, db: Session) -> ActivatedStrategy:
    """Create a single account strategy"""
    strategy = ActivatedStrategy(
        user_id=user_id,
        strategy_type=data.strategy_type,
        execution_type=data.execution_type,
        webhook_id=data.webhook_id,
        strategy_code_id=data.strategy_code_id,
        ticker=data.ticker,
        account_id=data.account_id,
        quantity=data.quantity,
        is_active=data.is_active,
        description=data.description,
        market_schedule=data.market_schedule
    )

    db.add(strategy)
    return strategy


def create_multiple_strategy(data: UnifiedStrategyCreate, user_id: int, db: Session) -> ActivatedStrategy:
    """Create a multiple account strategy"""
    strategy = ActivatedStrategy(
        user_id=user_id,
        strategy_type=data.strategy_type,
        execution_type=data.execution_type,
        webhook_id=data.webhook_id,
        strategy_code_id=data.strategy_code_id,
        ticker=data.ticker,
        leader_account_id=data.leader_account_id,
        leader_quantity=data.leader_quantity,
        group_name=data.group_name,
        is_active=data.is_active,
        description=data.description,
        market_schedule=data.market_schedule
    )

    db.add(strategy)
    db.flush()  # Get the strategy ID

    # Add follower accounts
    for follower in data.follower_accounts:
        db.execute(
            strategy_follower_quantities.insert().values(
                strategy_id=strategy.id,
                account_id=follower.account_id,
                quantity=follower.quantity
            )
        )

    return strategy


def update_follower_quantities(strategy: ActivatedStrategy, quantities: List[int], db: Session):
    """Update follower quantities for a multiple strategy"""
    # Get current followers
    current_followers = strategy.get_follower_accounts()

    if len(quantities) != len(current_followers):
        raise HTTPException(
            status_code=400,
            detail=f"Number of quantities ({len(quantities)}) must match number of followers ({len(current_followers)})"
        )

    # Delete existing quantities
    db.execute(
        strategy_follower_quantities.delete().where(
            strategy_follower_quantities.c.strategy_id == strategy.id
        )
    )

    # Add new quantities
    for account_id, quantity in zip(current_followers, quantities):
        db.execute(
            strategy_follower_quantities.insert().values(
                strategy_id=strategy.id,
                account_id=account_id,
                quantity=quantity
            )
        )


def enrich_strategy_data(strategy: ActivatedStrategy, db: Session) -> dict:
    """
    Enrich strategy with webhook/strategy_code data to provide complete information.

    This function looks up the webhook or strategy_code associated with the strategy
    and adds enriched fields like name, description, category, and additional metadata.

    Ported from legacy strategy.py (lines 699-741) for unified endpoint compatibility.
    """
    # Base strategy data
    enriched = {
        "id": strategy.id,
        "user_id": strategy.user_id,
        "strategy_type": strategy.strategy_type,
        "execution_type": strategy.execution_type,
        "ticker": strategy.ticker,
        "account_id": strategy.account_id,
        "quantity": strategy.quantity,
        "is_active": strategy.is_active,
        "created_at": strategy.created_at.isoformat() if strategy.created_at else None,
        "updated_at": strategy.updated_at.isoformat() if strategy.updated_at else None,
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

        # Default values (will be overwritten by enrichment if available)
        "name": "Unknown Strategy",
        "description": "Strategy details unavailable",
        "category": "Unknown",

        # Schedule fields
        "market_schedule": strategy.market_schedule,
        "schedule_active_state": strategy.schedule_active_state,
        "last_scheduled_toggle": strategy.last_scheduled_toggle.isoformat() if strategy.last_scheduled_toggle else None,

        # Execution source IDs
        "webhook_id": strategy.webhook_id,
        "strategy_code_id": strategy.strategy_code_id,
    }

    # Enrich webhook strategies
    if strategy.execution_type == ExecutionType.WEBHOOK and strategy.webhook_id:
        try:
            # Look up webhook by token (webhook_id is actually the token string)
            webhook = db.query(Webhook).filter(Webhook.token == str(strategy.webhook_id)).first()

            if webhook:
                enriched.update({
                    "name": webhook.name,
                    "description": webhook.details or f"{webhook.name} trading strategy",
                    "category": "TradingView Webhook",
                    "source_type": webhook.source_type,
                    "webhook_token": webhook.token,
                    "creator_id": webhook.user_id,
                    "subscriber_count": webhook.subscriber_count or 0
                })
            else:
                logger.warning(f"Webhook token '{strategy.webhook_id}' not found for strategy {strategy.id}")
                enriched["name"] = f"Webhook Strategy (Token: {strategy.webhook_id[:8]}...)" if len(str(strategy.webhook_id)) > 8 else f"Webhook Strategy ({strategy.webhook_id})"
        except Exception as e:
            logger.error(f"Error looking up webhook for strategy {strategy.id}: {e}")
            enriched["name"] = "Unknown Webhook Strategy"

    # Enrich engine strategies
    elif strategy.execution_type == ExecutionType.ENGINE and strategy.strategy_code_id:
        try:
            # Use the preloaded relationship instead of making another query
            strategy_code = strategy.strategy_code

            if strategy_code:
                enriched.update({
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
                logger.warning(f"Strategy code {strategy.strategy_code_id} not found for strategy {strategy.id}")
                enriched["name"] = f"Strategy Engine (ID: {strategy.strategy_code_id})"
        except Exception as e:
            logger.error(f"Error looking up strategy code for strategy {strategy.id}: {e}")
            enriched["name"] = "Unknown Engine Strategy"

    # Add broker account info
    if strategy.broker_account:
        enriched["broker_account"] = {
            "account_id": strategy.broker_account.account_id,
            "name": strategy.broker_account.name,
            "broker_id": strategy.broker_account.broker_id
        }
    else:
        enriched["broker_account"] = None

    # Handle follower accounts for group strategies
    if strategy.strategy_type == StrategyType.MULTIPLE:
        try:
            follower_accounts = strategy.get_follower_accounts() if hasattr(strategy, 'get_follower_accounts') else []
            enriched["follower_accounts"] = follower_accounts

            if strategy.leader_broker_account:
                enriched["leader_broker_account"] = {
                    "account_id": strategy.leader_broker_account.account_id,
                    "name": strategy.leader_broker_account.name,
                    "broker_id": strategy.leader_broker_account.broker_id
                }
            else:
                enriched["leader_broker_account"] = None
        except Exception as e:
            logger.error(f"Error getting follower accounts for strategy {strategy.id}: {e}")
            enriched["follower_accounts"] = []
            enriched["leader_broker_account"] = None
    else:
        enriched["follower_accounts"] = []
        enriched["leader_broker_account"] = None

    return enriched


# API Endpoints

@router.post("/", response_model=UnifiedStrategyResponse)
@check_subscription
@check_resource_limit("active_strategies")
async def create_strategy(
    strategy_data: UnifiedStrategyCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Create a new trading strategy (webhook or engine).

    This unified endpoint replaces:
    - POST /strategies/activate (for webhook strategies)
    - POST /strategies/engine/configure (for engine strategies)
    """
    try:
        logger.info(f"Creating {strategy_data.execution_type} strategy for user {current_user.id}")

        # Validate ticker
        valid, error_msg = validate_ticker(strategy_data.ticker)
        if not valid:
            raise HTTPException(status_code=400, detail=f"Invalid ticker: {error_msg}")

        # Validate access to execution source
        if strategy_data.execution_type == ExecutionType.WEBHOOK:
            validate_webhook_access(strategy_data.webhook_id, current_user, db)
        else:
            validate_strategy_code_access(strategy_data.strategy_code_id, current_user, db)

        # Validate account ownership
        if strategy_data.strategy_type == StrategyType.SINGLE:
            validate_account_ownership(strategy_data.account_id, current_user, db)
        else:
            validate_account_ownership(strategy_data.leader_account_id, current_user, db)
            for follower in strategy_data.follower_accounts:
                validate_account_ownership(follower.account_id, current_user, db)

        # Check for duplicates
        if check_duplicate_strategy(strategy_data, current_user.id, db):
            raise HTTPException(
                status_code=400,
                detail="A strategy with these parameters already exists"
            )

        # Create strategy based on type
        if strategy_data.strategy_type == StrategyType.SINGLE:
            strategy = create_single_strategy(strategy_data, current_user.id, db)
        else:
            strategy = create_multiple_strategy(strategy_data, current_user.id, db)

        # Update subscription counters if active
        if strategy.is_active:
            subscription = db.query(Subscription).filter(
                Subscription.user_id == current_user.id
            ).first()
            if subscription:
                subscription.active_strategies_count = (subscription.active_strategies_count or 0) + 1

        db.commit()
        db.refresh(strategy)

        logger.info(f"Created strategy {strategy.id} successfully")
        return strategy

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating strategy: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/")
async def list_strategies(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    # MOVED Query params AFTER dependencies to test if order matters
    execution_type: Optional[str] = Query(None),  # Changed from ExecutionType enum to str
    strategy_type: Optional[str] = Query(None),   # Changed from StrategyType enum to str
    is_active: Optional[bool] = Query(None),
    ticker: Optional[str] = Query(None),
    account_id: Optional[str] = Query(None)
):
    """
    List all user strategies with optional filters.

    This unified endpoint replaces:
    - GET /strategies/list
    - GET /strategies/engine/list
    """
    # Log immediately when function is called
    import sys
    print("DEBUG: list_strategies function called!", file=sys.stderr, flush=True)
    logger.error("DEBUG: list_strategies function entered!")

    try:
        logger.error(f"DEBUG: User authenticated: {current_user.id if current_user else 'NO USER'}")
        logger.info(f"list_strategies called for user {current_user.id}")
        logger.info(f"Filters: execution_type={execution_type}, strategy_type={strategy_type}, is_active={is_active}, ticker={ticker}, account_id={account_id}")

        # TEMPORARY FIX: Remove joinedload to prevent hanging
        # The joinedload was causing the endpoint to hang silently
        query = db.query(ActivatedStrategy).filter(
            ActivatedStrategy.user_id == current_user.id
        )

        # Apply filters (convert strings back to enums if provided)
        if execution_type:
            try:
                exec_type_enum = ExecutionType(execution_type)
                query = query.filter(ActivatedStrategy.execution_type == exec_type_enum)
            except ValueError:
                logger.warning(f"Invalid execution_type: {execution_type}")
        if strategy_type:
            try:
                strat_type_enum = StrategyType(strategy_type)
                query = query.filter(ActivatedStrategy.strategy_type == strat_type_enum)
            except ValueError:
                logger.warning(f"Invalid strategy_type: {strategy_type}")
        if is_active is not None:
            query = query.filter(ActivatedStrategy.is_active == is_active)
        if ticker:
            query = query.filter(ActivatedStrategy.ticker == ticker)
        if account_id:
            query = query.filter(
                (ActivatedStrategy.account_id == account_id) |
                (ActivatedStrategy.leader_account_id == account_id)
            )

        strategies = query.all()

        logger.error(f"DEBUG: Query executed, found {len(strategies)} strategies")
        logger.info(f"Found {len(strategies)} strategies for user {current_user.id}")

        # Debug: Return simple dict to test if serialization is the issue
        if len(strategies) == 0:
            logger.error("DEBUG: No strategies found, returning empty list")
            return []

        # Add follower information for multiple strategies
        for strategy in strategies:
            if strategy.strategy_type == StrategyType.MULTIPLE:
                try:
                    strategy.follower_account_ids = strategy.get_follower_accounts()
                    strategy.follower_quantities = strategy.get_follower_quantities()
                except Exception as e:
                    logger.error(f"Error getting follower info for strategy {strategy.id}: {e}")
                    strategy.follower_account_ids = []
                    strategy.follower_quantities = []

        logger.info(f"Returning {len(strategies)} strategies for user {current_user.id}")

        # TEMPORARY: Return simple list to avoid serialization issues
        return [
            {
                "id": s.id,
                "ticker": s.ticker,
                "strategy_type": s.strategy_type.value if s.strategy_type else None,
                "execution_type": s.execution_type.value if s.execution_type else None,
                "is_active": s.is_active,
                "created_at": s.created_at.isoformat() if s.created_at else None
            }
            for s in strategies
        ]
    except Exception as e:
        logger.error(f"Error in list_strategies: {type(e).__name__}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to retrieve strategies: {str(e)}")


@router.get("/{strategy_id}", response_model=UnifiedStrategyResponse)
async def get_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """Get details of a specific strategy"""
    strategy = db.query(ActivatedStrategy).options(
        joinedload(ActivatedStrategy.broker_account),
        joinedload(ActivatedStrategy.leader_broker_account),
        joinedload(ActivatedStrategy.webhook),
        joinedload(ActivatedStrategy.strategy_code)
    ).filter(
        ActivatedStrategy.id == strategy_id,
        ActivatedStrategy.user_id == current_user.id
    ).first()

    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    # Add follower information for multiple strategies
    if strategy.strategy_type == StrategyType.MULTIPLE:
        strategy.follower_account_ids = strategy.get_follower_accounts()
        strategy.follower_quantities = strategy.get_follower_quantities()

    return strategy


@router.put("/{strategy_id}", response_model=UnifiedStrategyResponse)
@check_subscription
async def update_strategy(
    strategy_id: int,
    updates: UnifiedStrategyUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Update an existing strategy - NO DELETE+RECREATE!

    Only these fields can be updated:
    - quantity/leader_quantity
    - follower_quantities
    - is_active
    - market_schedule
    - description
    - group_name

    Core fields (ticker, execution_type, accounts, etc.) cannot be changed.
    To change core fields, delete and recreate the strategy.
    """
    try:
        logger.info(f"Updating strategy {strategy_id} for user {current_user.id}")

        strategy = db.query(ActivatedStrategy).filter(
            ActivatedStrategy.id == strategy_id,
            ActivatedStrategy.user_id == current_user.id
        ).first()

        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")

        # Track if activation status changes for subscription counter
        old_is_active = strategy.is_active

        # Apply updates
        update_data = updates.dict(exclude_unset=True)

        # Handle strategy type specific updates
        if strategy.strategy_type == StrategyType.SINGLE:
            # For single strategies, only quantity matters
            if 'leader_quantity' in update_data:
                del update_data['leader_quantity']
            if 'follower_quantities' in update_data:
                del update_data['follower_quantities']
            if 'group_name' in update_data:
                del update_data['group_name']
        else:
            # For multiple strategies, handle follower quantities separately
            if 'quantity' in update_data:
                del update_data['quantity']

            if 'follower_quantities' in update_data:
                update_follower_quantities(strategy, update_data['follower_quantities'], db)
                del update_data['follower_quantities']

        # Apply remaining updates
        for field, value in update_data.items():
            setattr(strategy, field, value)

        # Update timestamp
        strategy.updated_at = datetime.utcnow()

        # Update subscription counter if active status changed
        if 'is_active' in update_data and old_is_active != strategy.is_active:
            subscription = db.query(Subscription).filter(
                Subscription.user_id == current_user.id
            ).first()

            if subscription:
                if strategy.is_active and not old_is_active:
                    subscription.active_strategies_count = (subscription.active_strategies_count or 0) + 1
                elif not strategy.is_active and old_is_active:
                    if subscription.active_strategies_count > 0:
                        subscription.active_strategies_count -= 1

        db.commit()
        db.refresh(strategy)

        # Add follower information for response
        if strategy.strategy_type == StrategyType.MULTIPLE:
            strategy.follower_account_ids = strategy.get_follower_accounts()
            strategy.follower_quantities = strategy.get_follower_quantities()

        logger.info(f"Updated strategy {strategy_id} successfully")
        return strategy

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating strategy: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{strategy_id}")
async def delete_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Delete a strategy.

    This unified endpoint replaces:
    - DELETE /strategies/{id}
    - DELETE /strategies/engine/{id}
    """
    try:
        strategy = db.query(ActivatedStrategy).filter(
            ActivatedStrategy.id == strategy_id,
            ActivatedStrategy.user_id == current_user.id
        ).first()

        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")

        # Update subscription counter if was active
        if strategy.is_active:
            subscription = db.query(Subscription).filter(
                Subscription.user_id == current_user.id
            ).first()
            if subscription and subscription.active_strategies_count > 0:
                subscription.active_strategies_count -= 1

        db.delete(strategy)
        db.commit()

        logger.info(f"Deleted strategy {strategy_id} successfully")
        return {"message": "Strategy deleted successfully", "id": strategy_id}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting strategy: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{strategy_id}/toggle", response_model=StrategyToggleResponse)
@check_subscription
async def toggle_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """Toggle a strategy's active state"""
    try:
        strategy = db.query(ActivatedStrategy).filter(
            ActivatedStrategy.id == strategy_id,
            ActivatedStrategy.user_id == current_user.id
        ).first()

        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")

        # Check limits if activating
        if not strategy.is_active:
            subscription_service = SubscriptionService(db)
            can_add, message = subscription_service.can_add_resource(
                current_user.id,
                "active_strategies"
            )
            if not can_add:
                raise HTTPException(status_code=403, detail=message)

        # Toggle state
        old_state = strategy.is_active
        strategy.is_active = not strategy.is_active
        strategy.updated_at = datetime.utcnow()

        # Update subscription counter
        subscription = db.query(Subscription).filter(
            Subscription.user_id == current_user.id
        ).first()

        if subscription:
            if strategy.is_active and not old_state:
                subscription.active_strategies_count = (subscription.active_strategies_count or 0) + 1
            elif not strategy.is_active and old_state:
                if subscription.active_strategies_count > 0:
                    subscription.active_strategies_count -= 1

        db.commit()

        return StrategyToggleResponse(
            id=strategy_id,
            is_active=strategy.is_active
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error toggling strategy: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/validate", response_model=StrategyValidationResponse)
async def validate_strategy(
    request: StrategyValidationRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Pre-validate strategy data before creation.
    Returns validation errors and warnings without creating the strategy.
    """
    errors = []
    warnings = []
    strategy_data = request.strategy_data

    try:
        # Validate ticker
        valid, error_msg = validate_ticker(strategy_data.ticker)
        if not valid:
            errors.append(f"Invalid ticker: {error_msg}")

        # Validate execution source access
        try:
            if strategy_data.execution_type == ExecutionType.WEBHOOK:
                validate_webhook_access(strategy_data.webhook_id, current_user, db)
            else:
                validate_strategy_code_access(strategy_data.strategy_code_id, current_user, db)
        except HTTPException as e:
            errors.append(e.detail)

        # Validate account ownership
        try:
            if strategy_data.strategy_type == StrategyType.SINGLE:
                validate_account_ownership(strategy_data.account_id, current_user, db)
            else:
                validate_account_ownership(strategy_data.leader_account_id, current_user, db)
                for follower in strategy_data.follower_accounts or []:
                    validate_account_ownership(follower.account_id, current_user, db)
        except HTTPException as e:
            errors.append(e.detail)

        # Check for duplicates
        if check_duplicate_strategy(strategy_data, current_user.id, db):
            errors.append("A strategy with these parameters already exists")

        # Check subscription limits
        subscription_service = SubscriptionService(db)
        can_add, message = subscription_service.can_add_resource(
            current_user.id,
            "active_strategies"
        )
        if not can_add:
            errors.append(message)
        else:
            # Check if close to limit
            subscription = db.query(Subscription).filter(
                Subscription.user_id == current_user.id
            ).first()
            if subscription:
                active_count = subscription.active_strategies_count or 0
                tier_limits = {
                    'basic': 5,
                    'pro': 20,
                    'elite': None
                }
                limit = tier_limits.get(subscription.tier)
                if limit and active_count >= limit - 2:
                    warnings.append(f"Close to strategy limit ({active_count}/{limit})")

    except Exception as e:
        errors.append(f"Validation error: {str(e)}")

    return StrategyValidationResponse(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings
    )


@router.get("/my-strategies", response_model=List[UnifiedStrategyResponse])
async def get_my_strategies(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Get strategies created by the current user.
    This endpoint is for backward compatibility with legacy frontend.
    """
    strategies = db.query(ActivatedStrategy).options(
        joinedload(ActivatedStrategy.broker_account),
        joinedload(ActivatedStrategy.leader_broker_account),
        joinedload(ActivatedStrategy.webhook),
        joinedload(ActivatedStrategy.strategy_code)
    ).filter(
        ActivatedStrategy.user_id == current_user.id
    ).order_by(ActivatedStrategy.created_at.desc()).all()

    # Add follower information for multiple strategies
    for strategy in strategies:
        if strategy.strategy_type == StrategyType.MULTIPLE:
            strategy.follower_account_ids = strategy.get_follower_accounts()
            strategy.follower_quantities = strategy.get_follower_quantities()

    return strategies


@router.get("/user-activated", response_model=List[Dict[str, Any]])
async def get_user_activated_strategies(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Get ALL strategies activated by the current user (both active and inactive).

    Returns enriched strategy data including:
    - Strategy names (from webhook/strategy_code lookups)
    - Categories, descriptions
    - Broker account details
    - Performance metrics
    - Schedule information

    This provides 100% feature parity with legacy endpoint.
    """
    try:
        # Get ALL strategies for the user (removed is_active filter)
        strategies = db.query(ActivatedStrategy).options(
            joinedload(ActivatedStrategy.broker_account),
            joinedload(ActivatedStrategy.leader_broker_account),
            joinedload(ActivatedStrategy.webhook),
            joinedload(ActivatedStrategy.strategy_code)
        ).filter(
            ActivatedStrategy.user_id == current_user.id
            # REMOVED: ActivatedStrategy.is_active == True
        ).all()

        # Enrich all strategies with webhook/strategy_code data
        enriched_strategies = []
        for strategy in strategies:
            enriched = enrich_strategy_data(strategy, db)
            enriched_strategies.append(enriched)

        # Sort by most recently triggered/created (same as legacy)
        enriched_strategies.sort(
            key=lambda x: x.get("last_triggered") or x.get("created_at") or "",
            reverse=True
        )

        logger.info(f"Returning {len(enriched_strategies)} activated strategies for user {current_user.id}")

        return enriched_strategies

    except Exception as e:
        logger.error(f"Error getting user activated strategies: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch user activated strategies: {str(e)}"
        )


@router.post("/batch", response_model=Dict[str, Any])
@check_subscription
async def batch_operation(
    batch: StrategyBatchOperation,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """Perform batch operations on multiple strategies"""
    try:
        # Get all strategies
        strategies = db.query(ActivatedStrategy).filter(
            ActivatedStrategy.id.in_(batch.strategy_ids),
            ActivatedStrategy.user_id == current_user.id
        ).all()

        if len(strategies) != len(batch.strategy_ids):
            raise HTTPException(
                status_code=404,
                detail="Some strategies not found or not owned by user"
            )

        results = []
        subscription = db.query(Subscription).filter(
            Subscription.user_id == current_user.id
        ).first()

        for strategy in strategies:
            try:
                if batch.operation == 'activate':
                    if not strategy.is_active:
                        strategy.is_active = True
                        if subscription:
                            subscription.active_strategies_count = (subscription.active_strategies_count or 0) + 1
                        results.append({"id": strategy.id, "status": "activated"})
                    else:
                        results.append({"id": strategy.id, "status": "already_active"})

                elif batch.operation == 'deactivate':
                    if strategy.is_active:
                        strategy.is_active = False
                        if subscription and subscription.active_strategies_count > 0:
                            subscription.active_strategies_count -= 1
                        results.append({"id": strategy.id, "status": "deactivated"})
                    else:
                        results.append({"id": strategy.id, "status": "already_inactive"})

                elif batch.operation == 'delete':
                    if strategy.is_active and subscription and subscription.active_strategies_count > 0:
                        subscription.active_strategies_count -= 1
                    db.delete(strategy)
                    results.append({"id": strategy.id, "status": "deleted"})

            except Exception as e:
                results.append({"id": strategy.id, "status": "error", "error": str(e)})

        db.commit()

        return {
            "operation": batch.operation,
            "total": len(batch.strategy_ids),
            "successful": len([r for r in results if "error" not in r]),
            "results": results
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in batch operation: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))