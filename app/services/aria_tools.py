# app/services/aria_tools.py
"""
ARIA Tool Calling System

This module defines the tools available to ARIA and provides the executor
that routes LLM tool calls to the appropriate handlers.

Tools are defined in OpenAI-compatible format (works with both Groq and Anthropic).
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# =============================================================================
# Tool Definitions
# =============================================================================

ARIA_TOOLS = [
    # -------------------------------------------------------------------------
    # Market Data Tools
    # -------------------------------------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "get_stock_quote",
            "description": "Get current price, change, volume, and day range for a stock or ETF. Use this when user asks about current price, how a stock is doing today, or wants real-time market data.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Stock/ETF ticker symbol (e.g., AAPL, SPY, TSLA, QQQ)"
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
            "description": "Get historical OHLC data for a stock. Use for questions about past performance, weekly/monthly ranges, or specific dates like 'last Friday'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Stock/ETF ticker symbol"
                    },
                    "period": {
                        "type": "string",
                        "enum": ["1d", "5d", "1wk", "1mo", "3mo"],
                        "description": "Time period for historical data"
                    },
                    "specific_day": {
                        "type": "string",
                        "description": "Specific day like 'last_friday', 'last_monday' (optional, use for specific day queries)"
                    }
                },
                "required": ["symbol"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_company_info",
            "description": "Get basic company information including name, sector, and industry. Use when user asks about what a company does or its sector.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Stock ticker symbol"
                    }
                },
                "required": ["symbol"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_fundamental_data",
            "description": "Get fundamental/financial data for a stock including P/E ratio, EPS, market cap, revenue, profit margins, dividends, 52-week range, and analyst recommendations. Use when user asks about valuation, earnings, financials, fundamentals, P/E, market cap, dividends, or analyst targets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Stock ticker symbol"
                    }
                },
                "required": ["symbol"]
            }
        }
    },
    # -------------------------------------------------------------------------
    # User Data Tools
    # -------------------------------------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "get_user_positions",
            "description": "Get user's current open trading positions. Use when user asks about their holdings, portfolio, or specific position.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Optional: specific symbol to check (omit for all positions)"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_active_strategies",
            "description": "Get user's currently active trading strategies. Use when user asks what strategies are running or about their automation.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_trading_performance",
            "description": "Get user's trading performance metrics (P&L, win rate, etc.). Use when user asks how they're doing or about their performance.",
            "parameters": {
                "type": "object",
                "properties": {
                    "period": {
                        "type": "string",
                        "enum": ["today", "week", "month", "all"],
                        "description": "Time period for performance"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_broker_status",
            "description": "Get status of user's connected broker accounts. Use when user asks about their broker connection or account status.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    # -------------------------------------------------------------------------
    # Action Tools (Require Confirmation)
    # -------------------------------------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "activate_strategy",
            "description": "Activate a trading strategy. ALWAYS confirm with user before executing. Use when user wants to turn on or start a strategy.",
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
        }
    },
    {
        "type": "function",
        "function": {
            "name": "deactivate_strategy",
            "description": "Deactivate a trading strategy. ALWAYS confirm with user before executing. Use when user wants to turn off or stop a strategy.",
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
    }
]


def get_tools_for_anthropic() -> List[Dict[str, Any]]:
    """
    Convert tools to Anthropic's format.
    Anthropic uses a slightly different structure.
    """
    anthropic_tools = []
    for tool in ARIA_TOOLS:
        anthropic_tools.append({
            "name": tool["function"]["name"],
            "description": tool["function"]["description"],
            "input_schema": tool["function"]["parameters"]
        })
    return anthropic_tools


def get_tools_for_groq() -> List[Dict[str, Any]]:
    """
    Get tools in OpenAI-compatible format (works directly with Groq).
    """
    return ARIA_TOOLS


# =============================================================================
# Tool Executor
# =============================================================================

class ARIAToolExecutor:
    """
    Executes tools called by the LLM.

    Routes tool calls to appropriate handlers and returns results
    in a format the LLM can understand.
    """

    def __init__(self, db: Session, user_id: int):
        """
        Initialize the tool executor.

        Args:
            db: Database session
            user_id: Current user's ID
        """
        self.db = db
        self.user_id = user_id

        # Lazy-load services to avoid circular imports
        self._market_service = None
        self._context_engine = None

    @property
    def market_service(self):
        """Lazy load market data service"""
        if self._market_service is None:
            from .market_data_service import MarketDataService
            self._market_service = MarketDataService()
        return self._market_service

    @property
    def context_engine(self):
        """Lazy load context engine"""
        if self._context_engine is None:
            from .aria_context_engine import ARIAContextEngine
            self._context_engine = ARIAContextEngine(self.db)
        return self._context_engine

    async def execute(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a tool call and return results.

        Args:
            tool_name: Name of the tool to execute
            arguments: Arguments passed to the tool

        Returns:
            Tool execution result as a dictionary
        """
        handlers = {
            "get_stock_quote": self._get_stock_quote,
            "get_historical_data": self._get_historical_data,
            "get_company_info": self._get_company_info,
            "get_fundamental_data": self._get_fundamental_data,
            "get_user_positions": self._get_user_positions,
            "get_active_strategies": self._get_active_strategies,
            "get_trading_performance": self._get_trading_performance,
            "get_broker_status": self._get_broker_status,
            "activate_strategy": self._activate_strategy,
            "deactivate_strategy": self._deactivate_strategy,
        }

        handler = handlers.get(tool_name)
        if not handler:
            logger.warning(f"Unknown tool: {tool_name}")
            return {"error": f"Unknown tool: {tool_name}"}

        try:
            logger.info(f"Executing tool: {tool_name} with args: {arguments}")
            result = await handler(**arguments)
            logger.info(f"Tool {tool_name} completed successfully")
            return result
        except Exception as e:
            logger.error(f"Tool {tool_name} failed: {e}")
            return {"error": f"Tool execution failed: {str(e)}"}

    async def execute_multiple(
        self,
        tool_calls: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Execute multiple tool calls and return all results.

        Args:
            tool_calls: List of tool calls from the LLM

        Returns:
            List of results corresponding to each tool call
        """
        results = []
        for call in tool_calls:
            tool_name = call.get("name") or call.get("function", {}).get("name")
            arguments = call.get("arguments") or call.get("function", {}).get("arguments", {})

            # Parse arguments if they're a string (JSON)
            if isinstance(arguments, str):
                import json
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {}

            result = await self.execute(tool_name, arguments)
            results.append({
                "tool_call_id": call.get("id", tool_name),
                "name": tool_name,
                "result": result
            })

        return results

    # -------------------------------------------------------------------------
    # Tool Handlers: Market Data
    # -------------------------------------------------------------------------

    async def _get_stock_quote(self, symbol: str) -> Dict[str, Any]:
        """Get current stock quote"""
        result = await self.market_service.get_quote(symbol)

        if not result.get("success"):
            return {"error": result.get("error", "Failed to fetch quote")}

        data = result.get("data", {})
        return {
            "symbol": data.get("symbol", symbol.upper()),
            "price": data.get("price"),
            "change": data.get("change"),
            "change_percent": data.get("change_percent"),
            "volume": data.get("volume"),
            "day_high": data.get("day_high"),
            "day_low": data.get("day_low"),
            "open": data.get("open"),
            "previous_close": data.get("previous_close"),
            "timestamp": data.get("timestamp")
        }

    async def _get_historical_data(
        self,
        symbol: str,
        period: str = "1wk",
        specific_day: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get historical data for a symbol"""
        if specific_day:
            # Parse "last_friday" style queries
            parts = specific_day.lower().replace("-", "_").split("_")
            modifier = parts[0] if len(parts) > 1 and parts[0] in ["last", "this"] else "last"
            day = parts[-1]

            result = await self.market_service.get_specific_day_data(
                symbol, day, modifier
            )
        else:
            result = await self.market_service.get_historical(symbol, period)

        if not result.get("success"):
            return {"error": result.get("error", "Failed to fetch historical data")}

        return result.get("data", {})

    async def _get_company_info(self, symbol: str) -> Dict[str, Any]:
        """Get company information"""
        result = await self.market_service.get_company_info(symbol)

        if not result.get("success"):
            return {"error": result.get("error", "Failed to fetch company info")}

        return result.get("data", {})

    async def _get_fundamental_data(self, symbol: str) -> Dict[str, Any]:
        """Get fundamental/financial data for a stock"""
        result = await self.market_service.get_fundamental_data(symbol)

        if not result.get("success"):
            return {"error": result.get("error", "Failed to fetch fundamental data")}

        return result.get("data", {})

    # -------------------------------------------------------------------------
    # Tool Handlers: User Data
    # -------------------------------------------------------------------------

    async def _get_user_positions(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        """Get user's current positions"""
        try:
            positions_data = await self.context_engine._get_current_positions(self.user_id)
            positions = positions_data.get("positions", {})

            if symbol:
                symbol_upper = symbol.upper()
                if symbol_upper in positions:
                    return {
                        "symbol": symbol_upper,
                        "position": positions[symbol_upper]
                    }
                else:
                    return {
                        "symbol": symbol_upper,
                        "position": None,
                        "message": f"No position found for {symbol_upper}"
                    }

            return {
                "total_positions": len(positions),
                "positions": positions,
                "total_unrealized_pnl": positions_data.get("total_unrealized_pnl", 0)
            }
        except Exception as e:
            logger.error(f"Error getting positions: {e}")
            return {"error": str(e)}

    async def _get_active_strategies(self) -> Dict[str, Any]:
        """Get user's active strategies"""
        try:
            strategies = await self.context_engine._get_active_strategies(self.user_id)
            return {
                "active_count": len(strategies),
                "strategies": strategies
            }
        except Exception as e:
            logger.error(f"Error getting strategies: {e}")
            return {"error": str(e)}

    async def _get_trading_performance(self, period: str = "today") -> Dict[str, Any]:
        """Get trading performance"""
        try:
            performance = await self.context_engine._get_performance_summary(self.user_id)

            # Filter by period if needed
            if period == "today":
                return {
                    "period": "today",
                    "pnl": performance.get("daily_pnl", 0),
                    "trades": performance.get("daily_trades", 0),
                    "win_rate": performance.get("daily_win_rate", 0)
                }
            elif period == "week":
                return {
                    "period": "week",
                    "pnl": performance.get("weekly_pnl", 0),
                    "trades": performance.get("weekly_trades", 0)
                }
            elif period == "month":
                return {
                    "period": "month",
                    "pnl": performance.get("monthly_pnl", 0),
                    "trades": performance.get("monthly_trades", 0)
                }
            else:
                return performance

        except Exception as e:
            logger.error(f"Error getting performance: {e}")
            return {"error": str(e)}

    async def _get_broker_status(self) -> Dict[str, Any]:
        """Get broker account status"""
        try:
            broker_status = await self.context_engine._get_broker_status(self.user_id)

            connected_count = sum(
                1 for b in broker_status.values()
                if b.get("connected", False)
            )

            return {
                "total_accounts": len(broker_status),
                "connected_accounts": connected_count,
                "accounts": broker_status
            }
        except Exception as e:
            logger.error(f"Error getting broker status: {e}")
            return {"error": str(e)}

    # -------------------------------------------------------------------------
    # Tool Handlers: Actions (Require Confirmation)
    # -------------------------------------------------------------------------

    async def _activate_strategy(self, strategy_name: str) -> Dict[str, Any]:
        """
        Prepare to activate a strategy (requires user confirmation).

        This doesn't execute immediately - returns a confirmation request.
        """
        return {
            "requires_confirmation": True,
            "action": "activate_strategy",
            "strategy_name": strategy_name,
            "message": f"Ready to activate strategy '{strategy_name}'. Please confirm to proceed.",
            "confirmation_prompt": f"Would you like me to activate '{strategy_name}'?"
        }

    async def _deactivate_strategy(self, strategy_name: str) -> Dict[str, Any]:
        """
        Prepare to deactivate a strategy (requires user confirmation).

        This doesn't execute immediately - returns a confirmation request.
        """
        return {
            "requires_confirmation": True,
            "action": "deactivate_strategy",
            "strategy_name": strategy_name,
            "message": f"Ready to deactivate strategy '{strategy_name}'. Please confirm to proceed.",
            "confirmation_prompt": f"Would you like me to deactivate '{strategy_name}'?"
        }


# =============================================================================
# System Prompt for Tool Calling
# =============================================================================

ARIA_TOOL_CALLING_SYSTEM_PROMPT = """You are ARIA, an expert AI trading assistant for the Atomik Trading platform.

## Your Capabilities
You have access to tools that let you:
- Get real-time stock/ETF quotes and prices
- Fetch historical price data for any period
- Check company information
- View user's positions and portfolio
- See active trading strategies
- Check trading performance metrics
- View broker account status

## Guidelines

### When to Use Tools
1. **Price questions** → Use get_stock_quote
   - "What's the price of AAPL?"
   - "How is SPY doing today?"
   - "Is Tesla up or down?"

2. **Historical data** → Use get_historical_data
   - "What was TSLA's opening price last Friday?"
   - "Show me SPY's weekly range"
   - "How has AAPL performed this month?"

3. **Fundamental/Financial data** → Use get_fundamental_data
   - "What's Apple's P/E ratio?"
   - "What's the market cap of NVDA?"
   - "Does MSFT pay dividends?"
   - "What do analysts think about TSLA?"
   - "What's Tesla's EPS?"
   - "Show me Amazon's profit margins"

4. **Portfolio questions** → Use get_user_positions
   - "What positions do I have?"
   - "Do I own any AAPL?"
   - "Show me my holdings"

5. **Strategy questions** → Use get_active_strategies
   - "What strategies are running?"
   - "Show me my active automations"

6. **Performance questions** → Use get_trading_performance
   - "How am I doing today?"
   - "What's my P&L this week?"

### When NOT to Use Tools
- General knowledge questions about trading, markets, or finance
- Explanations of concepts (what is a bull market, etc.)
- Opinion questions (should I buy, what do you think)
- Questions that don't require specific data

### Response Guidelines
- Be conversational and helpful
- Include specific numbers when you have data
- Never make up prices or data - if you don't have it, say so
- For financial questions, add appropriate caveats
- Keep responses concise but informative
- Use natural, friendly language

## Important
- Only call tools when you need specific data
- You can answer general questions directly from your knowledge
- If a tool call fails, explain the issue and offer alternatives
- For action tools (activate/deactivate), ALWAYS wait for user confirmation
"""
