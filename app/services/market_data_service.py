# app/services/market_data_service.py
"""
TEMPORARY Market Data Service for ARIA using yfinance

This is a temporary implementation to enable ARIA market data queries.
It should be migrated to atomik-data-hub once the Data Hub's data sources
(Databento, Polygon) are properly configured.

TODO: Migration plan:
1. Configure Polygon API key in atomik-data-hub for stocks
2. Configure Databento for futures data
3. Update ARIA to call Data Hub endpoints instead of this service
4. Remove this file and yfinance dependency

Created: 2024-11-25
Author: Claude Code
Purpose: Enable ARIA to answer market data questions (price, range, etc.)
"""

import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from functools import lru_cache
import asyncio

logger = logging.getLogger(__name__)

# Lazy import yfinance to avoid startup issues if not installed
_yf = None

def _get_yfinance():
    """Lazy load yfinance module"""
    global _yf
    if _yf is None:
        try:
            import yfinance as yf
            _yf = yf
            logger.info("yfinance loaded successfully for market data")
        except ImportError:
            logger.error("yfinance not installed. Run: pip install yfinance")
            raise ImportError("yfinance is required for market data. Install with: pip install yfinance")
    return _yf


class MarketDataService:
    """
    TEMPORARY: Simple market data service using yfinance

    Provides:
    - Real-time quotes (price, change, volume)
    - Historical data (OHLCV)
    - Basic company info

    Note: This is meant for ARIA testing only. For production, use atomik-data-hub.
    """

    def __init__(self):
        """Initialize the market data service"""
        self._cache = {}  # Simple in-memory cache
        self._cache_ttl = 60  # Cache for 60 seconds
        logger.info("MarketDataService initialized (TEMPORARY - using yfinance)")

    async def get_quote(self, symbol: str) -> Dict[str, Any]:
        """
        Get real-time quote for a symbol

        Args:
            symbol: Stock/ETF symbol (e.g., AAPL, TSLA, SPY)

        Returns:
            Dict with price, change, volume, high, low, etc.
        """
        try:
            # Check cache first
            cache_key = f"quote_{symbol}"
            cached = self._get_cached(cache_key)
            if cached:
                return cached

            # Fetch from yfinance (run in thread pool to not block)
            yf = _get_yfinance()

            def fetch_quote():
                ticker = yf.Ticker(symbol.upper())
                info = ticker.fast_info

                # Get current price and change
                current_price = info.get('lastPrice') or info.get('regularMarketPrice', 0)
                prev_close = info.get('previousClose') or info.get('regularMarketPreviousClose', 0)

                change = current_price - prev_close if prev_close else 0
                change_pct = (change / prev_close * 100) if prev_close else 0

                return {
                    "symbol": symbol.upper(),
                    "price": round(current_price, 2),
                    "change": round(change, 2),
                    "change_percent": round(change_pct, 2),
                    "volume": info.get('lastVolume') or info.get('regularMarketVolume', 0),
                    "day_high": round(info.get('dayHigh') or info.get('regularMarketDayHigh', 0), 2),
                    "day_low": round(info.get('dayLow') or info.get('regularMarketDayLow', 0), 2),
                    "open": round(info.get('open') or info.get('regularMarketOpen', 0), 2),
                    "previous_close": round(prev_close, 2),
                    "market_cap": info.get('marketCap'),
                    "timestamp": datetime.utcnow().isoformat(),
                    "source": "yfinance"
                }

            # Run in executor to avoid blocking
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, fetch_quote)

            # Cache the result
            self._set_cached(cache_key, result)

            return {
                "success": True,
                "data": result
            }

        except Exception as e:
            logger.error(f"Error fetching quote for {symbol}: {e}")
            return {
                "success": False,
                "error": str(e),
                "data": None
            }

    async def get_historical(
        self,
        symbol: str,
        period: str = "1wk"
    ) -> Dict[str, Any]:
        """
        Get historical data for a symbol

        Args:
            symbol: Stock/ETF symbol
            period: Time period - 1d, 5d, 1wk, 1mo, 3mo, 6mo, 1y

        Returns:
            Dict with OHLCV data and summary stats
        """
        try:
            # Check cache
            cache_key = f"hist_{symbol}_{period}"
            cached = self._get_cached(cache_key)
            if cached:
                return cached

            yf = _get_yfinance()

            def fetch_historical():
                ticker = yf.Ticker(symbol.upper())
                hist = ticker.history(period=period)

                if hist.empty:
                    return None

                # Calculate summary stats
                high = hist['High'].max()
                low = hist['Low'].min()
                range_val = high - low
                avg_volume = hist['Volume'].mean()

                # Get first and last for period change
                first_close = hist['Close'].iloc[0]
                last_close = hist['Close'].iloc[-1]
                period_change = last_close - first_close
                period_change_pct = (period_change / first_close * 100) if first_close else 0

                return {
                    "symbol": symbol.upper(),
                    "period": period,
                    "high": round(high, 2),
                    "low": round(low, 2),
                    "range": round(range_val, 2),
                    "open": round(first_close, 2),
                    "close": round(last_close, 2),
                    "period_change": round(period_change, 2),
                    "period_change_percent": round(period_change_pct, 2),
                    "avg_volume": int(avg_volume),
                    "data_points": len(hist),
                    "start_date": hist.index[0].strftime("%Y-%m-%d"),
                    "end_date": hist.index[-1].strftime("%Y-%m-%d"),
                    "timestamp": datetime.utcnow().isoformat(),
                    "source": "yfinance"
                }

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, fetch_historical)

            if result is None:
                return {
                    "success": False,
                    "error": f"No historical data found for {symbol}",
                    "data": None
                }

            # Cache for longer (5 minutes for historical)
            self._set_cached(cache_key, result, ttl=300)

            return {
                "success": True,
                "data": result
            }

        except Exception as e:
            logger.error(f"Error fetching historical data for {symbol}: {e}")
            return {
                "success": False,
                "error": str(e),
                "data": None
            }

    async def get_company_info(self, symbol: str) -> Dict[str, Any]:
        """
        Get basic company information

        Args:
            symbol: Stock symbol

        Returns:
            Dict with company name, sector, industry, etc.
        """
        try:
            cache_key = f"info_{symbol}"
            cached = self._get_cached(cache_key)
            if cached:
                return cached

            yf = _get_yfinance()

            def fetch_info():
                ticker = yf.Ticker(symbol.upper())
                info = ticker.info

                return {
                    "symbol": symbol.upper(),
                    "name": info.get('shortName') or info.get('longName', 'Unknown'),
                    "sector": info.get('sector', 'N/A'),
                    "industry": info.get('industry', 'N/A'),
                    "exchange": info.get('exchange', 'N/A'),
                    "currency": info.get('currency', 'USD'),
                    "country": info.get('country', 'N/A'),
                    "website": info.get('website'),
                    "timestamp": datetime.utcnow().isoformat(),
                    "source": "yfinance"
                }

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, fetch_info)

            # Cache company info for 1 hour
            self._set_cached(cache_key, result, ttl=3600)

            return {
                "success": True,
                "data": result
            }

        except Exception as e:
            logger.error(f"Error fetching company info for {symbol}: {e}")
            return {
                "success": False,
                "error": str(e),
                "data": None
            }

    def _get_cached(self, key: str) -> Optional[Dict]:
        """Get value from cache if not expired"""
        if key in self._cache:
            data, expiry = self._cache[key]
            if datetime.utcnow() < expiry:
                logger.debug(f"Cache hit for {key}")
                return {"success": True, "data": data, "cached": True}
            else:
                del self._cache[key]
        return None

    def _set_cached(self, key: str, data: Dict, ttl: int = None):
        """Set value in cache with expiry"""
        ttl = ttl or self._cache_ttl
        expiry = datetime.utcnow() + timedelta(seconds=ttl)
        self._cache[key] = (data, expiry)
        logger.debug(f"Cached {key} for {ttl}s")

    def clear_cache(self):
        """Clear all cached data"""
        self._cache.clear()
        logger.info("Market data cache cleared")


# Global instance for easy access
# TEMPORARY: This will be removed when migrating to atomik-data-hub
market_data_service = MarketDataService()
