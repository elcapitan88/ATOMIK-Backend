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

    async def get_specific_day_data(
        self,
        symbol: str,
        day_name: str,
        modifier: str = "last"
    ) -> Dict[str, Any]:
        """
        Get OHLC data for a specific day of the week.

        Args:
            symbol: Stock/ETF symbol
            day_name: Day of week (monday, tuesday, etc.)
            modifier: 'last' or 'this' (defaults to 'last')

        Returns:
            Dict with OHLC data for that specific day
        """
        try:
            from datetime import date
            import calendar

            yf = _get_yfinance()

            def fetch_specific_day():
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
                    # Go back to the most recent occurrence
                    days_back = (today_weekday - target_weekday) % 7
                    if days_back == 0:
                        days_back = 7  # If today is the target day, go back a week
                else:  # 'this' week
                    days_back = (today_weekday - target_weekday) % 7

                target_date = today - timedelta(days=days_back)

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
