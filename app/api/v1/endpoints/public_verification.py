"""
Public Verification Endpoints - Phase 1.3 Trust Foundation

These endpoints are PUBLIC (no authentication required).
They provide cryptographic verification of strategy performance and integrity.

This is a core component of the trust infrastructure - these pages serve as
public trust artifacts that creators can share to prove their strategy's legitimacy.
"""
import logging
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel

from ....db.session import get_db
from ....models.strategy_code import StrategyCode
from ....models.trade import Trade, ExecutionEnvironment

router = APIRouter()
logger = logging.getLogger(__name__)


class PublicStrategyVerification(BaseModel):
    """Response model for public strategy verification."""
    # Strategy identification
    strategy_hash: str
    name: str
    version: int

    # Timestamps
    locked_at: str
    created_at: str

    # Live-only performance (verified trades only)
    performance: Dict[str, Any]

    # Version info
    parent_version_id: Optional[int]
    version_count: int

    # Verification badge info
    verification: Dict[str, Any]


class PublicTradeRecord(BaseModel):
    """Response model for public trade log entries."""
    id: int
    symbol: str
    side: str
    quantity: int
    entry_price: float
    exit_price: Optional[float]
    realized_pnl: Optional[float]
    status: str
    executed_at: str
    closed_at: Optional[str]


