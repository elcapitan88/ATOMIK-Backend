# EDGAR Integration Plan: Data Hub → ARIA

**STATUS: IN PROGRESS** (2024-11-26)

**Last Updated**: 2024-11-26

## Progress Tracker

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 0 | ✅ COMPLETE | Fix Data Hub EDGAR XML Parsing |
| Phase 1 | ✅ COMPLETE | Data Hub HTTP Endpoints |
| Phase 2 | ✅ COMPLETE | FastAPI Backend Data Hub Client |
| Phase 3 | ✅ COMPLETE | ARIA Tool Definitions |
| Phase 4 | ⏳ PENDING | Testing & Deployment |

---

## Completed Work

### Phase 0 Completion (2024-11-26)

**Form 4 XML Parsing** - Real insider trading data from SEC Form 4 filings:
- Parses non-derivative and derivative transactions
- Extracts insider name, title, shares, price, transaction type
- Handles XSL prefix in document paths
- Uses correct SEC Archives URL (www.sec.gov vs data.sec.gov)
- Rate limited to respect SEC's 10 req/sec limit

**Institutional Holdings** - Using yfinance as data source:
- 13F filings are filed by institutions, not companies (complex to aggregate)
- yfinance provides clean institutional holder data
- Async-compatible using thread pool executor

**Filing Document Retrieval** - New method for AI analysis:
- `get_filing_document()` fetches raw HTML/text of any SEC filing
- Supports S-3, 424B5, 10-K, 8-K, and all other form types
- Cleans HTML (removes scripts, styles, excessive whitespace)
- Caches for 4 hours to avoid repeated SEC fetches
- Truncates to 100K characters to avoid token limits

**Form Types Expanded** - 60+ SEC form types including:
- Registration: S-1, S-3, S-4, S-8, F-1, F-3, F-4
- Prospectuses: 424B1-5, FWP
- Beneficial Ownership: SC 13D, SC 13G
- Tender Offers: SC TO-T, SC TO-I, SC 14D9
- And many more...

### Phase 1 Completion (2024-11-26)

**HTTP Endpoints Added** to `atomik-data-hub/src/mcp_financial_server/server.py`:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/edgar/filings` | GET | Get SEC filings for a company |
| `/api/edgar/insider-trading` | GET | Get insider trading from Form 4 |
| `/api/edgar/institutional-holdings` | GET | Get institutional holders |
| `/api/edgar/filing-document` | GET | Fetch raw filing content for AI analysis |

All endpoints support both `ticker` and `cik` parameters.

### Phase 2 Completion (2024-11-26)

**Data Hub Client Created**: `fastapi_backend/app/services/data_hub_service.py`

- HTTP client for atomik-data-hub using `httpx.AsyncClient`
- Methods: `get_sec_filings()`, `get_insider_trading()`, `get_institutional_holdings()`, `get_filing_document()`
- Uses `ATOMIK_DATA_HUB_URL` from settings (already configured)
- Lazy-loaded global instance for efficiency

### Phase 3 Completion (2024-11-26)

**ARIA Tool Definitions Added** to `fastapi_backend/app/services/aria_tools.py`:

| Tool | Description |
|------|-------------|
| `get_sec_filings` | Get SEC filings (10-K, 10-Q, 8-K, S-3, etc.) |
| `get_insider_trading` | Get insider trading activity (Form 4) |
| `get_institutional_holdings` | Get institutional ownership (13F) |
| `get_filing_document` | Fetch and analyze SEC filing content |

**Tool Handlers Implemented**:
- All four SEC/EDGAR tools have corresponding handler methods
- Data formatted for LLM consumption (concise, relevant fields only)
- Error handling with fallback messages

**System Prompt Updated**:
- Added SEC/EDGAR capabilities to ARIA's description
- Added examples for when to use each SEC tool
- Covers filings, insider trading, institutional holdings, and document analysis

## Overview

Integrate SEC EDGAR data from atomik-data-hub into ARIA's tool-calling architecture. This enables ARIA to answer questions like:
- "Show me Tesla's recent SEC filings"
- "What insider trading has happened at Apple recently?"
- "Who are the top institutional holders of NVDA?"
- "What's in TSLA's latest S-3 registration?" ← NEW!

---

## Architecture Principles

### 1. Separation of Concerns
Keep each data source in its own dedicated module/file:

```
atomik-data-hub/
└── tools/
    ├── edgar_data.py      # SEC EDGAR only
    ├── market_data.py     # Price/quote data only
    └── (future sources)   # Each in own file

