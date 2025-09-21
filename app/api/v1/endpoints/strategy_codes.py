"""Strategy code management endpoints for Strategy Engine integration."""
import logging
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from pydantic import BaseModel, validator

from ....db.session import get_db
from ....core.config import settings
from ....core.security import get_current_user
from ....models.user import User
from ....models.strategy_code import StrategyCode
from ....models.webhook import WebhookSubscription
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

    @validator('signals_generated', pre=True)
    def validate_signals_generated(cls, v):
        return v if v is not None else 0
    
    @validator('error_count', pre=True)
    def validate_error_count(cls, v):
        return v if v is not None else 0

    class Config:
        from_attributes = True


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