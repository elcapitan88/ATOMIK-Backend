# app/services/data_hub_client.py
"""
Data Hub Client for ARIA Integration
Connects directly to the Atomik Data Hub MCP Financial Server
"""

import httpx
import logging
from typing import Dict, Any, Optional, List
from tenacity import retry, stop_after_attempt, wait_exponential
from datetime import datetime
import json

from ..core.config import settings

logger = logging.getLogger(__name__)


class DataHubClient:
    """
    Client for interacting with Atomik Data Hub
    Provides market data, sentiment analysis, and economic indicators
    """

    def __init__(self):
        self.base_url = settings.ATOMIK_DATA_HUB_URL if hasattr(settings, 'ATOMIK_DATA_HUB_URL') else "http://localhost:8000"
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=5.0),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)
        )
        logger.info(f"DataHubClient initialized with base URL: {self.base_url}")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True
    )
    async def get_market_data(
        self,
        symbol: str,
        data_type: str = "quote"
    ) -> Dict[str, Any]:
        """
        Fetch real-time market data for a symbol

        Args:
            symbol: Trading symbol (e.g., "AAPL", "TSLA")
            data_type: Type of data - "quote", "historical", "volume_profile"

        Returns:
            Market data dictionary with price, volume, changes
        """
        try:
            logger.info(f"Fetching market data for {symbol} (type: {data_type})")

            response = await self.client.post(
                f"{self.base_url}/tools/get_market_data",
                json={
                    "symbol": symbol,
                    "data_type": data_type
                }
            )

            response.raise_for_status()
            data = response.json()

            # Log successful fetch
            if data.get("success"):
                logger.info(f"Successfully fetched {data_type} data for {symbol}")

            return data

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error fetching market data for {symbol}: {e}")
            # Return fallback data structure
            return {
                "success": False,
                "error": f"Failed to fetch market data: {str(e)}",
                "data": None
            }

        except Exception as e:
            logger.error(f"Unexpected error fetching market data for {symbol}: {e}")
            raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True
    )
    async def get_sentiment(
        self,
        symbol: str,
        timeframe: str = "1d"
    ) -> Dict[str, Any]:
        """
        Get market sentiment analysis for a symbol

        Args:
            symbol: Trading symbol
            timeframe: Time range - "1h", "1d", "7d", "30d"

        Returns:
            Sentiment data with scores and news analysis
        """
        try:
            logger.info(f"Fetching sentiment for {symbol} (timeframe: {timeframe})")

            response = await self.client.post(
                f"{self.base_url}/tools/get_market_sentiment",
                json={
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "include_social": False  # Can be made configurable
                }
            )

            response.raise_for_status()
            data = response.json()

            if data.get("success"):
                logger.info(f"Successfully fetched sentiment for {symbol}")

            return data

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error fetching sentiment for {symbol}: {e}")
            return {
                "success": False,
                "error": f"Failed to fetch sentiment: {str(e)}",
                "data": None
            }

        except Exception as e:
            logger.error(f"Unexpected error fetching sentiment for {symbol}: {e}")
            raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True
    )
    async def get_economic_data(
        self,
        series_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Fetch economic indicators from FRED

        Args:
            series_id: FRED series ID (e.g., "GDP", "UNRATE", "FEDFUNDS")
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format

        Returns:
            Economic data with time series values
        """
        try:
            logger.info(f"Fetching economic data for {series_id}")

            params = {"series_id": series_id}
            if start_date:
                params["start_date"] = start_date
            if end_date:
                params["end_date"] = end_date

            response = await self.client.post(
                f"{self.base_url}/tools/get_economic_data",
                json=params
            )

            response.raise_for_status()
            data = response.json()

            if data.get("success"):
                logger.info(f"Successfully fetched economic data for {series_id}")

            return data

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error fetching economic data: {e}")
            return {
                "success": False,
                "error": f"Failed to fetch economic data: {str(e)}",
                "data": None
            }

        except Exception as e:
            logger.error(f"Unexpected error fetching economic data: {e}")
            raise

    async def get_company_data(
        self,
        symbol: str,
        filing_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get company filings and SEC data

        Args:
            symbol: Company ticker symbol
            filing_type: Type of filing (e.g., "10-K", "10-Q")

        Returns:
            Company data including recent filings
        """
        try:
            logger.info(f"Fetching company data for {symbol}")

            params = {"symbol": symbol}
            if filing_type:
                params["filing_type"] = filing_type

            response = await self.client.post(
                f"{self.base_url}/tools/get_company_data",
                json=params
            )

            response.raise_for_status()
            return response.json()

        except Exception as e:
            logger.error(f"Error fetching company data for {symbol}: {e}")
            return {
                "success": False,
                "error": str(e),
                "data": None
            }

    async def get_news_summary(
        self,
        symbol: Optional[str] = None,
        limit: int = 10
    ) -> Dict[str, Any]:
        """
        Get recent news with sentiment scores

        Args:
            symbol: Optional symbol to filter news
            limit: Maximum number of articles

        Returns:
            News articles with sentiment analysis
        """
        try:
            logger.info(f"Fetching news summary for {symbol or 'market'}")

            params = {"limit": limit}
            if symbol:
                params["symbol"] = symbol

            response = await self.client.post(
                f"{self.base_url}/tools/get_news_summary",
                json=params
            )

            response.raise_for_status()
            return response.json()

        except Exception as e:
            logger.error(f"Error fetching news summary: {e}")
            return {
                "success": False,
                "error": str(e),
                "data": None
            }

    async def batch_fetch_market_data(
        self,
        symbols: List[str]
    ) -> Dict[str, Dict[str, Any]]:
        """
        Fetch market data for multiple symbols in parallel

        Args:
            symbols: List of trading symbols

        Returns:
            Dictionary mapping symbols to their market data
        """
        import asyncio

        tasks = [
            self.get_market_data(symbol)
            for symbol in symbols
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        return {
            symbol: result if not isinstance(result, Exception) else {
                "success": False,
                "error": str(result)
            }
            for symbol, result in zip(symbols, results)
        }

    async def get_comprehensive_analysis(
        self,
        symbol: str
    ) -> Dict[str, Any]:
        """
        Get comprehensive data for a symbol (price, sentiment, news)

        Args:
            symbol: Trading symbol

        Returns:
            Combined analysis with all available data
        """
        import asyncio

        try:
            # Fetch all data types in parallel
            market_task = self.get_market_data(symbol)
            sentiment_task = self.get_sentiment(symbol)
            news_task = self.get_news_summary(symbol, limit=5)

            market_data, sentiment_data, news_data = await asyncio.gather(
                market_task,
                sentiment_task,
                news_task,
                return_exceptions=True
            )

            # Process results
            analysis = {
                "symbol": symbol,
                "timestamp": datetime.utcnow().isoformat(),
                "success": True,
                "data": {
                    "market": market_data if not isinstance(market_data, Exception) else None,
                    "sentiment": sentiment_data if not isinstance(sentiment_data, Exception) else None,
                    "news": news_data if not isinstance(news_data, Exception) else None
                },
                "errors": []
            }

            # Track any errors
            if isinstance(market_data, Exception):
                analysis["errors"].append(f"Market data: {str(market_data)}")
            if isinstance(sentiment_data, Exception):
                analysis["errors"].append(f"Sentiment: {str(sentiment_data)}")
            if isinstance(news_data, Exception):
                analysis["errors"].append(f"News: {str(news_data)}")

            if analysis["errors"]:
                analysis["success"] = False

            return analysis

        except Exception as e:
            logger.error(f"Error in comprehensive analysis for {symbol}: {e}")
            return {
                "symbol": symbol,
                "success": False,
                "error": str(e),
                "data": None
            }

    async def close(self):
        """Close the HTTP client connection"""
        await self.client.aclose()

    async def __aenter__(self):
        """Async context manager entry"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()


# Helper functions for common queries
class DataHubQueries:
    """
    Pre-built queries for common ARIA use cases
    """

    @staticmethod
    def format_price_response(market_data: Dict[str, Any]) -> str:
        """Format market data for user-friendly price response"""
        if not market_data.get("success") or not market_data.get("data"):
            return "Unable to fetch current price data."

        data = market_data["data"]
        symbol = data.get("symbol", "Unknown")
        price = data.get("price", 0)
        change = data.get("change", 0)
        change_percent = data.get("change_percent", 0)

        direction = "📈" if change >= 0 else "📉"

        return f"{direction} {symbol} is at ${price:.2f}, {'+' if change >= 0 else ''}{change:.2f} ({change_percent:.2f}%) today"

    @staticmethod
    def format_sentiment_response(sentiment_data: Dict[str, Any]) -> str:
        """Format sentiment data for user-friendly response"""
        if not sentiment_data.get("success") or not sentiment_data.get("data"):
            return "Unable to analyze current market sentiment."

        data = sentiment_data["data"]
        overall = data.get("overall_sentiment", {})
        score = overall.get("score", 0)
        label = overall.get("label", "neutral")

        emoji_map = {
            "bullish": "🟢",
            "bearish": "🔴",
            "neutral": "⚪"
        }

        emoji = emoji_map.get(label.lower(), "⚪")

        return f"{emoji} Market sentiment is {label} (score: {score:.2f})"

    @staticmethod
    def should_fetch_data(query: str) -> Dict[str, bool]:
        """Determine what data types are needed based on query"""
        query_lower = query.lower()

        return {
            "market_data": any(word in query_lower for word in ["price", "cost", "worth", "trading", "quote"]),
            "sentiment": any(word in query_lower for word in ["sentiment", "feeling", "mood", "bullish", "bearish"]),
            "news": any(word in query_lower for word in ["news", "happening", "events", "announcement"]),
            "economic": any(word in query_lower for word in ["economy", "fed", "rates", "inflation", "gdp"])
        }