fastapi_backend/
└── services/
    ├── data_hub_service.py     # HTTP client for Data Hub (all external calls)
    ├── market_data_service.py  # Local yfinance (temporary)
    ├── aria_tools.py           # Tool definitions + executor
    └── llm_service.py          # LLM provider logic
```

### 2. Single Responsibility
- **Data Hub**: Fetches and caches external data (SEC, future: news, etc.)
- **FastAPI Backend**: Business logic, user context, ARIA orchestration
- **ARIA Tools**: Tool definitions and lightweight result formatting

### 3. Clean Data Flow
```
User → ARIA → Tool Executor → DataHubService → Data Hub → External API
                                     ↑
                              One HTTP client
                              for all Data Hub calls
```

### 4. Organized Tool Structure
Group tools logically in `aria_tools.py`:
```python
ARIA_TOOLS = [
    # ----- Market Data Tools -----
    get_stock_quote,
    get_historical_data,
    get_fundamental_data,

    # ----- User Account Tools -----
    get_user_positions,
    get_active_strategies,
    get_trading_performance,

    # ----- SEC/EDGAR Tools -----
    get_sec_filings,
    get_insider_trading,
    get_institutional_holdings,

    # ----- Action Tools (require confirmation) -----
    activate_strategy,
    deactivate_strategy,
]
```

### 5. Consistent Response Format
All tools return consistent structure:
```python
{
    "success": True,
    "data": {...},           # Tool-specific data
    "source": "edgar|yfinance|cache",
    "timestamp": "ISO-8601"
}
```

---

## Current State

### Data Hub (`atomik-data-hub/src/mcp_financial_server/tools/edgar_data.py`)

| Feature | Status | Notes |
|---------|--------|-------|
| CIK Lookup | ✅ Working | `_get_cik_from_ticker()` - uses SEC JSON API |
| Company Info | ✅ Working | `_get_company_info()` - uses SEC JSON API |
| Company Filings | ✅ Working | `_get_recent_filings()` - uses SEC JSON API |
| Insider Trading | ❌ Mock Data | `_get_insider_transactions()` returns fake data |
| Institutional Holdings | ❌ Mock Data | `_get_institutional_holdings()` returns fake data |

### Problem

The insider trading and institutional holdings methods currently return mock data because they require parsing SEC EDGAR XML files (Form 4 for insider trading, 13F for institutional holdings).

---

## Phase 0: Fix Data Hub EDGAR XML Parsing

**Goal**: Replace mock data with real SEC data by implementing XML parsing.

### Phase 0a: Fix Form 4 XML Parsing (Insider Trading)

Form 4 filings contain insider transactions in XML format.

**Current Code** (`edgar_data.py` lines 414-428):
```python
async def _get_insider_transactions(self, cik: str, days_back: int, limit: int):
    # For now, return mock data as parsing Form 4 XML requires complex logic
    return self._generate_mock_insider_transactions(cik, days_back, limit)
