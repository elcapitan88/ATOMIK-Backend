"""
Data Hub Service - Client for atomik-data-hub MCP server

This service makes HTTP calls to the Data Hub to fetch:
- SEC EDGAR filings
- Insider trading data
- Institutional holdings
- Filing document content for AI analysis
- FRED economic data (Federal Reserve Economic Data)
"""

import logging
from typing import Dict, Any, Optional
import httpx
from ..core.config import settings

logger = logging.getLogger(__name__)


class DataHubService:
    """HTTP client for atomik-data-hub."""

    def __init__(self):
        self.base_url = settings.ATOMIK_DATA_HUB_URL
        self.timeout = 30.0
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                headers={"Content-Type": "application/json"}
            )
        return self._client

    async def get_sec_filings(
        self,
        ticker: Optional[str] = None,
        cik: Optional[str] = None,
        form_type: Optional[str] = None,
        limit: int = 20
    ) -> Dict[str, Any]:
        """
        Get SEC filings for a company.

        Args:
            ticker: Stock ticker symbol (e.g., AAPL, TSLA)
            cik: SEC Central Index Key
            form_type: SEC form type filter (e.g., 10-K, 10-Q, 8-K, S-3)
            limit: Maximum number of filings to return

        Returns:
            SEC filings data with company info and filing list
        """
        try:
            client = await self._get_client()

            params = {"limit": limit}
            if ticker:
                params["ticker"] = ticker
            if cik:
                params["cik"] = cik
            if form_type:
                params["form_type"] = form_type

            response = await client.get("/api/edgar/filings", params=params)
            response.raise_for_status()

            return response.json()

        except Exception as e:
            logger.error(f"Error fetching SEC filings: {e}")
            return {
                "success": False,
                "error": str(e),
                "data": None
            }

    async def get_insider_trading(
        self,
        ticker: Optional[str] = None,
        cik: Optional[str] = None,
        days_back: int = 30,
        limit: int = 50
    ) -> Dict[str, Any]:
        """
        Get insider trading activity for a company.

        Args:
            ticker: Stock ticker symbol
            cik: SEC Central Index Key
            days_back: Number of days to look back
            limit: Maximum number of transactions

        Returns:
            Insider trading data with transactions and summary
        """
        try:
            client = await self._get_client()

            params = {"days_back": days_back, "limit": limit}
            if ticker:
                params["ticker"] = ticker
            if cik:
                params["cik"] = cik

            response = await client.get("/api/edgar/insider-trading", params=params)
            response.raise_for_status()

            return response.json()

        except Exception as e:
            logger.error(f"Error fetching insider trading: {e}")
            return {
                "success": False,
                "error": str(e),
                "data": None
            }

    async def get_institutional_holdings(
        self,
        ticker: Optional[str] = None,
        cik: Optional[str] = None,
        quarter: Optional[str] = None,
        limit: int = 50
    ) -> Dict[str, Any]:
        """
        Get institutional holdings for a company.

        Args:
            ticker: Stock ticker symbol
            cik: SEC Central Index Key
            quarter: Quarter filter (e.g., 2024-Q1)
            limit: Maximum number of holders

        Returns:
            Institutional holdings data with holders list and summary
        """
        try:
            client = await self._get_client()

            params = {"limit": limit}
            if ticker:
                params["ticker"] = ticker
            if cik:
                params["cik"] = cik
            if quarter:
                params["quarter"] = quarter

            response = await client.get("/api/edgar/institutional-holdings", params=params)
            response.raise_for_status()

            return response.json()

        except Exception as e:
            logger.error(f"Error fetching institutional holdings: {e}")
            return {
                "success": False,
                "error": str(e),
                "data": None
            }

    async def get_filing_document(
        self,
        ticker: Optional[str] = None,
        cik: Optional[str] = None,
        accession_number: Optional[str] = None,
        form_type: Optional[str] = None,
        document_type: str = "primary"
    ) -> Dict[str, Any]:
        """
        Fetch the raw content of an SEC filing document.

        Retrieves the actual document content (HTML/text) for AI analysis.
        Results are cached in Data Hub for 4 hours.

        Args:
            ticker: Stock ticker symbol
            cik: SEC Central Index Key
            accession_number: Specific filing accession number
            form_type: Form type to find (e.g., S-3, 424B5, 10-K)
            document_type: "primary" for main document, "full" for full submission

        Returns:
            Filing document content and metadata
        """
        try:
            client = await self._get_client()

            params = {"document_type": document_type}
            if ticker:
                params["ticker"] = ticker
            if cik:
                params["cik"] = cik
            if accession_number:
                params["accession_number"] = accession_number
            if form_type:
                params["form_type"] = form_type

            response = await client.get("/api/edgar/filing-document", params=params)
            response.raise_for_status()

            return response.json()

        except Exception as e:
            logger.error(f"Error fetching filing document: {e}")
            return {
                "success": False,
                "error": str(e),
                "data": None
            }

    # ==================== FRED Economic Data Methods ====================

    async def get_fred_series(
        self,
        series_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 100
    ) -> Dict[str, Any]:
        """
        Get FRED economic data series.

        Args:
            series_id: FRED series ID (e.g., GDP, UNRATE, CPIAUCSL, FEDFUNDS)
            start_date: Start date (YYYY-MM-DD format)
            end_date: End date (YYYY-MM-DD format)
            limit: Maximum number of observations

        Returns:
            Series data with observations and metadata
        """
        try:
            client = await self._get_client()

            params = {"series_id": series_id, "limit": limit}
            if start_date:
                params["start_date"] = start_date
            if end_date:
                params["end_date"] = end_date

            response = await client.get("/api/fred/series", params=params)
            response.raise_for_status()

            return response.json()

        except Exception as e:
            logger.error(f"Error fetching FRED series {series_id}: {e}")
            return {
                "success": False,
                "error": str(e),
                "data": None
            }

    async def get_interest_rates(self) -> Dict[str, Any]:
        """
        Get current interest rates from FRED.

        Returns curated interest rate data including:
        - Federal Funds Rate
        - Treasury yields (2Y, 5Y, 10Y, 30Y)
        - Mortgage rates
        - Prime rate
        """
        try:
            client = await self._get_client()

            response = await client.get("/api/fred/interest-rates")
            response.raise_for_status()

            return response.json()

        except Exception as e:
            logger.error(f"Error fetching interest rates: {e}")
            return {
                "success": False,
                "error": str(e),
                "data": None
            }

    async def get_economic_snapshot(self) -> Dict[str, Any]:
        """
        Get economic conditions snapshot from FRED.

        Returns key economic indicators:
        - GDP and growth rate
        - Unemployment rate
        - Inflation (CPI, PCE)
        - Consumer sentiment
        - Housing starts
        """
        try:
            client = await self._get_client()

            response = await client.get("/api/fred/snapshot")
            response.raise_for_status()

            return response.json()

        except Exception as e:
            logger.error(f"Error fetching economic snapshot: {e}")
            return {
                "success": False,
                "error": str(e),
                "data": None
            }

    async def get_economic_calendar(self) -> Dict[str, Any]:
        """
        Get upcoming economic data releases.

        Returns calendar of scheduled releases for major indicators.
        """
        try:
            client = await self._get_client()

            response = await client.get("/api/fred/calendar")
            response.raise_for_status()

            return response.json()

        except Exception as e:
            logger.error(f"Error fetching economic calendar: {e}")
            return {
                "success": False,
                "error": str(e),
                "data": None
            }

    async def search_fred_series(
        self,
        query: str,
        limit: int = 20
    ) -> Dict[str, Any]:
        """
        Search for FRED series by keyword.

        Args:
            query: Search term (e.g., 'unemployment', 'inflation', 'housing')
            limit: Maximum number of results

        Returns:
            List of matching series with metadata
        """
        try:
            client = await self._get_client()

            params = {"query": query, "limit": limit}

            response = await client.get("/api/fred/search", params=params)
            response.raise_for_status()

            return response.json()

        except Exception as e:
            logger.error(f"Error searching FRED series for '{query}': {e}")
            return {
                "success": False,
                "error": str(e),
                "data": None
            }

    async def close(self):
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None


# Global instance
data_hub_service = DataHubService()
