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

# Debug: Log when module is imported
import sys
print(f"DEBUG: strategy_unified.py module loaded", file=sys.stderr, flush=True)
logger.error("DEBUG: strategy_unified.py module imported")


@router.get("/debug-test")
async def debug_test_endpoint():
    """Direct test endpoint with no dependencies"""
    print("DEBUG: /debug-test endpoint hit!", file=sys.stderr, flush=True)
    return {"status": "test endpoint working", "message": "No dependencies"}


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


@router.get("/simple-list")
async def simple_list_strategies():
    """Test endpoint with minimal dependencies"""
    print("DEBUG: /simple-list endpoint hit!", file=sys.stderr, flush=True)
    return []


@router.get("/", response_model=List[UnifiedStrategyResponse])
async def list_strategies(
    execution_type: Optional[ExecutionType] = Query(None, description="Filter by execution type"),
    strategy_type: Optional[StrategyType] = Query(None, description="Filter by strategy type"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    ticker: Optional[str] = Query(None, description="Filter by ticker"),
    account_id: Optional[str] = Query(None, description="Filter by account"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
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

        query = db.query(ActivatedStrategy).options(
            joinedload(ActivatedStrategy.broker_account),
            joinedload(ActivatedStrategy.leader_broker_account),
            joinedload(ActivatedStrategy.webhook),
            joinedload(ActivatedStrategy.strategy_code)
        ).filter(ActivatedStrategy.user_id == current_user.id)

        # Apply filters
        if execution_type:
            query = query.filter(ActivatedStrategy.execution_type == execution_type)
        if strategy_type:
            query = query.filter(ActivatedStrategy.strategy_type == strategy_type)
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
        return strategies
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


@router.get("/user-activated", response_model=List[UnifiedStrategyResponse])
async def get_user_activated_strategies(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Get all strategies activated by the current user.
    This includes both strategies created by the user and strategies they're subscribed to.
    This endpoint is for backward compatibility with legacy frontend.
    """
    # Get all strategies for the user (both created and subscribed)
    strategies = db.query(ActivatedStrategy).options(
        joinedload(ActivatedStrategy.broker_account),
        joinedload(ActivatedStrategy.leader_broker_account),
        joinedload(ActivatedStrategy.webhook),
        joinedload(ActivatedStrategy.strategy_code)
    ).filter(
        ActivatedStrategy.user_id == current_user.id,
        ActivatedStrategy.is_active == True
    ).order_by(ActivatedStrategy.created_at.desc()).all()

    # Add follower information for multiple strategies
    for strategy in strategies:
        if strategy.strategy_type == StrategyType.MULTIPLE:
            strategy.follower_account_ids = strategy.get_follower_accounts()
            strategy.follower_quantities = strategy.get_follower_quantities()

    return strategies


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


# Legacy endpoint mappings for backward compatibility

@router.post("/activate", response_model=UnifiedStrategyResponse)
@check_subscription
@check_resource_limit("active_strategies")
async def activate_strategy(
    strategy_data: Union[SingleStrategyCreate, MultipleStrategyCreate],
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Legacy endpoint for activating a webhook strategy.
    Maps to the unified create_strategy endpoint.
    """
    # Convert legacy format to unified format
    unified_data = UnifiedStrategyCreate(
        strategy_type=strategy_data.strategy_type,
        execution_type=ExecutionType.WEBHOOK,
        webhook_id=strategy_data.webhook_id,
        ticker=strategy_data.ticker,
        is_active=True,
        account_id=getattr(strategy_data, 'account_id', None),
        quantity=getattr(strategy_data, 'quantity', None),
        leader_account_id=getattr(strategy_data, 'leader_account_id', None),
        leader_quantity=getattr(strategy_data, 'leader_quantity', None),
        follower_accounts=[
            FollowerAccount(account_id=acc_id, quantity=qty)
            for acc_id, qty in zip(
                getattr(strategy_data, 'follower_account_ids', []) or [],
                getattr(strategy_data, 'follower_quantities', []) or []
            )
        ] if hasattr(strategy_data, 'follower_account_ids') else None
    )

    return await create_strategy(unified_data, db, current_user)


@router.get("/list", response_model=List[UnifiedStrategyResponse])
async def list_strategies_legacy(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Legacy endpoint for listing webhook strategies.
    Maps to the unified list_strategies endpoint with webhook filter.
    """
    return await list_strategies(
        execution_type=ExecutionType.WEBHOOK,
        db=db,
        current_user=current_user
    )


@router.post("/engine/configure", response_model=UnifiedStrategyResponse)
@check_subscription
@check_resource_limit("active_strategies")
async def configure_engine_strategy(
    strategy_data: EngineStrategyCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Legacy endpoint for configuring an engine strategy.
    Maps to the unified create_strategy endpoint.
    """
    # Convert legacy format to unified format
    unified_data = UnifiedStrategyCreate(
        strategy_type=strategy_data.strategy_type,
        execution_type=ExecutionType.ENGINE,
        strategy_code_id=strategy_data.strategy_code_id,
        ticker=strategy_data.ticker,
        is_active=getattr(strategy_data, 'is_active', True),
        account_id=getattr(strategy_data, 'account_id', None),
        quantity=getattr(strategy_data, 'quantity', None),
        leader_account_id=getattr(strategy_data, 'leader_account_id', None),
        leader_quantity=getattr(strategy_data, 'leader_quantity', None),
        follower_accounts=[
            FollowerAccount(account_id=acc_id, quantity=qty)
            for acc_id, qty in zip(
                getattr(strategy_data, 'follower_account_ids', []) or [],
                getattr(strategy_data, 'follower_quantities', []) or []
            )
        ] if hasattr(strategy_data, 'follower_account_ids') else None
    )

    return await create_strategy(unified_data, db, current_user)


@router.get("/engine/list", response_model=List[UnifiedStrategyResponse])
async def list_engine_strategies(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Legacy endpoint for listing engine strategies.
    Maps to the unified list_strategies endpoint with engine filter.
    """
    return await list_strategies(
        execution_type=ExecutionType.ENGINE,
        db=db,
        current_user=current_user
    )


@router.put("/engine/{strategy_id}", response_model=UnifiedStrategyResponse)
@check_subscription
async def update_engine_strategy(
    strategy_id: int,
    updates: EngineStrategyUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Legacy endpoint for updating an engine strategy.
    Maps to the unified update_strategy endpoint.
    """
    # Convert legacy format to unified format
    unified_updates = UnifiedStrategyUpdate(
        is_active=updates.is_active if hasattr(updates, 'is_active') else None,
        quantity=updates.quantity if hasattr(updates, 'quantity') else None,
        leader_quantity=updates.leader_quantity if hasattr(updates, 'leader_quantity') else None,
        follower_quantities=updates.follower_quantities if hasattr(updates, 'follower_quantities') else None,
        description=updates.description if hasattr(updates, 'description') else None
    )

    return await update_strategy(strategy_id, unified_updates, db, current_user)


@router.delete("/engine/{strategy_id}")
async def delete_engine_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Legacy endpoint for deleting an engine strategy.
    Maps to the unified delete_strategy endpoint.
    """
    return await delete_strategy(strategy_id, db, current_user)