```

**Implementation**:

1. Get recent Form 4 filings from company submissions JSON
2. Fetch each Form 4 XML document
3. Parse the XML structure to extract:
   - `ownerName` - Insider name
   - `ownerRelationship/officerTitle` - Title
   - `transactionDate` - Date of transaction
   - `transactionAmounts/transactionShares` - Number of shares
   - `transactionAmounts/transactionPricePerShare` - Price
   - `transactionCodes/transactionCode` - A (Acquisition) or D (Disposition)
   - `postTransactionAmounts/sharesOwnedFollowingTransaction` - Shares after

**Form 4 XML Structure**:
```xml
<ownershipDocument>
  <issuer>
    <issuerCik>0000320193</issuerCik>
    <issuerName>Apple Inc</issuerName>
    <issuerTradingSymbol>AAPL</issuerTradingSymbol>
  </issuer>
  <reportingOwner>
    <reportingOwnerId>
      <rptOwnerCik>0001214128</rptOwnerCik>
      <rptOwnerName>COOK TIMOTHY D</rptOwnerName>
    </reportingOwnerId>
    <reportingOwnerRelationship>
      <isOfficer>1</isOfficer>
      <officerTitle>Chief Executive Officer</officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionDate><value>2024-10-01</value></transactionDate>
      <transactionCoding>
        <transactionCode>S</transactionCode>
      </transactionCoding>
      <transactionAmounts>
        <transactionShares><value>50000</value></transactionShares>
        <transactionPricePerShare><value>227.55</value></transactionPricePerShare>
      </transactionAmounts>
      <postTransactionAmounts>
        <sharesOwnedFollowingTransaction><value>3280557</value></sharesOwnedFollowingTransaction>
      </postTransactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>
