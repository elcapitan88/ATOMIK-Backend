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
from ....models.strategy_code import StrategyCode
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
        
        # Find active Engine strategy configurations for this signal
        # Step 1: Find the strategy code by name
        strategy_code = db.query(StrategyCode).filter(
            StrategyCode.name == signal.strategy_name,
            StrategyCode.is_active == True
        ).first()
        
        if not strategy_code:
            raise HTTPException(
                status_code=404,
                detail=f"No active strategy code found with name '{signal.strategy_name}'"
            )
        
        # Step 2: Find activated Engine strategies using this strategy code and symbol
        engine_strategies = db.query(ActivatedStrategy).filter(
            ActivatedStrategy.strategy_code_id == strategy_code.id,
            ActivatedStrategy.execution_type == 'engine',
            ActivatedStrategy.ticker == signal.symbol,
            ActivatedStrategy.is_active == True
        ).all()
        
        if not engine_strategies:
            raise HTTPException(
                status_code=404,
                detail=f"No active Engine strategies found for '{signal.strategy_name}' on symbol '{signal.symbol}'"
            )
        
        logger.info(f"Found {len(engine_strategies)} active Engine strategies for {signal.strategy_name} on {signal.symbol}")
        
        execution_results = []
        
        # Execute signal on all configured Engine strategies
        for strategy in engine_strategies:
            try:
                logger.info(f"Executing on strategy {strategy.id} for user {strategy.user_id}, account {strategy.account_id}, quantity {strategy.quantity}")
        
                # Convert signal to webhook payload format for StrategyProcessor
                # Use the strategy's configured quantity, not the signal quantity
                signal_data = {
                    "action": signal.action.upper(),
                    "comment": signal.comment or "",
                    "timestamp": signal.timestamp,
                    "source": "strategy_engine",
                    "strategy_name": signal.strategy_name,
                    "price": signal.price,
                    "ticker": signal.symbol
                }
                
                # Execute through the existing StrategyProcessor
                strategy_processor = StrategyProcessor(db)
                
                result = await strategy_processor.execute_strategy(strategy, signal_data)
                
                # Track execution result
                execution_result = {
                    "strategy_id": strategy.id,
                    "user_id": strategy.user_id,
                    "account_id": strategy.account_id,
                    "configured_quantity": strategy.quantity,
                    "success": result.get("status") == "success",
                    "result": result
                }
                
                if result.get("status") == "success":
                    execution_result.update({
                        "execution_id": result.get("order_id"),
                        "broker_order_id": result.get("order_details", {}).get("order_id"),
                        "filled_price": result.get("order_details", {}).get("price", signal.price),
                        "status": "filled"
                    })
                    logger.info(f"Strategy {strategy.id} executed successfully: {result}")
                else:
                    execution_result.update({
                        "status": result.get("status", "failed"),
                        "error": result.get("reason", "Execution failed")
                    })
                    logger.warning(f"Strategy {strategy.id} execution failed: {result}")
                
                execution_results.append(execution_result)
                
            except Exception as exec_error:
                logger.error(f"Execution error for strategy {strategy.id}: {str(exec_error)}")
                execution_results.append({
                    "strategy_id": strategy.id,
                    "user_id": strategy.user_id,
                    "account_id": strategy.account_id,
                    "success": False,
                    "error": str(exec_error)
                })
        
        # Compile overall execution summary
        successful_executions = [r for r in execution_results if r.get("success")]
        failed_executions = [r for r in execution_results if not r.get("success")]
        
        return {
            "signal_processed": True,
            "strategy_name": signal.strategy_name,
            "symbol": signal.symbol,
            "action": signal.action,
            "total_strategies": len(execution_results),
            "successful_executions": len(successful_executions),
            "failed_executions": len(failed_executions),
            "execution_details": execution_results,
            "message": f"Processed signal for {len(execution_results)} strategies: {len(successful_executions)} successful, {len(failed_executions)} failed"
        }
        
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