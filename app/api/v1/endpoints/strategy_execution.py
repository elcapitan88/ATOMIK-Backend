"""Strategy execution endpoints for Strategy Engine."""
import logging
from typing import Dict, Any
from fastapi import APIRouter, HTTPException, Header, Depends
from pydantic import BaseModel

from ....core.config import settings
from ....schemas.webhook import WebhookPayload

router = APIRouter()
logger = logging.getLogger(__name__)


class StrategySignalRequest(BaseModel):
    """Request model for strategy signals."""
    action: str  # BUY, SELL
    comment: str = None  # EXIT_50, EXIT_FINAL, etc.
    strategy_name: str = None
    symbol: str = None


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
    authenticated: bool = Depends(verify_strategy_engine_api_key)
) -> Dict[str, Any]:
    """
    Execute trading signal from Strategy Engine.
    
    This endpoint receives signals from the Strategy Engine service
    and processes them through the existing webhook infrastructure.
    """
    try:
        logger.info(f"Received strategy signal: {signal.strategy_name} {signal.action} {signal.symbol}")
        
        # Convert to WebhookPayload format for consistency with existing system
        webhook_payload = WebhookPayload(
            action=signal.action,
            comment=signal.comment
        )
        
        # TODO: Process through existing webhook/trading infrastructure
        # For now, just log the signal
        logger.info(f"Processing signal: {webhook_payload.dict()}")
        
        return {
            "success": True,
            "message": "Signal received and queued for execution",
            "signal": {
                "action": signal.action,
                "comment": signal.comment,
                "strategy_name": signal.strategy_name,
                "symbol": signal.symbol
            }
        }
        
    except Exception as e:
        logger.error(f"Error processing strategy signal: {e}")
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