```

**New Method**:
```python
async def _get_insider_transactions(
    self,
    cik: str,
    days_back: int = 30,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """Get real insider trading transactions from Form 4 filings."""
    import xml.etree.ElementTree as ET

    transactions = []
    cik_padded = cik.zfill(10)

    # 1. Get recent Form 4 filings from submissions
    url = f"{self.edgar_base_url}/submissions/CIK{cik_padded}.json"
    response = await self.client.get(url)
    data = response.json()

    recent = data.get("filings", {}).get("recent", {})
    cutoff_date = date.today() - timedelta(days=days_back)

    # 2. Find Form 4 filings within date range
    for i, form in enumerate(recent.get("form", [])):
        if form != "4":
            continue

        filing_date_str = recent.get("filingDate", [])[i]
        filing_date = datetime.strptime(filing_date_str, "%Y-%m-%d").date()

        if filing_date < cutoff_date:
            break

        accession = recent.get("accessionNumber", [])[i].replace("-", "")
        primary_doc = recent.get("primaryDocument", [])[i]

        # 3. Fetch and parse Form 4 XML
        xml_url = f"{self.edgar_base_url}/Archives/edgar/data/{cik}/{accession}/{primary_doc}"
        xml_response = await self.client.get(xml_url)

        if xml_response.status_code == 200:
            parsed = self._parse_form4_xml(xml_response.text, filing_date_str)
            transactions.extend(parsed)

        if len(transactions) >= limit:
            break

    return transactions[:limit]

def _parse_form4_xml(self, xml_content: str, filing_date: str) -> List[Dict]:
    """Parse Form 4 XML and extract transactions."""
    import xml.etree.ElementTree as ET

    transactions = []
    try:
        root = ET.fromstring(xml_content)

        # Get issuer info
        issuer = root.find("issuer")
        ticker = issuer.findtext("issuerTradingSymbol") if issuer else None
        company = issuer.findtext("issuerName") if issuer else None
        cik = issuer.findtext("issuerCik") if issuer else None

        # Get owner info
        owner = root.find("reportingOwner")
        owner_name = owner.findtext("reportingOwnerId/rptOwnerName") if owner else "Unknown"
        owner_title = owner.findtext("reportingOwnerRelationship/officerTitle") if owner else None

        # Parse non-derivative transactions
        for txn in root.findall(".//nonDerivativeTransaction"):
            txn_date = txn.findtext("transactionDate/value")
            txn_code = txn.findtext("transactionCoding/transactionCode")
            shares = txn.findtext("transactionAmounts/transactionShares/value")
            price = txn.findtext("transactionAmounts/transactionPricePerShare/value")
            shares_after = txn.findtext("postTransactionAmounts/sharesOwnedFollowingTransaction/value")

            # Map transaction codes: S=Sale(D), P=Purchase(A), A=Grant(A), etc.
            txn_type = "D" if txn_code in ["S", "F"] else "A"

            try:
                shares_val = float(shares) if shares else 0
                price_val = float(price) if price else 0
                value = shares_val * price_val
            except (ValueError, TypeError):
                shares_val, price_val, value = 0, 0, 0

            transactions.append({
                "filing_date": filing_date,
                "transaction_date": txn_date,
                "company_name": company,
                "cik": cik,
                "ticker": ticker,
                "insider_name": owner_name,
                "insider_title": owner_title,
                "transaction_type": txn_type,
                "transaction_code": txn_code,
                "shares": int(shares_val),
                "price_per_share": round(price_val, 2),
                "transaction_value": round(value, 2),
                "shares_owned_after": int(float(shares_after)) if shares_after else None,
                "ownership_type": "D"
            })

    except ET.ParseError as e:
        logger.error(f"XML parse error: {e}")

    return transactions
```

### Phase 0b: Fix 13F XML Parsing (Institutional Holdings)

13F-HR filings contain institutional holdings data in XML format.

**Current Code** (`edgar_data.py` lines 430-444):
```python
async def _get_institutional_holdings(self, cik: str, quarter: Optional[str], limit: int):
    # For now, return mock data as parsing 13F XML requires complex logic
    return self._generate_mock_institutional_holdings(cik, quarter, limit)
```

**Challenge**: 13F filings are filed by the *institution*, not the company. So we need to:
1. Search for 13F filings that mention the target company's CUSIP
2. This requires a different approach - querying the SEC full-text search

**Alternative Approach**: Use SEC's company-centric 13F data
- The SEC provides aggregated institutional ownership through the submissions API
- We can also use third-party APIs or scrape from SEC's EDGAR full-text search

**Implementation**:

```python
async def _get_institutional_holdings(
    self,
    cik: str,
    quarter: Optional[str] = None,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """
    Get institutional holdings for a company.

    Note: This searches for 13F filings that include the company's stock.
    Since 13Fs are filed by institutions (not companies), this requires
    searching across many filings.
    """
    # For institutional holdings of a specific company, we need to:
    # 1. Get the company's CUSIP (9-character identifier)
    # 2. Search 13F filings for that CUSIP

    # Get company CUSIP from SEC
    cusip = await self._get_company_cusip(cik)
    if not cusip:
        logger.warning(f"Could not find CUSIP for CIK {cik}")
        return []

    holdings = []

    # Use SEC EDGAR full-text search to find 13F filings containing this CUSIP
    # Note: This is a simplified approach - production would use SEC's EFTS API
    search_url = f"https://efts.sec.gov/LATEST/search-index"
    params = {
        "q": f'"{cusip}"',
        "forms": "13F-HR",
        "dateRange": "custom",
        "startdt": (date.today() - timedelta(days=120)).isoformat(),
        "enddt": date.today().isoformat()
    }

    response = await self.client.get(search_url, params=params)
    if response.status_code != 200:
        return []

    results = response.json()

    for hit in results.get("hits", {}).get("hits", [])[:limit]:
        filing = hit.get("_source", {})

        # Parse the 13F XML to get exact holdings
        # ... (complex XML parsing similar to Form 4)

        holdings.append({
            "institution_name": filing.get("entity"),
            "institution_cik": filing.get("cik"),
            "filing_date": filing.get("filing_date"),
            # ... other fields from parsed XML
        })

    return holdings

async def _get_company_cusip(self, cik: str) -> Optional[str]:
    """Get company CUSIP from SEC or financial data provider."""
    # CUSIP can be found in company filings or from data providers
    # For now, this is a placeholder that would need implementation
    pass
```

**Note**: Getting institutional holdings for a specific company is complex because 13F filings are filed by institutions, not companies. Options:
1. **Build an index**: Periodically download and index all 13F filings
2. **Use SEC EFTS**: Full-text search API (limited functionality)
3. **Use third-party**: Financial data providers like Yahoo Finance, Alpha Vantage

**Recommended Approach for MVP**:
- Return the most recent Form 4 and 8-K filings as the "working" data
- Add a note that institutional holdings require additional data source
- OR integrate with yfinance's `institutional_holders` data

### Phase 0c: Test EDGAR Tools Locally

1. Run Data Hub locally: `cd atomik-data-hub && npm run dev`
2. Test insider trading with real data:
   ```bash
   curl "http://localhost:3000/api/edgar/insider-trading?ticker=AAPL"
   ```
3. Verify XML parsing returns real transaction data, not mock
4. Test edge cases: companies with no recent Form 4s, malformed XML

---

## Phase 1: Data Hub - Add HTTP Endpoints

**Goal**: Expose EDGAR tools via HTTP REST endpoints.

**File**: `atomik-data-hub/src/mcp_financial_server/server.py`

### Phase 1a: Add `/api/edgar/filings` endpoint

```python
@app.get("/api/edgar/filings")
async def get_company_filings(
    ticker: Optional[str] = None,
    cik: Optional[str] = None,
    form_type: Optional[str] = None,
    limit: int = 20
):
    """Get SEC filings for a company."""
    result = await edgar_data_tool.get_company_filings(
        ticker=ticker,
        cik=cik,
        form_type=form_type,
        limit=limit
    )
    return result
```

### Phase 1b: Add `/api/edgar/insider-trading` endpoint

```python
@app.get("/api/edgar/insider-trading")
async def get_insider_trading(
    ticker: Optional[str] = None,
    cik: Optional[str] = None,
    days_back: int = 30,
    limit: int = 50
):
    """Get insider trading activity for a company."""
    result = await edgar_data_tool.get_insider_trading(
        ticker=ticker,
        cik=cik,
        days_back=days_back,
        limit=limit
    )
    return result
```

### Phase 1c: Add `/api/edgar/institutional-holdings` endpoint

```python
@app.get("/api/edgar/institutional-holdings")
async def get_institutional_holdings(
    ticker: Optional[str] = None,
    cik: Optional[str] = None,
    quarter: Optional[str] = None,
    limit: int = 50
):
    """Get institutional holdings for a company."""
    result = await edgar_data_tool.get_institutional_holdings(
        ticker=ticker,
        cik=cik,
        quarter=quarter,
        limit=limit
    )
    return result
```

### Phase 1d: Test Locally

```bash
# Start Data Hub
cd atomik-data-hub
npm run dev

# Test endpoints
curl "http://localhost:3000/api/edgar/filings?ticker=TSLA&limit=5"
curl "http://localhost:3000/api/edgar/insider-trading?ticker=AAPL&days_back=30"
curl "http://localhost:3000/api/edgar/institutional-holdings?ticker=NVDA"
```

---

## Phase 2: FastAPI Backend - Create Data Hub Client

**Goal**: Create a service in fastapi_backend that calls Data Hub HTTP endpoints.

### Phase 2a: Create `data_hub_service.py`

**File**: `fastapi_backend/app/services/data_hub_service.py`

```python
"""
Data Hub Service - Client for atomik-data-hub MCP server

This service makes HTTP calls to the Data Hub to fetch:
- SEC EDGAR filings
- Insider trading data
- Institutional holdings
- (Future: other financial data)
"""

import logging
from typing import Dict, Any, Optional
import httpx
from ..core.config import settings

logger = logging.getLogger(__name__)


class DataHubService:
    """HTTP client for atomik-data-hub."""

    def __init__(self):
        self.base_url = getattr(settings, 'DATA_HUB_URL', 'http://localhost:3000')
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
        """Get SEC filings for a company."""
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
        """Get insider trading activity for a company."""
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
        """Get institutional holdings for a company."""
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

    async def close(self):
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None


# Global instance
data_hub_service = DataHubService()
```

### Phase 2b: Add Configuration

**File**: `fastapi_backend/app/core/config.py`

Add to Settings class:
```python
DATA_HUB_URL: str = "http://localhost:3000"  # Local dev
# Railway: https://atomik-data-hub-production.up.railway.app
```

**Environment Variable** (Railway):
```
DATA_HUB_URL=https://atomik-data-hub-production.up.railway.app
```

---

## Phase 3: ARIA Tools - Add SEC/EDGAR Tools

**Goal**: Add tool definitions so LLM can call SEC data functions.

### Phase 3a-3c: Add Tool Definitions

**File**: `fastapi_backend/app/services/aria_tools.py`

Add to `ARIA_TOOLS` list:

```python
# -------------------------------------------------------------------------
# SEC EDGAR Tools
# -------------------------------------------------------------------------
{
    "type": "function",
    "function": {
        "name": "get_sec_filings",
        "description": "Get SEC filings (10-K, 10-Q, 8-K, etc.) for a company. Use when user asks about SEC filings, annual reports, quarterly reports, or regulatory filings.",
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Stock ticker symbol (e.g., AAPL, TSLA)"
                },
                "form_type": {
                    "type": "string",
                    "description": "SEC form type to filter (e.g., 10-K, 10-Q, 8-K). Optional.",
                    "enum": ["10-K", "10-Q", "8-K", "DEF 14A", "4", "13F-HR"]
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of filings to return (default 10)",
                    "default": 10
                }
            },
            "required": ["symbol"]
        }
    }
},
{
    "type": "function",
    "function": {
        "name": "get_insider_trading",
        "description": "Get insider trading activity for a company (Form 4 filings). Use when user asks about insider buying, insider selling, executive stock transactions, or insider activity.",
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Stock ticker symbol"
                },
                "days_back": {
                    "type": "integer",
                    "description": "Number of days to look back (default 30)",
                    "default": 30
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of transactions (default 20)",
                    "default": 20
                }
            },
            "required": ["symbol"]
        }
    }
},
{
    "type": "function",
    "function": {
        "name": "get_institutional_holdings",
        "description": "Get institutional ownership data for a company (13F filings). Use when user asks about institutional holders, which funds own a stock, or institutional ownership.",
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Stock ticker symbol"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of holders to return (default 20)",
                    "default": 20
                }
            },
            "required": ["symbol"]
        }
    }
}
```

### Phase 3d: Add Tool Handlers

**File**: `fastapi_backend/app/services/aria_tools.py`

Add to `ARIAToolExecutor` class:

```python
from .data_hub_service import data_hub_service

