# app/api/v1/api.py
from fastapi import APIRouter, Depends
import logging

# Setup logging for import debugging
logger = logging.getLogger(__name__)
logger.info("Starting API router imports...")

try:
    from .endpoints import auth, broker, subscription, webhooks, strategy, tradovate, binance, futures_contracts
    from .endpoints import strategy_monetization, creator_analytics, strategy_execution, strategy_codes
    from .endpoints import engine_strategies

    # Import new unified strategy endpoints
    try:
        from .endpoints import strategy_unified
        logger.info("Unified strategy endpoints imported successfully")
    except ImportError as e:
        logger.warning(f"Could not import unified strategy endpoints: {e}")
        strategy_unified = None

    logger.info("Basic endpoints imported successfully")
    
    from .endpoints import admin
    logger.info("Admin endpoint imported successfully")
    
    # Import working endpoints (excluding interactivebrokers which breaks)
    from .endpoints import creators, chat, feature_flags, marketplace, aria, affiliate, creator_profiles
    logger.info("Working endpoints imported successfully (including ARIA and affiliate)")
except Exception as e:
    logger.error(f"Error importing endpoints: {e}")
    import traceback
    logger.error(traceback.format_exc())

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

# Strategy endpoints configuration
# Use unified endpoints as primary, with legacy endpoints for backward compatibility
if 'strategy_unified' in locals() and strategy_unified is not None:
    logger.info("Using unified strategy endpoints as primary strategy API")
    # Register unified endpoints at /strategies for primary use
    api_router.include_router(strategy_unified.router, prefix="/strategies", tags=["strategies"])

    # Keep legacy endpoints at /strategies/legacy for backward compatibility if needed
    logger.info("Legacy endpoints available at /strategies/legacy for backward compatibility")
    api_router.include_router(strategy.router, prefix="/strategies/legacy", tags=["legacy-strategies"])
    api_router.include_router(strategy_codes.router, prefix="/strategies/legacy", tags=["legacy-strategy-codes"])
    api_router.include_router(engine_strategies.router, prefix="/strategies/legacy", tags=["legacy-engine-strategies"])
else:
    # Fallback to legacy endpoints if unified not available
    logger.warning("Unified strategy endpoints not available, using legacy endpoints")
    api_router.include_router(strategy.router, prefix="/strategies", tags=["strategies"])
    api_router.include_router(strategy_codes.router, prefix="/strategies", tags=["strategy-codes"])
    api_router.include_router(engine_strategies.router, prefix="/strategies", tags=["engine-strategies"])

api_router.include_router(strategy_execution.router, prefix="/trades", tags=["strategy-execution"])
# Old monetization system removed - consolidated into marketplace
# api_router.include_router(strategy_monetization.router, prefix="/strategies", tags=["strategy-monetization"])
api_router.include_router(creator_analytics.router, prefix="/analytics", tags=["creator-analytics"])
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

# Register additional routers
try:
    api_router.include_router(futures_contracts.router, prefix="/futures-contracts", tags=["futures-contracts"])
    logger.info("Futures contracts router registered")
except Exception as e:
    logger.error(f"Error registering futures contracts router: {e}")

try:
    api_router.include_router(creators.router, prefix="/creators", tags=["creators"])
    logger.info("Creators router registered")
except Exception as e:
    logger.error(f"Error registering creators router: {e}")

try:
    api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
    logger.info("Chat router registered")
except Exception as e:
    logger.error(f"Error registering chat router: {e}")

try:
    api_router.include_router(feature_flags.router, prefix="/beta", tags=["features"])
    logger.info("Feature flags router registered")
except Exception as e:
    logger.error(f"Error registering feature_flags router: {e}")

try:
    api_router.include_router(marketplace.router, prefix="/marketplace", tags=["marketplace"])
    logger.info("Marketplace router registered")
except Exception as e:
    logger.error(f"Error registering marketplace router: {e}")

# ARIA Assistant router
try:
    api_router.include_router(aria.router, prefix="/aria", tags=["aria-assistant"])
    logger.info("ARIA Assistant router registered")
except Exception as e:
    logger.error(f"Error registering ARIA router: {e}")

# Affiliate router
try:
    api_router.include_router(affiliate.router, prefix="/affiliate", tags=["affiliate"])
    logger.info("Affiliate router registered")
except Exception as e:
    logger.error(f"Error registering affiliate router: {e}")

# Creator Profiles router (social features)
try:
    api_router.include_router(creator_profiles.router, prefix="/creators", tags=["creator-profiles"])
    logger.info("Creator profiles router registered")
except Exception as e:
    logger.error(f"Error registering creator profiles router: {e}")

# Interactive Brokers router - Re-enabled after dependency fixes (July 27, 2025)
try:
    from app.api.v1.endpoints import interactivebrokers
    api_router.include_router(interactivebrokers.router, prefix="/brokers/interactivebrokers", tags=["interactivebrokers"])
    logger.info("Interactive Brokers router registered")
except Exception as e:
    logger.error(f"Error registering Interactive Brokers router: {e}")

# Define the callback route - Notice the change in the path
@tradovate_callback_router.get("/tradovate/callback")  # Changed from "/api/tradovate/callback"
async def tradovate_callback_handler(
    code: str,
    state: Optional[str] = None,
    db: Session = Depends(get_db)
):
    return await tradovate.tradovate_callback(code=code, state=state, db=db)