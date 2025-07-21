# app/api/v1/api.py
from fastapi import APIRouter, Depends
import logging

# Setup logging for import debugging
logger = logging.getLogger(__name__)
logger.info("Starting API router imports...")

# Import basic required endpoints
from .endpoints import auth, broker, subscription, webhooks, strategy, tradovate, binance, futures_contracts, admin
logger.info("Basic endpoints imported successfully")

# Import optional endpoints with individual error handling
chat = None
feature_flags = None
interactivebrokers = None
creators = None
marketplace = None

try:
    from .endpoints import chat
    logger.info("Chat endpoint imported successfully")
except Exception as e:
    logger.warning(f"Could not import chat endpoint: {e}")

try:
    from .endpoints import feature_flags
    logger.info("Feature flags endpoint imported successfully")
except Exception as e:
    logger.warning(f"Could not import feature_flags endpoint: {e}")

try:
    from .endpoints import interactivebrokers
    logger.info("Interactive Brokers endpoint imported successfully")
except Exception as e:
    logger.warning(f"Could not import interactivebrokers endpoint: {e}")

try:
    from .endpoints import creators
    logger.info("Creators endpoint imported successfully")
except Exception as e:
    logger.warning(f"Could not import creators endpoint: {e}")

try:
    from .endpoints import marketplace
    logger.info("Marketplace endpoint imported successfully")
except Exception as e:
    logger.warning(f"Could not import marketplace endpoint: {e}")

# Temporarily disabled strategy_ai endpoints to fix startup issues
# from .endpoints.strategy_ai import interpret_router, generate_router, templates_router, context_router
from typing import Optional
from sqlalchemy.orm import Session
from app.db.session import get_db

# Create routers
api_router = APIRouter()
tradovate_callback_router = APIRouter()

# Include all standard routes under /api/v1
api_router.include_router(tradovate.router, prefix="/brokers/tradovate", tags=["tradovate"])
api_router.include_router(binance.router, prefix="/brokers/binance", tags=["binance"])
api_router.include_router(broker.router, prefix="/brokers", tags=["brokers"])
api_router.include_router(auth.router, prefix="/auth", tags=["authentication"])
api_router.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
api_router.include_router(strategy.router, prefix="/strategies", tags=["strategies"])
api_router.include_router(subscription.router, prefix="/subscriptions", tags=["subscriptions"])

# Register admin router with logging
try:
    logger.info("Registering admin router...")
    api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
    logger.info(f"Admin router registered successfully with {len(admin.router.routes)} routes")
    for route in admin.router.routes:
        logger.info(f"Admin route: {route.methods} {route.path}")
except Exception as e:
    logger.error(f"Error registering admin router: {e}")

# Register optional routers only if they were imported successfully
if chat is not None:
    try:
        api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
        logger.info("Chat router registered")
    except Exception as e:
        logger.error(f"Error registering chat router: {e}")

if feature_flags is not None:
    try:
        api_router.include_router(feature_flags.router, prefix="/beta", tags=["features"])
        logger.info("Feature flags router registered")
    except Exception as e:
        logger.error(f"Error registering feature_flags router: {e}")

if interactivebrokers is not None:
    try:
        api_router.include_router(interactivebrokers.router, prefix="/brokers/interactivebrokers", tags=["interactive-brokers"])
        logger.info("Interactive Brokers router registered")
    except Exception as e:
        logger.error(f"Error registering interactivebrokers router: {e}")

# Register futures contracts router (this should always work)
try:
    api_router.include_router(futures_contracts.router, prefix="/futures-contracts", tags=["futures-contracts"])
    logger.info("Futures contracts router registered")
except Exception as e:
    logger.error(f"Error registering futures contracts router: {e}")

# Register creator marketplace routers only if imported
if creators is not None:
    try:
        api_router.include_router(creators.router, prefix="/creators", tags=["creators"])
        logger.info("Creators router registered")
    except Exception as e:
        logger.error(f"Error registering creators router: {e}")

if marketplace is not None:
    try:
        api_router.include_router(marketplace.router, prefix="/marketplace", tags=["marketplace"])
        logger.info("Marketplace router registered")
    except Exception as e:
        logger.error(f"Error registering marketplace router: {e}")

# Define the callback route - Notice the change in the path
@tradovate_callback_router.get("/tradovate/callback")  # Changed from "/api/tradovate/callback"
async def tradovate_callback_handler(
    code: str,
    state: Optional[str] = None,
    db: Session = Depends(get_db)
):
    return await tradovate.tradovate_callback(code=code, state=state, db=db)