class ARIAToolExecutor:
    def __init__(self, db, user_id: int):
        # ... existing init ...
        self.data_hub = data_hub_service

    async def execute(self, tool_name: str, arguments: Dict) -> Dict[str, Any]:
        handlers = {
            # ... existing handlers ...
            "get_sec_filings": self._get_sec_filings,
            "get_insider_trading": self._get_insider_trading,
            "get_institutional_holdings": self._get_institutional_holdings,
        }
        # ... rest of method ...

    # SEC/EDGAR Tool Handlers
    async def _get_sec_filings(
        self,
        symbol: str,
        form_type: Optional[str] = None,
        limit: int = 10
    ) -> Dict[str, Any]:
        """Get SEC filings for a company."""
        result = await self.data_hub.get_sec_filings(
            ticker=symbol,
            form_type=form_type,
            limit=limit
        )

        if not result.get("success"):
            return {"error": result.get("error", "Failed to fetch SEC filings")}

        data = result.get("data", {})
        filings = data.get("filings", [])

        return {
            "company": data.get("company_info", {}).get("company_name"),
            "ticker": symbol.upper(),
            "total_filings": len(filings),
            "filings": [
                {
                    "form": f.get("form_type"),
                    "filed": f.get("filing_date"),
                    "description": f.get("description")
                }
                for f in filings[:limit]
            ],
            "source": result.get("source", "edgar")
        }

    async def _get_insider_trading(
        self,
        symbol: str,
        days_back: int = 30,
        limit: int = 20
    ) -> Dict[str, Any]:
        """Get insider trading activity."""
        result = await self.data_hub.get_insider_trading(
            ticker=symbol,
            days_back=days_back,
            limit=limit
        )

        if not result.get("success"):
            return {"error": result.get("error", "Failed to fetch insider trading")}

        data = result.get("data", {})
        transactions = data.get("transactions", [])
        summary = data.get("summary", {})

        return {
            "company": data.get("company_info", {}).get("company_name"),
            "ticker": symbol.upper(),
            "period": f"Last {days_back} days",
            "summary": {
                "total_transactions": summary.get("total_transactions", 0),
                "net_activity": "Buying" if summary.get("net_activity", 0) > 0 else "Selling",
                "acquisitions": summary.get("acquisitions", 0),
                "dispositions": summary.get("dispositions", 0)
            },
            "recent_transactions": [
                {
                    "insider": t.get("insider_name"),
                    "title": t.get("insider_title"),
                    "type": "Buy" if t.get("transaction_type") == "A" else "Sell",
                    "shares": t.get("shares"),
                    "price": t.get("price_per_share"),
                    "value": t.get("transaction_value"),
                    "date": t.get("transaction_date")
                }
                for t in transactions[:10]
            ],
            "source": result.get("source", "edgar")
        }

    async def _get_institutional_holdings(
        self,
        symbol: str,
        limit: int = 20
    ) -> Dict[str, Any]:
        """Get institutional holdings."""
        result = await self.data_hub.get_institutional_holdings(
            ticker=symbol,
            limit=limit
        )

        if not result.get("success"):
            return {"error": result.get("error", "Failed to fetch institutional holdings")}

        data = result.get("data", {})
        holdings = data.get("holdings", [])
        summary = data.get("summary", {})

        return {
            "company": data.get("company_info", {}).get("company_name"),
            "ticker": symbol.upper(),
            "summary": {
                "total_institutions": summary.get("total_institutions", 0),
                "total_value": summary.get("total_value", 0),
                "top_holder": summary.get("top_holder", {}).get("name")
            },
            "top_holders": [
                {
                    "institution": h.get("institution_name"),
                    "shares": h.get("shares"),
                    "value": h.get("market_value"),
                    "percent": h.get("percent_of_class")
                }
                for h in holdings[:10]
            ],
            "source": result.get("source", "edgar")
        }
