# ARIA Refactor Plan: Tool Calling Architecture

**STATUS: IMPLEMENTED** (2024-11-25)

## Overview

Migrate ARIA from rule-based intent detection to LLM-first architecture with tool calling. This eliminates manual parsing and lets the LLM naturally understand user intent.

## Implementation Summary

The tool-calling architecture has been implemented with the following files:
- `app/services/aria_tools.py` - Tool definitions and ARIAToolExecutor class
- `app/services/llm_service.py` - Added `chat_with_tools()` and related methods
- `app/services/aria_assistant.py` - Added `_process_with_tools()` method, enabled by `USE_TOOL_CALLING = True`
- `app/services/aria_conversation_memory.py` - Multi-turn conversation memory

### Model Configuration

**Default Model**: `openai/gpt-oss-20b` (via Groq)
- 20B parameter Mixture of Experts model
- 131K context window for long conversations
- **Prompt Caching**: 50% discount on cached input tokens (system prompt + tools)
- **Tool Calling**: Native support for function-based architecture
- **Pricing**: $0.075/1M input ($0.0375 cached), $0.30/1M output

To toggle between architectures, set `ARIAAssistant.USE_TOOL_CALLING`:
- `True` (default): Use LLM tool-calling architecture
- `False`: Use legacy rule-based intent detection

## Current vs New Architecture

### Current (Rule-Based)
```
User Query → Regex/Keyword Parsing → Intent Detection → Route to Handler → Fetch Data → LLM Response
```

### New (Tool Calling)
```
User Query → LLM (with tools) → LLM calls tools as needed → LLM generates response
```

---

## Phase 1: Define ARIA Tools

### 1.1 Market Data Tools
```python
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_stock_quote",
            "description": "Get current price, change, volume, and day range for a stock or ETF. Use this when user asks about current price or how a stock is doing today.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Stock/ETF ticker symbol (e.g., AAPL, SPY, TSLA)"
                    }
                },
                "required": ["symbol"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_historical_data",
            "description": "Get historical OHLC data for a stock. Use for questions about past performance, weekly/monthly ranges, or specific dates.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Stock/ETF ticker symbol"
                    },
                    "period": {
                        "type": "string",
                        "enum": ["day", "week", "month"],
                        "description": "Time period for historical data"
                    },
                    "specific_day": {
                        "type": "string",
                        "description": "Specific day like 'last_friday', 'last_monday' (optional)"
                    }
                },
                "required": ["symbol"]
            }
        }
    }
]
```

### 1.2 User Data Tools
```python
{
    "name": "get_user_positions",
    "description": "Get user's current open trading positions. Use when user asks about their holdings or portfolio.",
    "parameters": {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "description": "Optional: specific symbol to check (omit for all positions)"
            }
        }
    }
},
{
    "name": "get_active_strategies",
    "description": "Get user's currently active trading strategies. Use when user asks what strategies are running.",
    "parameters": {
        "type": "object",
        "properties": {}
    }
},
{
    "name": "get_trading_performance",
    "description": "Get user's trading performance metrics (P&L, win rate, etc.). Use when user asks how they're doing.",
    "parameters": {
        "type": "object",
        "properties": {
            "period": {
                "type": "string",
                "enum": ["today", "week", "month", "all"],
                "description": "Time period for performance"
            }
        }
    }
}
```

### 1.3 Action Tools (Require Confirmation)
```python
{
    "name": "activate_strategy",
    "description": "Activate a trading strategy. ALWAYS confirm with user before executing.",
    "parameters": {
        "type": "object",
        "properties": {
            "strategy_name": {
                "type": "string",
                "description": "Name of the strategy to activate"
            }
        },
        "required": ["strategy_name"]
    }
},
{
    "name": "deactivate_strategy",
    "description": "Deactivate a trading strategy. ALWAYS confirm with user before executing.",
    "parameters": {
        "type": "object",
        "properties": {
            "strategy_name": {
                "type": "string",
                "description": "Name of the strategy to deactivate"
            }
        },
        "required": ["strategy_name"]
    }
}
```

---

## Phase 2: Update LLM Service

### 2.1 New File Structure
```
app/services/
├── llm_service.py          # Updated with tool calling support
├── aria_tools.py           # NEW: Tool definitions and executors
├── aria_assistant.py       # Simplified orchestrator
├── market_data_service.py  # Unchanged (becomes tool backend)
├── aria_context_engine.py  # Unchanged (becomes tool backend)
└── intent_service.py       # DEPRECATED (keep for backward compat)
```

### 2.2 LLM Service Changes

