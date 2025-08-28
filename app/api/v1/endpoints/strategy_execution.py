"""Strategy execution endpoints for Strategy Engine."""
import logging
from typing import Dict, Any, Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException, Header, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ....core.config import settings
from ....schemas.webhook import WebhookPayload
from ....db.session import get_db
from ....models.strategy import ActivatedStrategy
from ....models.webhook import Webhook
from ....services.strategy_service import StrategyProcessor

router = APIRouter()
logger = logging.getLogger(__name__)


class StrategySignalRequest(BaseModel):
    """Request model for strategy signals from Strategy Engine."""
    action: str = Field(..., description="BUY or SELL")
    symbol: str = Field(..., description="Trading symbol (e.g., MES, ES)")
    strategy_name: str = Field(..., description="Name of the strategy")
    quantity: int = Field(..., description="Number of contracts")
    price: float = Field(..., description="Signal price")
    timestamp: str = Field(..., description="ISO timestamp")
    comment: Optional[str] = Field(None, description="EXIT_50, EXIT_FINAL, etc.")


def verify_strategy_engine_api_key(x_api_key: str = Header(None, alias="X-API-Key")) -> bool:
    """Verify API key for Strategy Engine authentication."""
    if not settings.STRATEGY_ENGINE_API_KEY:
        logger.warning("No STRATEGY_ENGINE_API_KEY configured - allowing all requests")
        return True
    
    if x_api_key != settings.STRATEGY_ENGINE_API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Invalid API key"
        )
    
    return True


@router.post("/execute")
async def execute_strategy_signal(
    signal: StrategySignalRequest,
    db: Session = Depends(get_db),
    authenticated: bool = Depends(verify_strategy_engine_api_key)
) -> Dict[str, Any]:
    """
    Execute trading signal from Strategy Engine.
    
    This endpoint:
    1. Receives signals from the automated Strategy Engine
    2. Finds or creates an appropriate strategy configuration
    3. Executes through the existing StrategyProcessor (broker-agnostic)
    4. Returns execution status
    """
    try:
        logger.info(f"Strategy Engine signal: {signal.strategy_name} {signal.action} {signal.symbol} x{signal.quantity}")
        
        # Find an active strategy for this signal
        # First, look for a strategy-engine specific configuration
        strategy = db.query(ActivatedStrategy).filter(
            ActivatedStrategy.ticker == signal.symbol,
            ActivatedStrategy.is_active == True,
            # Could filter by strategy_name in webhook details
        ).first()
        
        if not strategy:
            # Create a temporary strategy for this execution
            # In production, this would be configured ahead of time
            logger.warning(f"No active strategy found for {signal.symbol}, using default configuration")
            
            # Find a suitable broker account (prefer paper/demo for testing)
            from ....models.broker import BrokerAccount
            broker_account = db.query(BrokerAccount).filter(
                BrokerAccount.is_active == True
            ).first()
            
            if not broker_account:
                raise HTTPException(
                    status_code=503,
                    detail="No active broker account available for execution"
                )
            
            # Create temporary strategy configuration
            strategy = ActivatedStrategy(
                user_id=broker_account.user_id,
                strategy_type='single',
                ticker=signal.symbol,
                account_id=broker_account.account_id,
                quantity=signal.quantity,
                is_active=True,
                webhook_id=f"strategy_engine_{signal.strategy_name}"  # Virtual webhook ID
            )
            
            # Note: Not persisting this temporary strategy to DB
        
        # Convert signal to webhook payload format for StrategyProcessor
        signal_data = {
            "action": signal.action.upper(),
            "comment": signal.comment or "",
            "timestamp": signal.timestamp,
            "source": "strategy_engine",
            "strategy_name": signal.strategy_name,
            "price": signal.price
        }
        
        # Execute through the existing StrategyProcessor
        strategy_processor = StrategyProcessor(db)
        
        try:
            result = await strategy_processor.execute_strategy(strategy, signal_data)
            
            # Check if execution was successful
            if result.get("status") == "success":
                logger.info(f"Strategy signal executed successfully: {result}")
                
                return {
                    "success": True,
                    "execution_id": result.get("order_id"),
                    "broker_order_id": result.get("order_details", {}).get("order_id"),
                    "filled_price": result.get("order_details", {}).get("price", signal.price),
                    "filled_quantity": signal.quantity,
                    "status": "filled",
                    "message": f"Order executed: {signal.action} {signal.quantity}x {signal.symbol}",
                    "details": result
                }
            else:
                logger.warning(f"Strategy signal execution failed: {result}")
                
                return {
                    "success": False,
                    "status": result.get("status", "failed"),
                    "message": result.get("reason", "Execution failed"),
                    "details": result
                }
                
        except Exception as exec_error:
            logger.error(f"Execution error: {str(exec_error)}")
            raise HTTPException(
                status_code=500,
                detail=f"Execution failed: {str(exec_error)}"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing strategy signal: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process signal: {str(e)}"
        )


@router.get("/health")
async def strategy_execution_health(
    authenticated: bool = Depends(verify_strategy_engine_api_key)
) -> Dict[str, Any]:
    """Health check endpoint for Strategy Engine."""
    return {
        "status": "healthy",
        "service": "strategy_execution",
        "authenticated": True
    }