```

### Phase 3e: Update System Prompt

Add to `ARIA_TOOL_CALLING_SYSTEM_PROMPT`:

```python
7. **SEC filings** → Use get_sec_filings
   - "Show me Tesla's recent SEC filings"
   - "What 10-K reports has Apple filed?"
   - "Get NVDA's 8-K filings"

8. **Insider trading** → Use get_insider_trading
   - "Has anyone at Apple been buying stock?"
   - "Show me insider trading at Tesla"
   - "Are executives selling NVDA?"

9. **Institutional holdings** → Use get_institutional_holdings
   - "Who owns the most Apple stock?"
   - "What institutions hold Tesla?"
   - "Top institutional holders of NVDA"
```

---

## Phase 4: Testing & Deployment

### Phase 4a: Deploy Data Hub

1. Push changes to atomik-data-hub repository
2. Railway auto-deploys from main branch
3. Verify deployment: `https://atomik-data-hub-production.up.railway.app/health`

### Phase 4b: Update Railway Environment

Add environment variable to fastapi_backend service:
```
DATA_HUB_URL=https://atomik-data-hub-production.up.railway.app
```

### Phase 4c: Deploy FastAPI Backend

1. Push changes to fastapi_backend repository
2. Railway auto-deploys from main branch
3. Verify ARIA is working: test via frontend chat