```python
# llm_service.py - Key changes

class LLMService:
    def __init__(self):
        # ... existing init ...
        self.tools = self._load_aria_tools()

    async def chat_with_tools(
        self,
        user_query: str,
        user_id: int,
        use_premium: bool = False
    ) -> Dict[str, Any]:
        """
        Main entry point - sends query to LLM with available tools.
        LLM decides if/which tools to call.
        """
        provider = "anthropic" if use_premium else "groq"

        # Initial LLM call with tools
        response = await self._call_llm_with_tools(
            query=user_query,
            tools=self.tools,
            provider=provider
        )

        # If LLM wants to call tools
        if response.tool_calls:
            tool_results = await self._execute_tools(
                response.tool_calls,
                user_id
            )

            # Send tool results back to LLM for final response
            final_response = await self._call_llm_with_tool_results(
                original_query=user_query,
                tool_calls=response.tool_calls,
                tool_results=tool_results,
                provider=provider
            )
            return final_response

        # No tools needed - return direct response
        return {"text": response.content, "tools_used": []}
```

### 2.3 Groq Tool Calling Format
```python
# Groq uses OpenAI-compatible format
response = self.client.chat.completions.create(
    model="llama-3.1-70b-versatile",
    messages=[
        {"role": "system", "content": ARIA_SYSTEM_PROMPT},
        {"role": "user", "content": user_query}
    ],
    tools=tools,
    tool_choice="auto"  # Let LLM decide
)
```

### 2.4 Claude Tool Calling Format
```python
# Anthropic format
response = self.client.messages.create(
    model="claude-3-sonnet-20240229",
    max_tokens=1024,
    system=ARIA_SYSTEM_PROMPT,
    tools=tools,
    messages=[{"role": "user", "content": user_query}]
)
```

---

## Phase 3: Create Tool Executor

### 3.1 New File: aria_tools.py

```python
# app/services/aria_tools.py

from typing import Dict, Any, List
from .market_data_service import MarketDataService
from .aria_context_engine import ARIAContextEngine

class ARIAToolExecutor:
    """Executes tools called by the LLM"""

    def __init__(self, db, user_id: int):
        self.db = db
        self.user_id = user_id
        self.market_service = MarketDataService()
        self.context_engine = ARIAContextEngine(db)

    async def execute(self, tool_name: str, arguments: Dict) -> Dict[str, Any]:
        """Route tool call to appropriate handler"""

        handlers = {
            "get_stock_quote": self._get_stock_quote,
            "get_historical_data": self._get_historical_data,
            "get_user_positions": self._get_user_positions,
            "get_active_strategies": self._get_active_strategies,
            "get_trading_performance": self._get_trading_performance,
            "activate_strategy": self._activate_strategy,
            "deactivate_strategy": self._deactivate_strategy,
        }

        handler = handlers.get(tool_name)
        if not handler:
            return {"error": f"Unknown tool: {tool_name}"}

        return await handler(**arguments)

    async def _get_stock_quote(self, symbol: str) -> Dict:
        result = await self.market_service.get_quote(symbol)
        return result.get("data", {})

    async def _get_historical_data(
        self,
        symbol: str,
        period: str = "week",
        specific_day: str = None
    ) -> Dict:
        if specific_day:
            # Parse "last_friday" -> day="friday", modifier="last"
            parts = specific_day.split("_")
            modifier = parts[0] if len(parts) > 1 else "last"
            day = parts[-1]
            result = await self.market_service.get_specific_day_data(
                symbol, day, modifier
            )
        else:
            period_map = {"day": "1d", "week": "1wk", "month": "1mo"}
            result = await self.market_service.get_historical(
                symbol, period_map.get(period, "1wk")
            )
        return result.get("data", {})

    async def _get_user_positions(self, symbol: str = None) -> Dict:
        positions = await self.context_engine._get_current_positions(self.user_id)
        if symbol:
            return positions.get(symbol.upper(), {})
        return positions

    async def _get_active_strategies(self) -> List[Dict]:
        return await self.context_engine._get_active_strategies(self.user_id)

    async def _get_trading_performance(self, period: str = "today") -> Dict:
        return await self.context_engine._get_performance_summary(self.user_id)

    async def _activate_strategy(self, strategy_name: str) -> Dict:
        # Return confirmation request instead of executing
        return {
            "requires_confirmation": True,
            "action": "activate_strategy",
            "strategy_name": strategy_name,
            "message": f"Ready to activate '{strategy_name}'. Please confirm."
        }

    async def _deactivate_strategy(self, strategy_name: str) -> Dict:
        return {
            "requires_confirmation": True,
            "action": "deactivate_strategy",
            "strategy_name": strategy_name,
            "message": f"Ready to deactivate '{strategy_name}'. Please confirm."
        }
```

---

## Phase 4: Simplify ARIA Assistant

### 4.1 New Simplified Flow

