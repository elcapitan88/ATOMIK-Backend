# app/services/market_data_service.py
"""
Market Data Service for ARIA

Provides market data for ARIA queries:
- Stocks/ETFs: Uses yfinance (temporary, will migrate to Polygon via Data Hub)
- Futures: Uses atomik-data-hub which fetches from Databento

Data Sources:
- Stocks (AAPL, TSLA, SPY, etc.): yfinance → Yahoo Finance
- Futures (MNQ, ES, NQ, etc.): Data Hub → Databento

Created: 2024-11-25
Updated: 2025-12-09 - Added futures support via Databento/Data Hub
Author: Claude Code
"""

import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta, date
from functools import lru_cache
import asyncio
import httpx

from ..core.config import settings

logger = logging.getLogger(__name__)

# =============================================================================
# Futures Symbol Configuration
# =============================================================================

# Futures symbols supported via Databento (through atomik-data-hub)
FUTURES_SYMBOLS = {
    # E-mini contracts
    'ES',   # E-mini S&P 500
    'NQ',   # E-mini Nasdaq-100
    'RTY',  # E-mini Russell 2000
    'YM',   # E-mini Dow Jones

    # Micro contracts
    'MES',  # Micro E-mini S&P 500
    'MNQ',  # Micro E-mini Nasdaq-100
    'M2K',  # Micro E-mini Russell 2000
    'MYM',  # Micro E-mini Dow Jones

    # Commodities
    'CL',   # Crude Oil
    'GC',   # Gold
    'SI',   # Silver
    'NG',   # Natural Gas

    # Micro commodities
    'MCL',  # Micro Crude Oil
    'MGC',  # Micro Gold

    # Treasury futures
    'ZB',   # 30-Year Treasury Bond
    'ZN',   # 10-Year Treasury Note
    'ZF',   # 5-Year Treasury Note
    'ZT',   # 2-Year Treasury Note

    # Bitcoin futures
    'MBT',  # Micro Bitcoin (CME)
}

