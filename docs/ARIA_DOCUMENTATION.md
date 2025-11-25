# ARIA - Atomik Real-time Intelligent Assistant

## Documentation Version
- **Last Updated**: 2025-11-25
- **Status**: Active Development
- **Environment**: FastAPI Backend on Railway + React Frontend

---

## Table of Contents
1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Core Components](#core-components)
4. [Frontend Components](#frontend-components)
5. [Request Flow](#request-flow)
6. [Dual LLM Model System](#dual-llm-model-system)
7. [Intent Recognition](#intent-recognition)
8. [Market Data Integration](#market-data-integration)
9. [API Endpoints](#api-endpoints)
10. [Configuration](#configuration)
11. [Database Models](#database-models)
12. [Testing](#testing)
13. [Migration Notes](#migration-notes)

---

## Overview

ARIA (Atomik Real-time Intelligent Assistant) is the AI-powered assistant integrated into the Atomik Trading platform. It provides:

- **Natural Language Processing**: Understanding user queries about trading, accounts, and market data
- **Intent Recognition**: Pattern-based and AI-powered intent classification
- **Market Data Queries**: Real-time price and historical data lookups
- **Trading Context**: Account and strategy information retrieval
- **Dual LLM Support**: Economy (Groq) and Premium (Anthropic) model tiers

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Frontend (React)                         │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  UI Components                                             │  │
│  │  ├── ARIAAssistant.jsx (Floating pill + expanded chat)    │  │
│  │  ├── ARIAAssistant.css (Glassmorphism styles)             │  │
│  │  └── Chatbox.js (Slide-in panel - Chakra UI)              │  │
│  └───────────────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Services                                                  │  │
│  │  └── ariaApi.js (API client + helpers + events)           │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────┬───────────────────────────────────┘
                              │ HTTP POST /api/v1/aria/chat
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     FastAPI Backend                             │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                   aria.py (Router)                        │  │
│  │              POST /chat, GET /health                      │  │
│  └─────────────────────────┬────────────────────────────────┘  │
│                            │                                    │
│  ┌─────────────────────────▼────────────────────────────────┐  │
│  │                ARIAAssistant                              │  │
│  │         (Main orchestrator - aria_assistant.py)           │  │
│  └──┬──────────┬──────────┬──────────┬──────────┬──────────┘  │
│     │          │          │          │          │              │
│     ▼          ▼          ▼          ▼          ▼              │
│  ┌──────┐  ┌──────┐  ┌──────┐  ┌──────┐  ┌──────────────┐     │
│  │Intent│  │Context│ │Action│  │ LLM  │  │ Market Data  │     │
│  │Service│ │Engine │ │Exec  │  │Service│ │ Service      │     │
│  └──────┘  └──────┘  └──────┘  └──────┘  └──────────────┘     │
│                                    │              │             │
│                              ┌─────┴─────┐   ┌───┴────┐        │
│                              │   Groq    │   │yfinance│        │
│                              │(Economy)  │   │ (TEMP) │        │
│                              └───────────┘   └────────┘        │
│                              ┌───────────┐                      │
│                              │ Anthropic │                      │
│                              │ (Premium) │                      │
│                              └───────────┘                      │
└─────────────────────────────────────────────────────────────────┘
```

---

## Core Components

### 1. ARIAAssistant (`aria_assistant.py`)

The main orchestrator that:
- Receives user queries
- Coordinates intent recognition
- Routes to appropriate handlers
- Generates responses

```python
class ARIAAssistant:
    def __init__(self, db: Session, user_id: int, context_engine, action_executor):
        self.intent_service = IntentService()
        self.llm_service = LLMService()
        self.market_data_service = MarketDataService()

    async def process_query(self, query: str) -> Dict[str, Any]:
        # 1. Recognize intent
        # 2. Route to handler
        # 3. Generate response
```

### 2. IntentService (`intent_service.py`)

Classifies user queries into actionable intents using:
- **Pattern matching**: Regex patterns for common queries
- **AI fallback**: LLM classification for complex queries

**Supported Intent Types:**
```python
# Trading Intents
ACCOUNT_QUERY = "account_query"
STRATEGY_QUERY = "strategy_query"
POSITION_QUERY = "position_query"
TRADE_ACTION = "trade_action"

# Market Data Intents (TEMPORARY)
MARKET_PRICE_QUERY = "market_price_query"
MARKET_HISTORICAL_QUERY = "market_historical_query"

# General
HELP_QUERY = "help_query"
GREETING = "greeting"
UNKNOWN = "unknown"
```

### 3. LLMService (`llm_service.py`)

Manages AI model interactions with dual-provider support:

```python
class LLMService:
    def __init__(self):
        self.provider = settings.LLM_PROVIDER  # "groq" or "anthropic"

    async def generate_response(self, prompt, context, complexity):
        if self.provider == "groq":
            return await self._call_groq(prompt, context)
        elif self.provider == "anthropic":
            return await self._call_anthropic(prompt, context)
```

### 4. MarketDataService (`market_data_service.py`)

**TEMPORARY IMPLEMENTATION** using yfinance for market data:

```python
class MarketDataService:
    async def get_quote(self, symbol: str) -> Dict[str, Any]
    async def get_historical(self, symbol: str, period: str) -> Dict[str, Any]
    async def get_company_info(self, symbol: str) -> Dict[str, Any]
```

> **Note**: This will be migrated to atomik-data-hub once Databento/Polygon data sources are configured.

### 5. ContextEngine (`context_engine.py`)

Manages conversation context and user state:
- Redis caching for session data
- Conversation history tracking
- User preference storage

### 6. ActionExecutor (`action_executor.py`)

Executes trading-related actions:
- Account operations
- Strategy management
- Position queries

---

## Frontend Components

The ARIA frontend provides a complete chat interface with voice support, built with React.

### 1. ARIAAssistant (`components/ARIA/ARIAAssistant.jsx`)

A standalone floating chat interface with:

**States:**
- **Collapsed**: Floating pill at top of screen with "Ask ARIA..." prompt
- **Expanded**: Full chat interface with message history
- **Hidden**: Minimized to restore button in corner

**Features:**
- Voice input via Web Speech API (`webkitSpeechRecognition`)
- Text-to-speech for ARIA responses (`speechSynthesis`)
- Auto-scroll chat history
- Example command quick tips
- Confirmation workflow for actions
- Loading/typing indicators
- Error state handling

```jsx
// Key state management
const [isExpanded, setIsExpanded] = useState(false);
const [isListening, setIsListening] = useState(false);
const [chatHistory, setChatHistory] = useState([...]);
const [pendingConfirmation, setPendingConfirmation] = useState(null);
```

### 2. Chatbox (`components/Chatbox.js`)

An alternative slide-in panel chat interface using Chakra UI:

**Features:**
- Slide-in from right with backdrop overlay
- Framer Motion animations
- TypeWriter effect for AI responses
- Code block rendering with syntax highlighting
- Confirmation buttons for action verification
- Action result badges

```jsx
// Chakra UI + Framer Motion
<MotionBox
  position="fixed"
  initial={{ x: "100%" }}
  animate={{ x: 0 }}
  exit={{ x: "100%" }}
  transition={{ type: "spring", damping: 25, stiffness: 200 }}
>
```

### 3. ariaApi (`services/api/ariaApi.js`)

Complete API service for ARIA backend communication:

**Core Methods:**
```javascript
ariaApi.sendMessage(message, inputType, context)  // Send chat message
ariaApi.sendVoiceCommand(command)                 // Voice-optimized endpoint
ariaApi.sendConfirmation(interactionId, confirmed) // Confirm/cancel actions
ariaApi.getUserContext()                          // Get trading context
ariaApi.getExamples()                             // Get example commands
ariaApi.getHealthStatus()                         // Service health check
ariaApi.getAnalytics(days)                        // Interaction analytics
```

**Helper Utilities:**
```javascript
ariaHelpers.formatStrategyCommand(name, action)   // Format strategy commands
ariaHelpers.formatPositionQuery(symbol)           // Format position queries
ariaHelpers.requiresConfirmation(response)        // Check if confirmation needed
ariaHelpers.isSuccessResponse(response)           // Check success status
```

**Event Emitter:**
```javascript
ariaEvents.on('message', callback)    // Listen for events
ariaEvents.emit('message', data)      // Emit events
ariaEvents.off('message', callback)   // Remove listener
```

### 4. ARIAAssistant.css (`components/ARIA/ARIAAssistant.css`)

Glassmorphism-styled CSS with:

**Design Features:**
- Frosted glass effect (`backdrop-filter: blur()`)
- Gradient accents (Atomik brand colors: `#00C6E0`)
- Smooth transitions and animations
- Voice pulse animation
- Typing indicator animation

**Responsive Design:**
- Mobile breakpoint at 768px
- Height breakpoint at 600px
- Dark mode media query support

```css
.aria-pill {
  background: rgba(255, 255, 255, 0.1);
  backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 50px;
}
```

### Frontend File Structure

```
frontend/src/
├── components/
│   ├── ARIA/
│   │   ├── ARIAAssistant.jsx    # Floating pill chat UI
│   │   └── ARIAAssistant.css    # Glassmorphism styles
│   └── Chatbox.js               # Slide-in panel chat UI
└── services/
    └── api/
        └── ariaApi.js           # API client + helpers
```

### UI Feature Matrix

| Feature | ARIAAssistant | Chatbox |
|---------|---------------|---------|
| Text input | ✅ | ✅ |
| Voice input | ✅ | ❌ |
| Text-to-speech | ✅ | ❌ |
| Example commands | ✅ | ✅ |
| Confirmation flow | ✅ | ✅ |
| TypeWriter effect | ❌ | ✅ |
| Code block rendering | ❌ | ✅ |
| Minimize/restore | ✅ | ❌ |
| Slide-in animation | ❌ | ✅ |
| Backdrop overlay | ❌ | ✅ |

---

## Request Flow

```
User Query: "What's Apple's price?"
           │
           ▼
┌─────────────────────────────┐
│   1. ARIAAssistant         │
│      process_query()        │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│   2. IntentService         │
│      recognize_intent()     │
│                             │
│   Pattern: "price|quote"    │
│   + "apple|aapl"           │
│   = MARKET_PRICE_QUERY     │
│   Entity: AAPL              │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│   3. Route to Handler      │
│   _generate_market_price   │
│   _response()              │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│   4. MarketDataService     │
│      get_quote("AAPL")     │
│                             │
│   → yfinance API call      │
│   → Returns price data     │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│   5. Format Response       │
│                             │
│   "AAPL is trading at      │
│    $234.93, up 1.45%"      │
└─────────────────────────────┘
```

---

## Dual LLM Model System

ARIA supports two LLM providers for different use cases:

### Economy Tier: Groq (Default)
- **Model**: `llama-3.1-70b-versatile`
- **API**: OpenAI-compatible (`https://api.groq.com/openai/v1`)
- **Use Case**: Day-to-day queries, simple operations
- **Cost**: Free tier available, very low cost
- **Speed**: Extremely fast (LPU inference)

### Premium Tier: Anthropic
- **Model**: `claude-3-sonnet` or `claude-3-opus`
- **Use Case**: Complex analysis, nuanced responses
- **Cost**: Higher cost per token
- **Quality**: Superior reasoning and context handling

### Configuration
```python
# In config.py
LLM_PROVIDER: str = "groq"  # Options: "groq", "anthropic", "none"
GROQ_API_KEY: str = ""
GROQ_MODEL: str = "llama-3.1-70b-versatile"
ANTHROPIC_API_KEY: str = ""
```

### Complexity-Based Routing
```python
class QueryComplexity(Enum):
    SIMPLE = "simple"      # Quick lookups, basic info
    MODERATE = "moderate"  # Multi-step queries
    COMPLEX = "complex"    # Analysis, recommendations
```

---

## Intent Recognition

### Pattern-Based Recognition

The IntentService uses regex patterns for fast, reliable intent matching:

```python
# Price Query Pattern
r"(?:what(?:'s| is)|get|show|tell me|check)?\s*(?:the\s+)?(?:current\s+)?(?:price|quote|trading|value).*?(?:of|for)?\s*([A-Za-z]+)"

# Historical Query Pattern
r"(?:what(?:'s| is)|get|show|tell me)?\s*(?:the\s+)?(?:range|high|low|performance).*?(?:of|for)?\s*([A-Za-z]+).*?(?:last|past|this)\s*(?:week|month|day)"
```

### Entity Extraction

Symbols are normalized during extraction:
```python
SYMBOL_ALIASES = {
    "apple": "AAPL",
    "tesla": "TSLA",
    "google": "GOOGL",
    "amazon": "AMZN",
    "microsoft": "MSFT",
    "nvidia": "NVDA",
    "spy": "SPY",
    "qqq": "QQQ"
}
```

### AI Fallback

For unrecognized patterns, the LLM classifies intent:
```python
if intent_type == IntentTypes.UNKNOWN and self.llm_service.is_available():
    intent = await self.llm_service.classify_intent(query)
```

---

## Market Data Integration

### Current Implementation (TEMPORARY)

Using yfinance directly in FastAPI backend:

**Supported Queries:**
- Real-time quotes: "What's AAPL's price?"
- Historical data: "What was TSLA's range last week?"
- Company info: "Tell me about NVDA"

**Caching:**
- Quotes: 60 seconds
- Historical: 5 minutes
- Company info: 1 hour

### Future Migration: atomik-data-hub

The atomik-data-hub service exists with:
- **Databento**: Futures data
- **Polygon**: Stocks/ETFs data

**Migration Steps:**
1. Configure Polygon API key in atomik-data-hub
2. Configure Databento for futures
3. Update ARIA to call Data Hub endpoints
4. Remove yfinance dependency

---

## API Endpoints

### POST `/api/v1/aria/chat`

Process a chat message from the user.

**Request:**
```json
{
    "message": "What's Apple's price?",
    "context": {
        "session_id": "optional-session-id"
    }
}
```

**Response:**
```json
{
    "success": true,
    "response": "AAPL (Apple Inc.) is currently trading at $234.93, up $3.36 (1.45%) today.",
    "intent": "market_price_query",
    "data": {
        "symbol": "AAPL",
        "price": 234.93,
        "change": 3.36,
        "change_percent": 1.45
    },
    "timestamp": "2024-11-25T20:30:00Z"
}
```

### GET `/api/v1/aria/health`

Check ARIA service health.

**Response:**
```json
{
    "status": "healthy",
    "components": {
        "database": "connected",
        "redis": "connected",
        "llm": {
            "provider": "groq",
            "status": "available"
        },
        "market_data": "available"
    }
}
```

---

## Configuration

### Environment Variables

```bash
# LLM Configuration
LLM_PROVIDER=groq                           # groq, anthropic, or none
GROQ_API_KEY=gsk_xxxxxxxxxxxxx              # Groq API key
GROQ_MODEL=llama-3.1-70b-versatile          # Groq model
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxx      # Anthropic API key (optional)

# Redis (for context caching)
REDIS_URL=redis://localhost:6379

# Database
DATABASE_URL=postgresql://user:pass@host:5432/db
```

### Railway Configuration

Set these in Railway dashboard under Variables:
- `GROQ_API_KEY`
- `LLM_PROVIDER`
- `GROQ_MODEL`

---

## Database Models

### ARIAInteraction

Tracks all user interactions:

```python
class ARIAInteraction(Base):
    __tablename__ = "aria_interactions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    query = Column(Text)
    intent_type = Column(String(50))
    response = Column(Text)
    confidence = Column(Float)
    processing_time_ms = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
```

### ARIAContext

Stores conversation context:

```python
class ARIAContext(Base):
    __tablename__ = "aria_contexts"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    session_id = Column(String(100))
    context_data = Column(JSON)
    expires_at = Column(DateTime)
```

---

## Testing

### API Testing with cURL

```bash
# Health Check
curl https://your-app.railway.app/api/v1/aria/health

# Chat (with authentication)
curl -X POST https://your-app.railway.app/api/v1/aria/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -d '{"message": "What is AAPL trading at?"}'
```

### Example Queries

| Query | Intent | Expected Response |
|-------|--------|-------------------|
| "What's Apple's price?" | market_price_query | Current AAPL price with change |
| "Show me Tesla's range last week" | market_historical_query | TSLA weekly high/low/range |
| "What accounts do I have?" | account_query | List of connected accounts |
| "Show my strategies" | strategy_query | User's trading strategies |
| "Help" | help_query | Available commands |

---

## Migration Notes

### TEMPORARY Code Markers

All temporary implementations are marked with comments:

```python
# TEMPORARY: For ARIA market data - will migrate to atomik-data-hub
# TODO: Migration plan:
# 1. Configure Polygon API key in atomik-data-hub
# 2. Configure Databento for futures
# 3. Update ARIA to call Data Hub endpoints
# 4. Remove this file and yfinance dependency
```

### Files to Clean Up

When migrating to atomik-data-hub:
1. Remove `market_data_service.py`
2. Remove yfinance from `requirements.txt`
3. Update `intent_service.py` to route to Data Hub
4. Update `aria_assistant.py` handlers

### atomik-data-hub Integration Points

The Data Hub has MCP server structure at:
- `atomik-data-hub/src/mcp_financial_server/server.py`

Will need to:
- Configure as internal service call
- Or expose REST endpoints for ARIA consumption

---

## File Structure

```
PRJCT/
├── fastapi_backend/
│   ├── app/
│   │   ├── api/v1/endpoints/
│   │   │   └── aria.py              # API routes
│   │   ├── services/
│   │   │   ├── aria_assistant.py    # Main orchestrator
│   │   │   ├── intent_service.py    # Intent recognition
│   │   │   ├── llm_service.py       # LLM provider management
│   │   │   ├── market_data_service.py  # TEMPORARY: yfinance
│   │   │   ├── context_engine.py    # Context management
│   │   │   └── action_executor.py   # Action execution
│   │   ├── models/
│   │   │   └── aria.py              # Database models
│   │   └── core/
│   │       └── config.py            # Configuration
│   ├── docs/
│   │   └── ARIA_DOCUMENTATION.md    # This file
│   └── requirements.txt             # Dependencies
│
└── frontend/
    └── src/
        ├── components/
        │   ├── ARIA/
        │   │   ├── ARIAAssistant.jsx    # Floating pill chat UI
        │   │   └── ARIAAssistant.css    # Glassmorphism styles
        │   └── Chatbox.js               # Slide-in panel chat UI
        └── services/
            └── api/
                └── ariaApi.js           # API client + helpers + events
```

---

## Changelog

### 2025-11-25
- **Frontend UI Components Completed**
  - Added `ARIAAssistant.jsx` - Floating pill chat with voice support
  - Added `ARIAAssistant.css` - Glassmorphism styling with animations
  - Added `Chatbox.js` - Slide-in panel chat with Chakra UI + Framer Motion
  - Added `ariaApi.js` - Complete API service with helpers and event emitter
- Voice input via Web Speech API
- Text-to-speech for ARIA responses
- Confirmation workflow for trading actions
- Example commands/quick tips
- Responsive design with mobile support
- Updated documentation with frontend section

### 2024-11-25
- Integrated Groq as economy LLM provider
- Added yfinance market data service (temporary)
- Added market data intent recognition
- Created comprehensive documentation
- Fixed SQLAlchemy text() wrapper issue

### Completed
- [x] Implement frontend UI components (2025-11-25)

### Future
- [ ] Migrate market data to atomik-data-hub
- [ ] Add Anthropic premium tier activation
- [ ] Add conversation memory persistence
- [ ] Implement trading action execution

---

## Support

For issues or questions:
- Check the health endpoint first
- Verify environment variables are set
- Check Railway logs for errors
- Review intent patterns if queries aren't recognized
