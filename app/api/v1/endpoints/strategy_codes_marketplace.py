"""Marketplace endpoints for Strategy Engine strategies."""
import logging
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ....db.session import get_db
from ....core.security import get_current_user_optional
from ....models.user import User
from ....models.strategy_code import StrategyCode

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/available", response_model=List[Dict[str, Any]])
async def get_available_strategies(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_optional)
):
    """
    Get all available Strategy Engine strategies for marketplace.
    Returns public strategies that users can activate/subscribe to.
    """
    try:
        # Get all active and validated strategies
        # In production, you might want to filter by a "is_public" flag
        # For now, we'll show all active strategies from the system user (39)
        available_strategies = db.query(StrategyCode).filter(
            StrategyCode.is_active == True,
            StrategyCode.is_validated == True,
            StrategyCode.user_id == 39  # System/public strategies owner
        ).all()
        
        strategies_list = []
        for strategy in available_strategies:
            strategy_data = {
                "id": strategy.id,
                "name": strategy.name,
                "display_name": strategy.name.replace("_", " ").title(),
                "description": strategy.description or "Advanced trading strategy",
                "symbols": strategy.symbols_list,
                "creator": "Atomik Trading",  # Or fetch from user if needed
                "category": "Strategy Engine",
                "is_active": strategy.is_active,
                "signals_generated": strategy.signals_generated,
                "version": strategy.version,
                "features": [
                    "Automated Execution",
                    "Real-time Signals",
                    "Risk Management"
                ],
                "performance": {
                    "signals_total": strategy.signals_generated,
                    "last_signal": strategy.last_signal_at.isoformat() if strategy.last_signal_at else None,
                    "error_rate": (strategy.error_count / max(strategy.signals_generated, 1)) * 100 if strategy.signals_generated else 0
                }
            }
            strategies_list.append(strategy_data)
        
        logger.info(f"Returning {len(strategies_list)} available strategies for marketplace")
        return strategies_list
        
    except Exception as e:
        logger.error(f"Error getting available strategies: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{strategy_id}/details", response_model=Dict[str, Any])
async def get_strategy_details(
    strategy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_optional)
):
    """Get detailed information about a specific strategy for marketplace display."""
    try:
        strategy = db.query(StrategyCode).filter(
            StrategyCode.id == strategy_id,
            StrategyCode.is_active == True,
            StrategyCode.is_validated == True
        ).first()
        
        if not strategy:
            raise HTTPException(
                status_code=404,
                detail="Strategy not found or not available"
            )
        
        return {
            "id": strategy.id,
            "name": strategy.name,
            "display_name": strategy.name.replace("_", " ").title(),
            "description": strategy.description or "Advanced algorithmic trading strategy",
            "long_description": f"""
                {strategy.description}
                
                This strategy is powered by the Atomik Strategy Engine and provides:
                • Real-time market data analysis
                • Automated trade execution
                • Built-in risk management
                • Position sizing and stop loss protection
            """,
            "symbols": strategy.symbols_list,
            "creator": "Atomik Trading",
            "category": "Strategy Engine",
            "version": strategy.version,
            "created_at": strategy.created_at.isoformat(),
            "updated_at": strategy.updated_at.isoformat(),
            "is_active": strategy.is_active,
            "features": [
                "Automated Execution",
                "Real-time Signals", 
                "Risk Management",
                "Position Sizing",
                "Stop Loss Protection"
            ],
            "requirements": [
                "Active broker account",
                "Subscription to Atomik Trading",
                "Minimum account balance"
            ],
            "performance": {
                "signals_generated": strategy.signals_generated,
                "last_signal_at": strategy.last_signal_at.isoformat() if strategy.last_signal_at else None,
                "error_count": strategy.error_count,
                "success_rate": 100 - ((strategy.error_count / max(strategy.signals_generated, 1)) * 100) if strategy.signals_generated else None
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting strategy details: {e}")
        raise HTTPException(status_code=500, detail=str(e))