# Human-readable names for futures
FUTURES_NAMES = {
    'ES': 'E-mini S&P 500',
    'NQ': 'E-mini Nasdaq-100',
    'RTY': 'E-mini Russell 2000',
    'YM': 'E-mini Dow Jones',
    'MES': 'Micro E-mini S&P 500',
    'MNQ': 'Micro E-mini Nasdaq-100',
    'M2K': 'Micro E-mini Russell 2000',
    'MYM': 'Micro E-mini Dow Jones',
    'CL': 'Crude Oil',
    'GC': 'Gold',
    'SI': 'Silver',
    'NG': 'Natural Gas',
    'MCL': 'Micro Crude Oil',
    'MGC': 'Micro Gold',
    'ZB': '30-Year Treasury Bond',
    'ZN': '10-Year Treasury Note',
    'ZF': '5-Year Treasury Note',
    'ZT': '2-Year Treasury Note',
    'MBT': 'Micro Bitcoin',
}

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
    Market data service for ARIA queries.

    Routes requests to appropriate data sources:
    - Stocks/ETFs: yfinance (temporary)
    - Futures: atomik-data-hub → Databento

    Provides:
    - Real-time quotes (price, change, volume)
    - Historical data (OHLCV)
    - Basic company info (stocks only)
    """

    def __init__(self):
        """Initialize the market data service"""
        self._cache = {}  # Simple in-memory cache
        self._cache_ttl = 60  # Cache for 60 seconds
        self._data_hub_url = getattr(settings, 'ATOMIK_DATA_HUB_URL', 'http://localhost:8000')
        self._data_hub_api_key = getattr(settings, 'ATOMIK_DATA_HUB_API_KEY', None)
        self._http_client: Optional[httpx.AsyncClient] = None
        logger.info(f"MarketDataService initialized (stocks: yfinance, futures: Data Hub at {self._data_hub_url})")

    def is_futures_symbol(self, symbol: str) -> bool:
        """Check if symbol is a futures contract."""
        return symbol.upper() in FUTURES_SYMBOLS

    def get_futures_name(self, symbol: str) -> str:
        """Get human-readable name for a futures symbol."""
        return FUTURES_NAMES.get(symbol.upper(), symbol.upper())

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client for Data Hub requests."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=5.0),
                headers={"Content-Type": "application/json"}
            )
        return self._http_client

    # =========================================================================
    # Futures Data Methods (via Data Hub → Databento)
    # =========================================================================

    async def _get_futures_historical(
        self,
        symbol: str,
        bars: int = 300,
        interval: str = "1d"
    ) -> Dict[str, Any]:
        """
        Fetch historical futures data from Data Hub (Databento).

        Args:
            symbol: Futures symbol (e.g., MNQ, ES, NQ)
            bars: Number of bars to fetch
            interval: Bar interval (1m, 5m, 15m, 1h, 1d)

        Returns:
            Historical OHLCV data from Databento
        """
        try:
            client = await self._get_http_client()

            params = {
                "bars": bars,
                "interval": interval
            }
            if self._data_hub_api_key:
                params["api_key"] = self._data_hub_api_key

            url = f"{self._data_hub_url}/api/v1/historical/{symbol.upper()}"
            logger.info(f"Fetching futures data from Data Hub: {url}")

            response = await client.get(url, params=params)
            response.raise_for_status()

            data = response.json()
            logger.info(f"Successfully fetched {len(data.get('bars', []))} bars for {symbol} from Data Hub")

            return data

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error fetching futures data for {symbol}: {e.response.status_code} - {e.response.text}")
            return {
                "success": False,
                "error": f"Data Hub error: {e.response.status_code}",
                "data": None
            }
        except Exception as e:
            logger.error(f"Error fetching futures data for {symbol}: {e}")
            return {
                "success": False,
                "error": str(e),
                "data": None
            }

    async def _get_futures_quote(self, symbol: str) -> Dict[str, Any]:
        """
        Get current quote for a futures symbol by fetching recent historical data.

        Args:
            symbol: Futures symbol (e.g., MNQ, ES)

        Returns:
            Quote data derived from most recent bar
        """
        try:
            # Fetch recent 1-minute bars to get current price
            data = await self._get_futures_historical(symbol, bars=5, interval="1m")

            if not data.get("success", True) or not data.get("bars"):
                # Try daily bars as fallback
                data = await self._get_futures_historical(symbol, bars=2, interval="1d")

            if not data.get("bars"):
                return {
                    "success": False,
                    "error": f"No data available for futures symbol {symbol}",
                    "data": None
                }

            bars = data["bars"]
            latest_bar = bars[-1] if bars else None
            prev_bar = bars[-2] if len(bars) > 1 else None

            if not latest_bar:
                return {
                    "success": False,
                    "error": f"No recent data for {symbol}",
                    "data": None
                }

            # Calculate change from previous bar
            current_price = latest_bar.get("close", 0)
            prev_close = prev_bar.get("close", current_price) if prev_bar else current_price
            change = current_price - prev_close
            change_pct = (change / prev_close * 100) if prev_close else 0

            result = {
                "symbol": symbol.upper(),
                "name": self.get_futures_name(symbol),
                "price": round(current_price, 2),
                "change": round(change, 2),
                "change_percent": round(change_pct, 2),
                "volume": latest_bar.get("volume", 0),
                "day_high": round(latest_bar.get("high", 0), 2),
                "day_low": round(latest_bar.get("low", 0), 2),
                "open": round(latest_bar.get("open", 0), 2),
                "previous_close": round(prev_close, 2),
                "timestamp": latest_bar.get("timestamp", datetime.utcnow().isoformat()),
                "source": "databento",
                "asset_type": "futures"
            }

            # Cache the result
            cache_key = f"quote_{symbol}"
            self._set_cached(cache_key, result)

            return {
                "success": True,
                "data": result
            }

        except Exception as e:
            logger.error(f"Error fetching futures quote for {symbol}: {e}")
            return {
                "success": False,
                "error": str(e),
                "data": None
            }

    async def _get_futures_historical_summary(
        self,
        symbol: str,
        period: str = "1wk"
    ) -> Dict[str, Any]:
        """
        Get historical summary for futures (high, low, range, etc.)

        Args:
            symbol: Futures symbol
            period: Time period - 1d, 5d, 1wk, 1mo, 3mo

        Returns:
            Historical summary stats
        """
        try:
            # Map period to number of bars (daily)
            period_bars = {
                "1d": 1,
                "5d": 5,
                "1wk": 7,
                "1mo": 30,
                "3mo": 90
            }
            bars = period_bars.get(period, 7)

            data = await self._get_futures_historical(symbol, bars=bars, interval="1d")

            if not data.get("bars"):
                return {
                    "success": False,
                    "error": f"No historical data for futures symbol {symbol}",
                    "data": None
                }

            bars_data = data["bars"]

            # Calculate summary stats
            highs = [b.get("high", 0) for b in bars_data]
            lows = [b.get("low", 0) for b in bars_data]
            volumes = [b.get("volume", 0) for b in bars_data]

            high = max(highs) if highs else 0
            low = min(lows) if lows else 0
            range_val = high - low
            avg_volume = sum(volumes) / len(volumes) if volumes else 0

            first_bar = bars_data[0] if bars_data else {}
            last_bar = bars_data[-1] if bars_data else {}

            first_close = first_bar.get("close", 0)
            last_close = last_bar.get("close", 0)
            period_change = last_close - first_close
            period_change_pct = (period_change / first_close * 100) if first_close else 0

            result = {
                "symbol": symbol.upper(),
                "name": self.get_futures_name(symbol),
                "period": period,
                "high": round(high, 2),
                "low": round(low, 2),
                "range": round(range_val, 2),
                "open": round(first_bar.get("open", 0), 2),
                "close": round(last_close, 2),
                "period_change": round(period_change, 2),
                "period_change_percent": round(period_change_pct, 2),
                "avg_volume": int(avg_volume),
                "data_points": len(bars_data),
                "start_date": first_bar.get("timestamp", "")[:10] if first_bar.get("timestamp") else "",
                "end_date": last_bar.get("timestamp", "")[:10] if last_bar.get("timestamp") else "",
                "timestamp": datetime.utcnow().isoformat(),
                "source": "databento",
                "asset_type": "futures"
            }

            # Cache the result
            cache_key = f"hist_{symbol}_{period}"
            self._set_cached(cache_key, result, ttl=300)

            return {
                "success": True,
                "data": result
            }

        except Exception as e:
            logger.error(f"Error fetching futures historical for {symbol}: {e}")
            return {
                "success": False,
                "error": str(e),
                "data": None
            }

    async def _get_futures_specific_day(
        self,
        symbol: str,
        target_date: date
    ) -> Dict[str, Any]:
        """
        Get futures data for a specific date.

        Args:
            symbol: Futures symbol
            target_date: The specific date to fetch

        Returns:
            OHLCV data for that date
        """
        try:
            # Fetch enough bars to include the target date
            days_ago = (date.today() - target_date).days + 5
            data = await self._get_futures_historical(symbol, bars=days_ago, interval="1d")

            if not data.get("bars"):
                return {
                    "success": False,
                    "error": f"No data available for {symbol}",
                    "data": None
                }

            # Find the bar closest to target date
            target_str = target_date.isoformat()
            closest_bar = None
            min_diff = float('inf')

            for bar in data["bars"]:
                bar_date_str = bar.get("timestamp", "")[:10]
                if bar_date_str:
                    try:
                        bar_date = date.fromisoformat(bar_date_str)
                        diff = abs((bar_date - target_date).days)
                        if diff < min_diff:
                            min_diff = diff
                            closest_bar = bar
                            if diff == 0:
                                break  # Exact match
                    except ValueError:
                        continue

            if not closest_bar:
                return {
                    "success": False,
                    "error": f"No data found for {symbol} near {target_date}",
                    "data": None
                }

            actual_date = closest_bar.get("timestamp", "")[:10]

            result = {
                "symbol": symbol.upper(),
                "name": self.get_futures_name(symbol),
                "requested_date": target_str,
                "actual_date": actual_date,
                "open": round(closest_bar.get("open", 0), 2),
                "high": round(closest_bar.get("high", 0), 2),
                "low": round(closest_bar.get("low", 0), 2),
                "close": round(closest_bar.get("close", 0), 2),
                "volume": closest_bar.get("volume", 0),
                "timestamp": datetime.utcnow().isoformat(),
                "source": "databento",
                "asset_type": "futures",
                "note": f"Data for {actual_date}" + (
                    f" (closest to requested {target_str})" if actual_date != target_str else ""
                )
            }

            return {
                "success": True,
                "data": result
            }

        except Exception as e:
            logger.error(f"Error fetching specific day futures data for {symbol}: {e}")
            return {
                "success": False,
                "error": str(e),
                "data": None
            }

    # =========================================================================
    # Public API Methods (route to appropriate data source)
    # =========================================================================

    async def get_quote(self, symbol: str) -> Dict[str, Any]:
        """
        Get real-time quote for a symbol.

        Routes to appropriate data source:
        - Futures (MNQ, ES, NQ, etc.): Data Hub → Databento
        - Stocks/ETFs: yfinance

        Args:
            symbol: Symbol (e.g., AAPL, TSLA, SPY, MNQ, ES)

        Returns:
            Dict with price, change, volume, high, low, etc.
        """
        try:
            # Route futures to Data Hub (Databento)
            if self.is_futures_symbol(symbol):
                logger.info(f"Routing {symbol} to Data Hub (futures)")
                return await self._get_futures_quote(symbol)

            # Check cache first for stocks
            cache_key = f"quote_{symbol}"
            cached = self._get_cached(cache_key)
            if cached:
                return cached

            # Fetch stocks from yfinance (run in thread pool to not block)
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
        Get historical data for a symbol.

        Routes to appropriate data source:
        - Futures (MNQ, ES, NQ, etc.): Data Hub → Databento
        - Stocks/ETFs: yfinance

        Args:
            symbol: Symbol (e.g., AAPL, TSLA, SPY, MNQ, ES)
            period: Time period - 1d, 5d, 1wk, 1mo, 3mo, 6mo, 1y

        Returns:
            Dict with OHLCV data and summary stats
        """
        try:
            # Route futures to Data Hub (Databento)
            if self.is_futures_symbol(symbol):
                logger.info(f"Routing historical {symbol} to Data Hub (futures)")
                return await self._get_futures_historical_summary(symbol, period)

            # Check cache for stocks
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

    async def get_specific_day_data(
        self,
        symbol: str,
        day_name: str,
        modifier: str = "last"
    ) -> Dict[str, Any]:
        """
        Get OHLC data for a specific day of the week.

        Routes to appropriate data source:
        - Futures (MNQ, ES, NQ, etc.): Data Hub → Databento
        - Stocks/ETFs: yfinance

        Args:
            symbol: Symbol (e.g., AAPL, TSLA, SPY, MNQ, ES)
            day_name: Day of week (monday, tuesday, etc.)
            modifier: 'last' or 'this' (defaults to 'last')

        Returns:
            Dict with OHLC data for that specific day
        """
        try:
            from datetime import date
            import calendar

            # Calculate target date first (same logic for both futures and stocks)
            today = date.today()
            today_weekday = today.weekday()

            # Map day names to weekday numbers (0=Monday, 6=Sunday)
            days_map = {
                'monday': 0, 'tuesday': 1, 'wednesday': 2,
                'thursday': 3, 'friday': 4, 'saturday': 5, 'sunday': 6
            }

            target_weekday = days_map.get(day_name.lower(), 4)  # Default to Friday

            # Calculate days to go back
            if modifier == 'last':
                days_back = (today_weekday - target_weekday) % 7
                if days_back == 0:
                    days_back = 7  # If today is the target day, go back a week
            else:  # 'this' week
                days_back = (today_weekday - target_weekday) % 7

            target_date = today - timedelta(days=days_back)

            # Route futures to Data Hub (Databento)
            if self.is_futures_symbol(symbol):
                logger.info(f"Routing specific day {symbol} to Data Hub (futures)")
                return await self._get_futures_specific_day(symbol, target_date)

            yf = _get_yfinance()

            def fetch_specific_day():
                # target_date is already calculated above - use closure
                # Fetch data for that specific day (need to get a range and filter)
                # Get 2 weeks of data to ensure we have the target day
                start_date = target_date - timedelta(days=3)
                end_date = target_date + timedelta(days=1)

                ticker = yf.Ticker(symbol.upper())
                hist = ticker.history(start=start_date.isoformat(), end=end_date.isoformat())

                if hist.empty:
                    return None

                # Find the row closest to target_date
                # Convert index to date for comparison
                hist.index = hist.index.tz_localize(None)

                target_datetime = datetime.combine(target_date, datetime.min.time())

                # Find closest date (market might be closed on target day)
                closest_idx = None
                min_diff = float('inf')

                for idx in hist.index:
                    diff = abs((idx.date() - target_date).days)
                    if diff < min_diff:
                        min_diff = diff
                        closest_idx = idx

                if closest_idx is None:
                    return None

                row = hist.loc[closest_idx]
                actual_date = closest_idx.strftime("%Y-%m-%d")
                actual_day = closest_idx.strftime("%A")

                return {
                    "symbol": symbol.upper(),
                    "requested_day": day_name.capitalize(),
                    "actual_date": actual_date,
                    "actual_day": actual_day,
                    "open": round(row['Open'], 2),
                    "high": round(row['High'], 2),
                    "low": round(row['Low'], 2),
                    "close": round(row['Close'], 2),
                    "volume": int(row['Volume']),
                    "timestamp": datetime.utcnow().isoformat(),
                    "source": "yfinance",
                    "note": f"Data for {actual_day}, {actual_date}" + (
                        f" (closest to requested {day_name.capitalize()})" if actual_day.lower() != day_name.lower() else ""
                    )
                }

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, fetch_specific_day)

            if result is None:
                return {
                    "success": False,
                    "error": f"No data found for {symbol} on {modifier} {day_name}",
                    "data": None
                }

            return {
                "success": True,
                "data": result
            }

        except Exception as e:
            logger.error(f"Error fetching specific day data for {symbol}: {e}")
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

    async def get_fundamental_data(self, symbol: str) -> Dict[str, Any]:
        """
        Get fundamental/financial data for a stock.

        Args:
            symbol: Stock ticker symbol

        Returns:
            Dict with P/E, EPS, market cap, dividends, 52-week range, analyst data, etc.
        """
        try:
            cache_key = f"fundamentals_{symbol}"
            cached = self._get_cached(cache_key)
            if cached:
                return cached

            yf = _get_yfinance()

            def fetch_fundamentals():
                ticker = yf.Ticker(symbol.upper())
                info = ticker.info

                # Helper to safely get and round numbers
                def safe_get(key, decimals=2):
                    val = info.get(key)
                    if val is None:
                        return None
                    try:
                        return round(float(val), decimals)
                    except (TypeError, ValueError):
                        return val

                # Helper to format large numbers
                def format_large_num(val):
                    if val is None:
                        return None
                    if val >= 1_000_000_000_000:
                        return f"${val / 1_000_000_000_000:.2f}T"
                    elif val >= 1_000_000_000:
                        return f"${val / 1_000_000_000:.2f}B"
                    elif val >= 1_000_000:
                        return f"${val / 1_000_000:.2f}M"
                    else:
                        return f"${val:,.0f}"

                market_cap_raw = info.get('marketCap')
                revenue_raw = info.get('totalRevenue')

                return {
                    "symbol": symbol.upper(),
                    "name": info.get('shortName') or info.get('longName', 'Unknown'),

                    # Valuation metrics
                    "pe_ratio_trailing": safe_get('trailingPE'),
                    "pe_ratio_forward": safe_get('forwardPE'),
                    "peg_ratio": safe_get('pegRatio'),
                    "price_to_book": safe_get('priceToBook'),
                    "price_to_sales": safe_get('priceToSalesTrailing12Months'),

                    # Earnings
                    "eps_trailing": safe_get('trailingEps'),
                    "eps_forward": safe_get('forwardEps'),

                    # Market cap & enterprise value
                    "market_cap": market_cap_raw,
                    "market_cap_formatted": format_large_num(market_cap_raw),
                    "enterprise_value": info.get('enterpriseValue'),
                    "enterprise_value_formatted": format_large_num(info.get('enterpriseValue')),

                    # Revenue & profitability
                    "revenue": revenue_raw,
                    "revenue_formatted": format_large_num(revenue_raw),
                    "revenue_per_share": safe_get('revenuePerShare'),
                    "profit_margin": safe_get('profitMargins', 4),
                    "operating_margin": safe_get('operatingMargins', 4),
                    "gross_margin": safe_get('grossMargins', 4),
                    "ebitda": info.get('ebitda'),
                    "ebitda_formatted": format_large_num(info.get('ebitda')),

                    # Dividends
                    "dividend_yield": safe_get('dividendYield', 4),
                    "dividend_yield_percent": f"{(info.get('dividendYield') or 0) * 100:.2f}%" if info.get('dividendYield') else None,
                    "dividend_rate": safe_get('dividendRate'),
                    "payout_ratio": safe_get('payoutRatio', 4),
                    "ex_dividend_date": info.get('exDividendDate'),

                    # 52-week range
                    "fifty_two_week_high": safe_get('fiftyTwoWeekHigh'),
                    "fifty_two_week_low": safe_get('fiftyTwoWeekLow'),
                    "fifty_day_average": safe_get('fiftyDayAverage'),
                    "two_hundred_day_average": safe_get('twoHundredDayAverage'),

                    # Analyst data
                    "analyst_target_price": safe_get('targetMeanPrice'),
                    "analyst_target_high": safe_get('targetHighPrice'),
                    "analyst_target_low": safe_get('targetLowPrice'),
                    "analyst_recommendation": info.get('recommendationKey'),
                    "number_of_analysts": info.get('numberOfAnalystOpinions'),

                    # Shares & float
                    "shares_outstanding": info.get('sharesOutstanding'),
                    "float_shares": info.get('floatShares'),
                    "short_ratio": safe_get('shortRatio'),
                    "short_percent_of_float": safe_get('shortPercentOfFloat', 4),

                    # Beta & volatility
                    "beta": safe_get('beta'),

                    # Additional context
                    "sector": info.get('sector', 'N/A'),
                    "industry": info.get('industry', 'N/A'),

                    "timestamp": datetime.utcnow().isoformat(),
                    "source": "yfinance"
                }

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, fetch_fundamentals)

            # Cache fundamentals for 15 minutes (they don't change often)
            self._set_cached(cache_key, result, ttl=900)

            return {
                "success": True,
                "data": result
            }

        except Exception as e:
            logger.error(f"Error fetching fundamental data for {symbol}: {e}")
            return {
                "success": False,
                "error": str(e),
                "data": None
            }


# Global instance for easy access
# TEMPORARY: This will be removed when migrating to atomik-data-hub
market_data_service = MarketDataService()