```python
# app/services/aria_assistant.py - Simplified

class ARIAAssistant:
    def __init__(self, db: Session):
        self.db = db
        self.llm_service = LLMService()

    async def process_user_input(
        self,
        user_id: int,
        input_text: str,
        input_type: str = "text",
        use_premium: bool = False
    ) -> Dict[str, Any]:
        """
        Simplified main entry point.
        Everything goes through LLM with tools.
        """
        start_time = datetime.utcnow()

        try:
            # Single LLM call handles everything
            response = await self.llm_service.chat_with_tools(
                user_query=input_text,
                user_id=user_id,
                use_premium=use_premium
            )

            # Handle confirmation requests from action tools
            if response.get("requires_confirmation"):
                return {
                    "success": True,
                    "requires_confirmation": True,
                    "response": {
                        "text": response["message"],
                        "type": "confirmation"
                    },
                    "pending_action": response
                }

            # Normal response
            processing_time = int((datetime.utcnow() - start_time).total_seconds() * 1000)

            return {
                "success": True,
                "response": {
                    "text": response["text"],
                    "type": "text"
                },
                "tools_used": response.get("tools_used", []),
                "provider": response.get("provider"),
                "processing_time_ms": processing_time
            }

        except Exception as e:
            logger.error(f"ARIA processing error: {e}")
            return {
                "success": False,
                "response": {
                    "text": "I encountered an error. Please try again.",
                    "type": "error"
                },
                "error": str(e)
            }
```

---

## Phase 5: System Prompt for Tool Calling

```python
ARIA_SYSTEM_PROMPT = """You are ARIA, an expert AI trading assistant for the Atomik Trading platform.

## Your Capabilities
You have access to tools that let you:
- Get real-time stock/ETF quotes
- Fetch historical price data
- Check user's positions and portfolio
- View active trading strategies
- Check trading performance

## Guidelines
1. For questions about specific stocks/prices, USE the get_stock_quote tool
2. For historical data questions, USE the get_historical_data tool
3. For portfolio/position questions, USE the get_user_positions tool
4. For general market/trading questions, answer directly from your knowledge
5. Be conversational and helpful
6. Include specific numbers when you have them from tools
7. Never make up prices or data - if you don't have it, say so

## Response Style
- Be concise but informative
- Use natural, friendly language
- Include relevant data from tool results
- For financial questions, add appropriate caveats

## Important
- You can answer general questions without tools (e.g., "what is a bull market")
- Only use tools when you need specific data
- If a tool call fails, explain the issue and offer alternatives
"""
```

---

## Phase 6: Migration Steps

### Step 1: Create aria_tools.py (NEW FILE)
- Define all tools in OpenAI/Anthropic format
- Create ARIAToolExecutor class

### Step 2: Update llm_service.py
- Add `chat_with_tools()` method
- Add tool calling support for both Groq and Anthropic
- Add `_execute_tools()` method

### Step 3: Simplify aria_assistant.py
- Remove intent routing logic
- Use single `chat_with_tools()` call
- Handle confirmation flow

### Step 4: Deprecate intent_service.py
- Keep file for backward compatibility
- Mark as deprecated
- Remove from main flow

### Step 5: Update API endpoints
- No changes needed - same interface
- Add optional `use_premium` parameter

### Step 6: Testing
- Test all tool calls individually
- Test natural language variations
- Test edge cases ("IS" vs ticker)
- Test confirmation flow for actions

---

## Benefits After Migration

| Aspect | Before | After |
|--------|--------|-------|
| Edge cases | Manual handling | LLM handles naturally |
| New features | Add regex patterns | Add new tool |
| Code complexity | ~700 lines intent service | ~100 lines tool executor |
| Maintenance | High (pattern tuning) | Low (tool definitions) |
| Natural language | Limited patterns | Full understanding |
| Development speed | Slow (test patterns) | Fast (define tool, done) |

---

## Cost Estimate

| Provider | Cost per Query | Monthly (1000 queries/day) |
|----------|---------------|---------------------------|
| Groq (Llama 3.1 70B) | ~$0.0005 | ~$15/month |
| Claude Sonnet | ~$0.003 | ~$90/month |

Recommendation: Use Groq for 95% of queries, Claude for complex analysis or user-requested premium.

---

## Timeline

1. **Phase 1-2**: Create tool definitions and update LLM service (Day 1) - DONE
2. **Phase 3-4**: Create tool executor and simplify assistant (Day 1-2) - DONE
3. **Phase 5**: System prompt optimization (Day 2) - DONE
4. **Phase 6**: Testing and deployment (Day 2-3) - IN PROGRESS

**Total: 2-3 days for full migration**

### Files Created/Modified:
- `app/services/aria_tools.py` (NEW) - 350+ lines
- `app/services/llm_service.py` (MODIFIED) - Added ~400 lines
- `app/services/aria_assistant.py` (MODIFIED) - Added ~130 lines

---

## Questions Before Implementation

1. Should we keep the current system as fallback during migration?
2. Any tools we should add beyond the ones listed?
3. Premium (Claude) trigger - user button or automatic for complex queries?
4. Should action confirmations go through the UI or voice?
