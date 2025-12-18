"""Strategy code management endpoints for Strategy Engine integration."""
import logging
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from pydantic import BaseModel, validator

from ....db.session import get_db
from ....core.config import settings
from ....core.security import get_current_user
from ....core.permissions import require_creator_mode, require_public_creator
from ....models.user import User
from ....models.strategy_code import StrategyCode
from ....models.webhook import WebhookSubscription
from ....services.strategy_hash_service import StrategyHashService
from datetime import datetime

router = APIRouter()
logger = logging.getLogger(__name__)


class StrategyCodeCreate(BaseModel):
    """Request model for creating strategy code."""
    name: str
    description: Optional[str] = None
    code: str
    symbols: List[str] = []


class StrategyCodeUpdate(BaseModel):
    """Request model for updating strategy code."""
    name: Optional[str] = None
    description: Optional[str] = None
    code: Optional[str] = None
    symbols: Optional[List[str]] = None
    is_active: Optional[bool] = None


class StrategyCodeResponse(BaseModel):
    """Response model for strategy code."""
    id: int
    user_id: int
    name: str
    description: Optional[str]
    symbols_list: List[str]
    is_active: bool
    is_validated: bool
    validation_error: Optional[str]
    version: int
    created_at: str
    updated_at: str
    signals_generated: Optional[int] = 0
    error_count: Optional[int] = 0

    # Phase 1.1: Hash fields for trust verification
    code_hash: Optional[str] = None
    config_hash: Optional[str] = None
    combined_hash: Optional[str] = None
    locked_at: Optional[str] = None
    is_locked: bool = False
    parent_strategy_id: Optional[int] = None

    # Phase 1.1: Live performance metrics
    live_total_trades: int = 0
    live_winning_trades: int = 0
    live_total_pnl: float = 0.0
    live_win_rate: float = 0.0

    @validator('signals_generated', pre=True)
    def validate_signals_generated(cls, v):
        return v if v is not None else 0

    @validator('error_count', pre=True)
    def validate_error_count(cls, v):
        return v if v is not None else 0

    @validator('is_locked', pre=True, always=True)
    def compute_is_locked(cls, v, values):
        return values.get('locked_at') is not None

    @validator('live_total_pnl', 'live_win_rate', pre=True)
    def convert_decimal(cls, v):
        return float(v) if v is not None else 0.0

    class Config:
        from_attributes = True


class StrategyVersionCreate(BaseModel):
    """Request model for creating a new version from a locked strategy."""
    code: Optional[str] = None
    symbols: Optional[List[str]] = None
    name: Optional[str] = None
    description: Optional[str] = None


def verify_strategy_engine_api_key(x_api_key: str = Header(None, alias="X-API-Key")) -> bool:
    """Verify API key for Strategy Engine authentication."""
    if not settings.STRATEGY_ENGINE_API_KEY:
        logger.warning("No STRATEGY_ENGINE_API_KEY configured - allowing all requests")
        return True
    
    if x_api_key != settings.STRATEGY_ENGINE_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    return True


@router.get("/active-codes", response_model=Dict[str, Any])
async def get_active_strategy_codes(
    db: Session = Depends(get_db),
    authenticated: bool = Depends(verify_strategy_engine_api_key)
):
    """
    Get all active strategy codes for Strategy Engine execution.
    Used by Strategy Engine to load strategies from database.
    """
    try:
        active_strategies = db.query(StrategyCode).filter(
            StrategyCode.is_active == True,
            StrategyCode.is_validated == True
        ).all()
        
        strategies_data = []
        for strategy in active_strategies:
            strategies_data.append({
                "id": strategy.id,
                "user_id": strategy.user_id,
                "name": strategy.name,
                "description": strategy.description,
                "code": strategy.code,
                "symbols_list": strategy.symbols_list,
                "version": strategy.version,
                "created_at": strategy.created_at.isoformat(),
                "updated_at": strategy.updated_at.isoformat()
            })
        
        logger.info(f"Returning {len(strategies_data)} active strategies to Strategy Engine")
        
        return {
            "success": True,
            "count": len(strategies_data),
            "strategies": strategies_data
        }
        
    except Exception as e:
        logger.error(f"Error getting active strategy codes: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/code/{strategy_id}")