@router.get("/verify/{strategy_hash}", response_model=PublicStrategyVerification)
async def get_strategy_verification(
    strategy_hash: str,
    db: Session = Depends(get_db)
):
    """
    PUBLIC ENDPOINT - No authentication required.

    Get verification data for a strategy by its cryptographic hash.

    This endpoint returns:
    - Strategy identification (name, version, hash)
    - Lock timestamp (when strategy became immutable)
    - Live-only performance metrics (only verified live trades)
    - Version lineage information
    - Verification status badge

    Use this URL for public sharing and embedding.
    """
    try:
        # Find strategy by combined hash (must be locked)
        strategy = db.query(StrategyCode).filter(
            StrategyCode.combined_hash == strategy_hash,
            StrategyCode.locked_at.isnot(None)
        ).first()

        if not strategy:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "STRATEGY_NOT_FOUND",
                    "message": "No verified strategy found with this hash. The strategy may not exist or may not be published yet."
                }
            )

        # Count versions in lineage
        version_count = 1
        current = strategy
        while current.parent:
            version_count += 1
            current = current.parent

        # Also count children
        def count_children(s):
            count = 0
            for child in s.versions:
                count += 1 + count_children(child)
            return count
        version_count += count_children(strategy)

        return PublicStrategyVerification(
            strategy_hash=strategy.combined_hash,
            name=strategy.name,
            version=strategy.version,
            locked_at=strategy.locked_at.isoformat(),
            created_at=strategy.created_at.isoformat(),
            performance={
                "total_trades": strategy.live_total_trades,
                "winning_trades": strategy.live_winning_trades,
                "total_pnl": float(strategy.live_total_pnl) if strategy.live_total_pnl else 0,
                "win_rate": float(strategy.live_win_rate) if strategy.live_win_rate else 0,
                "first_trade": strategy.live_first_trade_at.isoformat() if strategy.live_first_trade_at else None,
                "last_trade": strategy.live_last_trade_at.isoformat() if strategy.live_last_trade_at else None,
                "is_live_verified": True  # All public metrics are live-only
            },
            parent_version_id=strategy.parent_strategy_id,
            version_count=version_count,
            verification={
                "is_immutable": True,
                "is_live_only": True,
                "hash_algorithm": "SHA-256",
                "platform": "Atomik",
                "verification_url": f"/verify/{strategy_hash}"
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting verification for hash {strategy_hash[:16]}...: {e}")
        raise HTTPException(status_code=500, detail="Error retrieving verification data")


@router.get("/verify/{strategy_hash}/trades", response_model=Dict[str, Any])
async def get_public_trade_log(
    strategy_hash: str,
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(50, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db)
):
    """
    PUBLIC ENDPOINT - No authentication required.

    Get the public trade log for a verified strategy.

    Returns only verified live trades (is_verified_live=True).
    The trade log is append-only and cannot be modified.

    Pagination:
    - page: Page number (starts at 1)
    - per_page: Items per page (max 100)
    """
    try:
        # Find strategy by hash
        strategy = db.query(StrategyCode).filter(
            StrategyCode.combined_hash == strategy_hash,
            StrategyCode.locked_at.isnot(None)
        ).first()

        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found or not published")

        # Query verified live trades for this strategy version
        query = db.query(Trade).filter(
            Trade.strategy_version_id == strategy.id,
            Trade.is_verified_live == True
        )

        # Get total count
        total = query.count()

        # Get paginated trades
        trades = query.order_by(Trade.open_time.desc()).offset(
            (page - 1) * per_page
        ).limit(per_page).all()

        return {
            "strategy_hash": strategy_hash,
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": (total + per_page - 1) // per_page,
            "trades": [
                {
                    "id": trade.id,
                    "symbol": trade.symbol,
                    "side": trade.side,
                    "quantity": trade.total_quantity,
                    "entry_price": float(trade.average_entry_price),
                    "exit_price": float(trade.exit_price) if trade.exit_price else None,
                    "realized_pnl": float(trade.realized_pnl) if trade.realized_pnl else None,
                    "status": trade.status,
                    "executed_at": trade.open_time.isoformat() if trade.open_time else None,
                    "closed_at": trade.close_time.isoformat() if trade.close_time else None,
                    "duration_seconds": trade.duration_seconds
                }
                for trade in trades
            ],
            "verification": {
                "all_trades_verified_live": True,
                "data_source": "broker_confirmed"
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting trade log for {strategy_hash[:16]}...: {e}")
        raise HTTPException(status_code=500, detail="Error retrieving trade log")


@router.get("/verify/{strategy_hash}/performance", response_model=Dict[str, Any])
async def get_detailed_performance(
    strategy_hash: str,
    db: Session = Depends(get_db)
):
    """
    PUBLIC ENDPOINT - No authentication required.

    Get detailed performance metrics for a verified strategy.

    All metrics are calculated from verified live trades only.
    Includes:
    - Win/loss statistics
    - P&L breakdown
    - Risk metrics (max drawdown, etc.)
    - Time-based analysis
    """
    try:
        # Find strategy by hash
        strategy = db.query(StrategyCode).filter(
            StrategyCode.combined_hash == strategy_hash,
            StrategyCode.locked_at.isnot(None)
        ).first()

        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found or not published")

        # Get all verified live trades for detailed analysis
        trades = db.query(Trade).filter(
            Trade.strategy_version_id == strategy.id,
            Trade.is_verified_live == True,
            Trade.status == "closed"
        ).all()

        if not trades:
            return {
                "strategy_hash": strategy_hash,
                "total_trades": 0,
                "message": "No closed trades yet",
                "performance": None
            }

        # Calculate detailed metrics
        total_trades = len(trades)
        winning_trades = [t for t in trades if t.realized_pnl and t.realized_pnl > 0]
        losing_trades = [t for t in trades if t.realized_pnl and t.realized_pnl < 0]

        total_pnl = sum(float(t.realized_pnl) for t in trades if t.realized_pnl)
        gross_profit = sum(float(t.realized_pnl) for t in winning_trades if t.realized_pnl)
        gross_loss = sum(float(t.realized_pnl) for t in losing_trades if t.realized_pnl)

        avg_win = gross_profit / len(winning_trades) if winning_trades else 0
        avg_loss = abs(gross_loss / len(losing_trades)) if losing_trades else 0

        # Calculate max drawdown from trade sequence
        cumulative_pnl = 0
        peak = 0
        max_drawdown = 0
        for trade in sorted(trades, key=lambda t: t.open_time):
            if trade.realized_pnl:
                cumulative_pnl += float(trade.realized_pnl)
                if cumulative_pnl > peak:
                    peak = cumulative_pnl
                drawdown = peak - cumulative_pnl
                if drawdown > max_drawdown:
                    max_drawdown = drawdown

        # Calculate average trade duration
        durations = [t.duration_seconds for t in trades if t.duration_seconds]
        avg_duration = sum(durations) / len(durations) if durations else 0

        return {
            "strategy_hash": strategy_hash,
            "total_trades": total_trades,
            "performance": {
                "summary": {
                    "total_pnl": round(total_pnl, 2),
                    "win_rate": round((len(winning_trades) / total_trades) * 100, 2) if total_trades > 0 else 0,
                    "profit_factor": round(gross_profit / abs(gross_loss), 2) if gross_loss != 0 else None,
                },
                "trades": {
                    "winning": len(winning_trades),
                    "losing": len(losing_trades),
                    "breakeven": total_trades - len(winning_trades) - len(losing_trades)
                },
                "pnl": {
                    "gross_profit": round(gross_profit, 2),
                    "gross_loss": round(gross_loss, 2),
                    "average_win": round(avg_win, 2),
                    "average_loss": round(avg_loss, 2),
                    "largest_win": round(max((float(t.realized_pnl) for t in winning_trades), default=0), 2),
                    "largest_loss": round(min((float(t.realized_pnl) for t in losing_trades), default=0), 2),
                },
                "risk": {
                    "max_drawdown": round(max_drawdown, 2),
                    "risk_reward_ratio": round(avg_win / avg_loss, 2) if avg_loss > 0 else None,
                },
                "time": {
                    "first_trade": min(t.open_time for t in trades).isoformat(),
                    "last_trade": max(t.close_time for t in trades if t.close_time).isoformat() if any(t.close_time for t in trades) else None,
                    "average_duration_seconds": round(avg_duration, 0),
                    "trading_days": len(set(t.open_time.date() for t in trades))
                }
            },
            "verification": {
                "all_metrics_from_live_trades": True,
                "calculation_method": "broker_confirmed_fills"
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting performance for {strategy_hash[:16]}...: {e}")
        raise HTTPException(status_code=500, detail="Error calculating performance metrics")


@router.get("/lookup")
async def lookup_strategy_by_hash(
    hash: str = Query(..., min_length=8, description="Full or partial strategy hash"),
    db: Session = Depends(get_db)
):
    """
    PUBLIC ENDPOINT - No authentication required.

    Look up a strategy by its hash (full or partial).

    Useful for verifying a hash copied from a creator's profile.
    Returns basic info and the full verification URL.
    """
    try:
        # Try exact match first
        strategy = db.query(StrategyCode).filter(
            StrategyCode.combined_hash == hash,
            StrategyCode.locked_at.isnot(None)
        ).first()

        # If no exact match, try prefix match
        if not strategy and len(hash) >= 8:
            strategy = db.query(StrategyCode).filter(
                StrategyCode.combined_hash.startswith(hash),
                StrategyCode.locked_at.isnot(None)
            ).first()

        if not strategy:
            return {
                "found": False,
                "message": "No verified strategy found with this hash",
                "searched_hash": hash
            }

        return {
            "found": True,
            "strategy": {
                "name": strategy.name,
                "version": strategy.version,
                "combined_hash": strategy.combined_hash,
                "short_hash": strategy.combined_hash[:8],
                "locked_at": strategy.locked_at.isoformat(),
                "live_total_trades": strategy.live_total_trades,
                "live_total_pnl": float(strategy.live_total_pnl) if strategy.live_total_pnl else 0
            },
            "verification_url": f"/api/v1/public/verify/{strategy.combined_hash}"
        }

    except Exception as e:
        logger.error(f"Error looking up hash {hash}: {e}")
        raise HTTPException(status_code=500, detail="Error looking up strategy")