### Phase 4d: End-to-End Testing

Test these queries in production:

1. **SEC Filings**:
   - "Show me Apple's recent SEC filings"
   - "What 10-Q reports has Tesla filed?"

2. **Insider Trading**:
   - "Has anyone at NVDA been buying stock lately?"
   - "Show me insider trading at Microsoft"

3. **Institutional Holdings**:
   - "Who are the top institutional holders of AAPL?"
   - "What funds own Tesla stock?"

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                          User Query                              │
│              "Show me Tesla's recent insider trading"            │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                      FastAPI Backend                             │
│  ┌─────────────────┐    ┌──────────────────┐                    │
│  │  ARIA Assistant │───▶│   LLM Service    │                    │
│  │                 │    │  (Groq/Claude)   │                    │
│  └─────────────────┘    └──────────────────┘                    │
│           │                      │                               │
│           │              Tool Call: get_insider_trading          │
│           ▼                      ▼                               │
│  ┌─────────────────┐    ┌──────────────────┐                    │
│  │ ARIAToolExecutor│───▶│ DataHubService   │                    │
│  │                 │    │   (HTTP Client)  │                    │
│  └─────────────────┘    └──────────────────┘                    │
└─────────────────────────────────────────────────────────────────┘
                                │
                         HTTP Request
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Atomik Data Hub                             │
│  ┌─────────────────┐    ┌──────────────────┐                    │
│  │   HTTP Server   │───▶│  EDGARDataTool   │                    │
│  │  (Express/Fast) │    │                  │                    │
│  └─────────────────┘    └──────────────────┘                    │
│                                │                                 │
│                          SEC API Call                            │
│                                ▼                                 │
│                    ┌──────────────────┐                         │
│                    │   SEC EDGAR API   │                         │
│                    │  data.sec.gov     │                         │
│                    └──────────────────┘                         │
└─────────────────────────────────────────────────────────────────┘
```

---

## Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `atomik-data-hub/.../edgar_data.py` | MODIFY | Fix XML parsing for Form 4 and 13F |
| `atomik-data-hub/.../server.py` | MODIFY | Add HTTP endpoints |
| `fastapi_backend/.../data_hub_service.py` | CREATE | HTTP client for Data Hub |
| `fastapi_backend/.../config.py` | MODIFY | Add DATA_HUB_URL setting |
| `fastapi_backend/.../aria_tools.py` | MODIFY | Add SEC tool definitions |

---

## Questions/Decisions

1. **Institutional Holdings Complexity**: 13F parsing is complex. Options:
   - A) Implement full 13F search (complex, most accurate)
   - B) Use yfinance `institutional_holders` as fallback (simpler)
   - C) Mark as "coming soon" and focus on filings + insider trading

2. **Rate Limiting**: SEC allows 10 req/sec. Should we add:
   - Client-side rate limiting in data_hub_service.py?
   - Or rely on Data Hub's existing rate limiter?

3. **Caching Strategy**:
   - Data Hub caches for 30min-4hr
   - Should FastAPI also cache, or rely on Data Hub?

---

## Estimated Effort

| Phase | Effort | Notes |
|-------|--------|-------|
| Phase 0 (XML Parsing) | 4-6 hours | Form 4 parsing, 13F simpler approach |
| Phase 1 (HTTP Endpoints) | 1-2 hours | Simple endpoint additions |
| Phase 2 (DataHubService) | 2-3 hours | HTTP client with error handling |
| Phase 3 (ARIA Tools) | 2-3 hours | Tool definitions and handlers |
| Phase 4 (Deploy & Test) | 2-3 hours | Railway deployment, E2E testing |
| **Total** | **11-17 hours** | |

🤖 Generated with [Claude Code](https://claude.com/claude-code)