async def get_strategy_code(
    strategy_id: int,
    db: Session = Depends(get_db),
    authenticated: bool = Depends(verify_strategy_engine_api_key)
):
    """
    Get specific strategy code by ID for Strategy Engine reload.
    """
    try:
        strategy = db.query(StrategyCode).filter(StrategyCode.id == strategy_id).first()
        
        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")
        
        return {
            "id": strategy.id,
            "user_id": strategy.user_id,
            "name": strategy.name,
            "description": strategy.description,
            "code": strategy.code,
            "symbols_list": strategy.symbols_list,
            "version": strategy.version,
            "is_active": strategy.is_active,
            "is_validated": strategy.is_validated,
            "created_at": strategy.created_at.isoformat(),
            "updated_at": strategy.updated_at.isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting strategy code {strategy_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload", response_model=StrategyCodeResponse)
async def upload_strategy_code(
    strategy: StrategyCodeCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Upload new strategy code for user.
    This will be used by the frontend to allow users to upload strategies.
    """
    try:
        # TODO: Add code validation with RestrictedPython
        # For now, just mark as unvalidated
        
        db_strategy = StrategyCode(
            user_id=current_user.id,
            name=strategy.name,
            description=strategy.description,
            code=strategy.code,
            is_active=False,  # Not active until validated
            is_validated=False
        )
        
        # Set symbols
        db_strategy.set_symbols_list(strategy.symbols)
        
        db.add(db_strategy)
        db.commit()
        db.refresh(db_strategy)
        
        logger.info(f"User {current_user.id} uploaded strategy: {strategy.name}")
        
        return StrategyCodeResponse(
            id=db_strategy.id,
            user_id=db_strategy.user_id,
            name=db_strategy.name,
            description=db_strategy.description,
            symbols_list=db_strategy.symbols_list,
            is_active=db_strategy.is_active,
            is_validated=db_strategy.is_validated,
            validation_error=db_strategy.validation_error,
            version=db_strategy.version,
            created_at=db_strategy.created_at.isoformat(),
            updated_at=db_strategy.updated_at.isoformat(),
            signals_generated=db_strategy.signals_generated,
            error_count=db_strategy.error_count
        )
        
    except Exception as e:
        logger.error(f"Error uploading strategy code: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))



@router.get("/my-strategies", response_model=List[StrategyCodeResponse])
async def get_user_strategies(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all strategy codes accessible to the user (owned or subscribed)."""
    try:
        # Get strategies the user owns
        owned_strategies = db.query(StrategyCode).filter(
            StrategyCode.user_id == current_user.id
        ).all()
        
        # Get strategy IDs the user is subscribed to via engine subscriptions
        subscriptions = db.query(WebhookSubscription).filter(
            WebhookSubscription.user_id == current_user.id,
            WebhookSubscription.strategy_type == 'engine',
            WebhookSubscription.strategy_code_id != None
        ).all()
        
        subscribed_strategy_ids = [sub.strategy_code_id for sub in subscriptions]
        
        # Get the subscribed strategies
        subscribed_strategies = []
        if subscribed_strategy_ids:
            subscribed_strategies = db.query(StrategyCode).filter(
                StrategyCode.id.in_(subscribed_strategy_ids)
            ).all()
        
        # Combine owned and subscribed strategies (remove duplicates)
        all_strategies = {}
        for strategy in owned_strategies:
            all_strategies[strategy.id] = strategy
        for strategy in subscribed_strategies:
            if strategy.id not in all_strategies:  # Only add if not already owned
                all_strategies[strategy.id] = strategy
        
        # Sort by created_at desc
        strategies = sorted(all_strategies.values(), key=lambda x: x.created_at, reverse=True)
        
        return [
            StrategyCodeResponse(
                id=strategy.id,
                user_id=strategy.user_id,
                name=strategy.name,
                description=strategy.description,
                symbols_list=strategy.symbols_list,
                is_active=strategy.is_active,
                is_validated=strategy.is_validated,
                validation_error=strategy.validation_error,
                version=strategy.version,
                created_at=strategy.created_at.isoformat(),
                updated_at=strategy.updated_at.isoformat(),
                signals_generated=strategy.signals_generated,
                error_count=strategy.error_count
            )
            for strategy in strategies
        ]
        
    except Exception as e:
        logger.error(f"Error getting user strategies: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{strategy_id}/activate")
async def activate_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Activate a strategy for execution."""
    try:
        strategy = db.query(StrategyCode).filter(
            StrategyCode.id == strategy_id,
            StrategyCode.user_id == current_user.id
        ).first()
        
        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")
        
        # TODO: Add validation before activation
        strategy.is_active = True
        strategy.is_validated = True  # Temporarily mark as validated
        strategy.activated_at = datetime.utcnow()
        
        db.commit()
        
        logger.info(f"User {current_user.id} activated strategy: {strategy.name}")

        # TODO: Signal Strategy Engine to reload strategies

        return {"success": True, "message": "Strategy activated"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error activating strategy {strategy_id}: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Phase 1.1: Strategy Hashing and Immutability Endpoints
# =============================================================================

def strategy_to_response(strategy: StrategyCode) -> StrategyCodeResponse:
    """Convert a StrategyCode model to response format."""
    return StrategyCodeResponse(
        id=strategy.id,
        user_id=strategy.user_id,
        name=strategy.name,
        description=strategy.description,
        symbols_list=strategy.symbols_list,
        is_active=strategy.is_active,
        is_validated=strategy.is_validated,
        validation_error=strategy.validation_error,
        version=strategy.version,
        created_at=strategy.created_at.isoformat() if strategy.created_at else None,
        updated_at=strategy.updated_at.isoformat() if strategy.updated_at else None,
        signals_generated=strategy.signals_generated,
        error_count=strategy.error_count,
        # Hash fields
        code_hash=strategy.code_hash,
        config_hash=strategy.config_hash,
        combined_hash=strategy.combined_hash,
        locked_at=strategy.locked_at.isoformat() if strategy.locked_at else None,
        is_locked=strategy.is_locked,
        parent_strategy_id=strategy.parent_strategy_id,
        # Live performance
        live_total_trades=strategy.live_total_trades or 0,
        live_winning_trades=strategy.live_winning_trades or 0,
        live_total_pnl=float(strategy.live_total_pnl) if strategy.live_total_pnl else 0.0,
        live_win_rate=float(strategy.live_win_rate) if strategy.live_win_rate else 0.0
    )


@router.post("/{strategy_id}/lock", response_model=StrategyCodeResponse)
async def lock_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Lock a strategy, making it immutable and generating cryptographic hashes.

    Once locked:
    - Code and configuration cannot be modified
    - A unique combined_hash is generated for verification
    - The strategy can be published to the marketplace (if user is public creator)
    - Performance history is tied to this specific version

    To make changes to a locked strategy, create a new version instead.
    """
    try:
        strategy = db.query(StrategyCode).filter(
            StrategyCode.id == strategy_id,
            StrategyCode.user_id == current_user.id
        ).first()

        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")

        if strategy.locked_at:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "ALREADY_LOCKED",
                    "message": "This strategy is already locked",
                    "locked_at": strategy.locked_at.isoformat(),
                    "combined_hash": strategy.combined_hash
                }
            )

        if not strategy.is_validated:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "NOT_VALIDATED",
                    "message": "Strategy must be validated before locking. Activate the strategy first to validate it."
                }
            )

        # Lock the strategy using the hash service
        hash_service = StrategyHashService(db)
        locked_strategy = hash_service.lock_strategy(strategy)

        logger.info(f"User {current_user.id} locked strategy {strategy_id}, hash: {locked_strategy.combined_hash[:16]}...")

        return strategy_to_response(locked_strategy)

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error locking strategy {strategy_id}: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{strategy_id}/new-version", response_model=StrategyCodeResponse)
@require_creator_mode
async def create_strategy_version(
    strategy_id: int,
    version_data: StrategyVersionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Create a new version of an existing strategy.

    This is the only way to modify a locked strategy. The new version:
    - Has a fresh performance history (starts at zero)
    - Gets a new combined_hash when locked
    - Links to the parent strategy for version lineage tracking
    - Inherits code/config from parent unless explicitly overridden
    """
    try:
        parent = db.query(StrategyCode).filter(
            StrategyCode.id == strategy_id,
            StrategyCode.user_id == current_user.id
        ).first()

        if not parent:
            raise HTTPException(status_code=404, detail="Parent strategy not found")

        # Create new version using hash service
        hash_service = StrategyHashService(db)
        new_version = hash_service.create_new_version(
            parent,
            new_code=version_data.code,
            new_symbols=version_data.symbols,
            new_name=version_data.name,
            new_description=version_data.description
        )

        logger.info(f"User {current_user.id} created version {new_version.version} of strategy {strategy_id}")

        return strategy_to_response(new_version)

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating strategy version from {strategy_id}: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{strategy_id}/versions", response_model=List[Dict[str, Any]])
async def get_version_history(
    strategy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get the full version history for a strategy.

    Returns all versions in the lineage, ordered from oldest to newest.
    Includes hash, lock status, and performance summary for each version.
    """
    try:
        strategy = db.query(StrategyCode).filter(
            StrategyCode.id == strategy_id,
            StrategyCode.user_id == current_user.id
        ).first()

        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")

        hash_service = StrategyHashService(db)
        versions = hash_service.get_version_history(strategy)

        return versions

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting version history for {strategy_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{strategy_id}/verify-hash")
async def verify_strategy_hash(
    strategy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Verify that a strategy's stored hash matches its current code/config.

    Used to detect any tampering or data corruption.
    Returns verification status and details.
    """
    try:
        strategy = db.query(StrategyCode).filter(
            StrategyCode.id == strategy_id,
            StrategyCode.user_id == current_user.id
        ).first()

        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")

        if not strategy.combined_hash:
            return {
                "verified": False,
                "message": "Strategy is not locked and has no hash",
                "is_locked": False
            }

        hash_service = StrategyHashService(db)
        is_valid, error_message = hash_service.verify_strategy_hash(strategy)

        return {
            "verified": is_valid,
            "message": error_message if error_message else "Hash verification successful",
            "is_locked": strategy.is_locked,
            "combined_hash": strategy.combined_hash,
            "locked_at": strategy.locked_at.isoformat() if strategy.locked_at else None
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error verifying hash for strategy {strategy_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{strategy_id}", response_model=StrategyCodeResponse)
@require_creator_mode
async def update_strategy_code(
    strategy_id: int,
    update_data: StrategyCodeUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Update a strategy's code, name, description, or symbols.

    IMPORTANT: Locked strategies cannot be updated. Create a new version instead.
    """
    try:
        strategy = db.query(StrategyCode).filter(
            StrategyCode.id == strategy_id,
            StrategyCode.user_id == current_user.id
        ).first()

        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")

        # Phase 1.1: Block updates to locked strategies
        if strategy.locked_at:
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "STRATEGY_LOCKED",
                    "message": "This strategy is locked and cannot be modified. Create a new version instead.",
                    "locked_at": strategy.locked_at.isoformat(),
                    "combined_hash": strategy.combined_hash,
                    "action": f"POST /api/v1/strategies/codes/{strategy_id}/new-version"
                }
            )

        # Apply updates
        if update_data.name is not None:
            strategy.name = update_data.name
        if update_data.description is not None:
            strategy.description = update_data.description
        if update_data.code is not None:
            strategy.code = update_data.code
            # Invalidate when code changes
            strategy.is_validated = False
        if update_data.symbols is not None:
            strategy.set_symbols_list(update_data.symbols)
        if update_data.is_active is not None:
            strategy.is_active = update_data.is_active

        strategy.updated_at = datetime.utcnow()

        db.commit()
        db.refresh(strategy)

        logger.info(f"User {current_user.id} updated strategy {strategy_id}")

        return strategy_to_response(strategy)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating strategy {strategy_id}: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{strategy_id}/publish", response_model=StrategyCodeResponse)
@require_public_creator
async def publish_strategy_to_marketplace(
    strategy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Publish a strategy to the marketplace.

    This endpoint performs TWO actions in one:
    1. LOCKS the strategy (generates cryptographic hashes, makes it immutable)
    2. Makes it visible in the marketplace

    Once published:
    - The strategy code cannot be modified (immutable)
    - A unique combined_hash is generated for public verification
    - Performance stats will update as trades execute
    - To make code changes, you must create a new version

    Prerequisites:
    - Strategy must be validated (activated at least once)
    - User must be a public creator
    """
    try:
        strategy = db.query(StrategyCode).filter(
            StrategyCode.id == strategy_id,
            StrategyCode.user_id == current_user.id
        ).first()

        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")

        # Check if already locked/published
        if strategy.locked_at:
            return strategy_to_response(strategy)  # Already published, return current state

        # Must be validated before publishing
        if not strategy.is_validated:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "NOT_VALIDATED",
                    "message": "Strategy must be validated before publishing. Activate the strategy first to validate it."
                }
            )

        # Lock the strategy (this generates hashes and makes it immutable)
        hash_service = StrategyHashService(db)
        locked_strategy = hash_service.lock_strategy(strategy)

        # Ensure it's active for marketplace visibility
        locked_strategy.is_active = True

        db.commit()
        db.refresh(locked_strategy)

        logger.info(
            f"User {current_user.id} published strategy {strategy_id} to marketplace, "
            f"hash: {locked_strategy.combined_hash[:16]}..."
        )

        return strategy_to_response(locked_strategy)

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error publishing strategy {strategy_id}: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{strategy_id}")
@require_creator_mode
async def delete_strategy_code(
    strategy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Delete a strategy.

    Note: Locked strategies with subscribers or trade history should not be deleted.
    Consider deactivating instead to preserve the audit trail.
    """
    try:
        strategy = db.query(StrategyCode).filter(
            StrategyCode.id == strategy_id,
            StrategyCode.user_id == current_user.id
        ).first()

        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")

        # Warn if deleting a locked strategy with trade history
        if strategy.locked_at and strategy.live_total_trades > 0:
            logger.warning(
                f"Deleting locked strategy {strategy_id} with {strategy.live_total_trades} trades. "
                "Consider deactivating instead."
            )

        db.delete(strategy)
        db.commit()

        logger.info(f"User {current_user.id} deleted strategy {strategy_id}")

        return {"success": True, "message": "Strategy deleted"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting strategy {strategy_id}: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))