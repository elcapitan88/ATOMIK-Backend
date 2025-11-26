# app/services/llm_service.py
"""
LLM Service for ARIA - Multi-provider support with Tool Calling

Providers:
- Groq (economy): openai/gpt-oss-20b - Fast, cheap, prompt caching enabled
- Anthropic (premium): Claude Sonnet - Best quality for complex queries

Architecture: LLM-first with tool calling
- LLM decides which tools to use based on user queries
- System prompt + tool definitions are cached (50% cost reduction on Groq)
- 131K context window supports long conversation histories
"""

import logging
from typing import Dict, Any, Optional, List, Union
from datetime import datetime
import json
from enum import Enum

from ..core.config import settings

logger = logging.getLogger(__name__)


class LLMProvider(Enum):
    """Supported LLM providers"""
    GROQ = "groq"
    ANTHROPIC = "anthropic"
    NONE = "none"


class QueryComplexity(Enum):
    """Query complexity levels for configuration"""
    SIMPLE = "simple"
    MODERATE = "moderate"
    COMPLEX = "complex"


class LLMService:
    """
    Multi-provider LLM service for ARIA
    Supports Groq (economy/fast) and Anthropic Claude (premium/best quality)
    """

    def __init__(self):
        """Initialize LLM client based on configured provider"""
        self.provider = getattr(settings, 'LLM_PROVIDER', 'none').lower()
        self.client = None
        self.model = None

        if self.provider == "groq":
            self._init_groq()
        elif self.provider == "anthropic":
            self._init_anthropic()
        else:
            logger.warning(f"LLM provider '{self.provider}' not configured. LLM features disabled.")

        # Track usage for cost monitoring
        self.usage_stats = {
            "total_requests": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "estimated_cost": 0.0,
            "provider": self.provider
        }

    def _init_groq(self):
        """
        Initialize Groq client (OpenAI-compatible API)

        Default model: openai/gpt-oss-20b
        - 20B parameter MoE model with 131K context
        - Supports prompt caching (50% discount on cached input tokens)
        - Supports tool calling for ARIA's function-based architecture
        - Pricing: $0.075/1M input ($0.0375 cached), $0.30/1M output
        """
        api_key = getattr(settings, 'GROQ_API_KEY', '')

        if not api_key:
            logger.warning("No GROQ_API_KEY found. LLM features will be disabled.")
            self.provider = "none"
            return

        try:
            from openai import OpenAI
            self.client = OpenAI(
                api_key=api_key,
                base_url="https://api.groq.com/openai/v1"
            )
            # GPT-OSS-20B: Best balance of speed, cost, and capabilities
            # - Prompt caching: 50% off on repeated system prompts/tools
            # - Tool calling: Native support for ARIA's function architecture
            # - 131K context: Handles long conversation histories
            self.model = getattr(settings, 'GROQ_MODEL', 'openai/gpt-oss-20b')
            logger.info(f"LLM Service initialized with Groq ({self.model})")
        except ImportError:
            logger.error("OpenAI package not installed. Run: pip install openai")
            self.provider = "none"
        except Exception as e:
            logger.error(f"Failed to initialize Groq client: {e}")
            self.provider = "none"

    def _init_anthropic(self):
        """Initialize Anthropic Claude client"""
        api_key = getattr(settings, 'ANTHROPIC_API_KEY', '')

        if not api_key:
            logger.warning("No ANTHROPIC_API_KEY found. LLM features will be disabled.")
            self.provider = "none"
            return

        try:
            import anthropic
            self.client = anthropic.Anthropic(api_key=api_key)
            self.model = "claude-3-sonnet-20240229"
            logger.info(f"LLM Service initialized with Anthropic ({self.model})")
        except ImportError:
            logger.error("Anthropic package not installed. Run: pip install anthropic")
            self.provider = "none"
        except Exception as e:
            logger.error(f"Failed to initialize Anthropic client: {e}")
            self.provider = "none"

    def get_query_config(self, complexity: QueryComplexity) -> Dict[str, Any]:
        """
        Get optimized configuration based on query complexity

        Args:
            complexity: Query complexity level

        Returns:
            Configuration dictionary with parameters
        """
        configs = {
            QueryComplexity.SIMPLE: {
                'max_tokens': settings.ARIA_SIMPLE_MAX_TOKENS if hasattr(settings, 'ARIA_SIMPLE_MAX_TOKENS') else 200,
                'temperature': 0.4,
                'system_prompt': """You are ARIA, an expert AI trading assistant for the Atomik Trading platform.
You specialize in stocks, ETFs, futures, options, and general market analysis.

Guidelines:
- Be conversational yet concise (2-3 sentences for simple queries)
- Answer the user's specific question directly
- Use natural, friendly language
- Include relevant numbers/data when available
- If asked about specific prices or data, provide exact figures
- For general financial questions, give helpful educational responses
- Never give specific buy/sell recommendations without disclaimers
- You can discuss market concepts, trading strategies, and financial terms""",
                'estimated_cost': 0.0015,
                'timeout': 10
            },
            QueryComplexity.MODERATE: {
                'max_tokens': settings.ARIA_MODERATE_MAX_TOKENS if hasattr(settings, 'ARIA_MODERATE_MAX_TOKENS') else 400,
                'temperature': 0.5,
                'system_prompt': """You are ARIA, an expert AI trading assistant for the Atomik Trading platform.
You specialize in stocks, ETFs, futures, options, and comprehensive market analysis.

Guidelines:
- Be conversational and helpful
- Provide clear, actionable analysis with key points
- Answer the user's question directly, then elaborate if helpful
- Use natural language, not robotic responses
- Include relevant market context when discussing prices
- For general financial/trading questions, provide educational explanations
- You can discuss: market trends, trading concepts, investment strategies, economic factors
- For predictions/recommendations, always include appropriate caveats
- Use bullet points sparingly, only when listing multiple items""",
                'estimated_cost': 0.003,
                'timeout': 15
            },
            QueryComplexity.COMPLEX: {
                'max_tokens': settings.ARIA_COMPLEX_MAX_TOKENS if hasattr(settings, 'ARIA_COMPLEX_MAX_TOKENS') else 800,
                'temperature': 0.6,
                'system_prompt': """You are ARIA, an expert AI trading assistant for the Atomik Trading platform.
You specialize in stocks, ETFs, futures, options, and deep market analysis.

Guidelines:
- Be conversational while providing comprehensive analysis
- Answer the user's question thoroughly with supporting context
- Structure longer responses with clear sections
- Include relevant market data, historical context, and analysis
- For complex financial questions, explain concepts clearly
- You can discuss: market dynamics, technical analysis, fundamental analysis, economic indicators, trading psychology
- When speculating about markets, clearly distinguish between facts and opinions
- Include appropriate risk disclaimers for any investment-related advice
- Consider multiple perspectives when analyzing market situations""",
                'estimated_cost': 0.008,
                'timeout': 30
            }
        }

        return configs.get(complexity, configs[QueryComplexity.MODERATE])

    def classify_query_complexity(self, query: str, has_market_data: bool = False) -> QueryComplexity:
        """
        Automatically classify query complexity based on content

        Args:
            query: User's query text
            has_market_data: Whether market data is involved

        Returns:
            Query complexity level
        """
        query_lower = query.lower()

        # Simple queries - direct data requests
        simple_keywords = ['price', 'cost', 'worth', 'value', 'how much', 'what is']
        if any(keyword in query_lower for keyword in simple_keywords) and len(query.split()) < 10:
            return QueryComplexity.SIMPLE

        # Complex queries - analysis and recommendations
        complex_keywords = ['analyze', 'recommend', 'should i', 'portfolio', 'strategy',
                          'compare', 'risk', 'forecast', 'predict', 'evaluate']
        if any(keyword in query_lower for keyword in complex_keywords):
            return QueryComplexity.COMPLEX

        # Default to moderate
        return QueryComplexity.MODERATE

    async def analyze_market_data(
        self,
        query: str,
        market_data: Optional[Dict[str, Any]] = None,
        user_context: Optional[Dict[str, Any]] = None,
        complexity: Optional[QueryComplexity] = None
    ) -> Dict[str, Any]:
        """
        Generate intelligent market analysis using configured LLM provider

        Args:
            query: User's question
            market_data: Market data from Data Hub
            user_context: User's trading context
            complexity: Override complexity classification

        Returns:
            Response with text and metadata
        """
        if not self.client or self.provider == "none":
            return {
                "success": False,
                "error": "LLM service not configured. Please configure LLM_PROVIDER and API key.",
                "text": "I'm unable to provide analysis without AI configuration."
            }

        try:
            # Auto-classify complexity if not provided
            if complexity is None:
                complexity = self.classify_query_complexity(query, bool(market_data))

            # Get configuration
            config = self.get_query_config(complexity)

            # Build context-aware prompt
            prompt = self._build_analysis_prompt(query, market_data, user_context)

            logger.info(f"Sending {complexity.value} query to {self.provider} (max_tokens: {config['max_tokens']})")

            # Route to appropriate provider
            if self.provider == "groq":
                return await self._call_groq(prompt, config, complexity)
            elif self.provider == "anthropic":
                return await self._call_anthropic(prompt, config, complexity)
            else:
                return {
                    "success": False,
                    "error": f"Unknown provider: {self.provider}",
                    "text": self._get_fallback_response(query, market_data)
                }

        except Exception as e:
            logger.error(f"Unexpected LLM error: {e}")
            return {
                "success": False,
                "error": str(e),
                "text": self._get_fallback_response(query, market_data)
            }

    async def _call_groq(
        self,
        prompt: str,
        config: Dict[str, Any],
        complexity: QueryComplexity
    ) -> Dict[str, Any]:
        """Call Groq API (OpenAI-compatible)"""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                max_tokens=config['max_tokens'],
                temperature=config['temperature'],
                messages=[
                    {"role": "system", "content": config['system_prompt']},
                    {"role": "user", "content": prompt}
                ]
            )

            response_text = response.choices[0].message.content if response.choices else ""

            # Update usage stats
            input_tokens = response.usage.prompt_tokens if response.usage else 0
            output_tokens = response.usage.completion_tokens if response.usage else 0
            self._update_usage_stats_manual(input_tokens, output_tokens, config['estimated_cost'])

            return {
                "success": True,
                "text": response_text,
                "complexity": complexity.value,
                "tokens_used": {
                    "input": input_tokens,
                    "output": output_tokens
                },
                "estimated_cost": config['estimated_cost'],
                "model": self.model,
                "provider": "groq"
            }

        except Exception as e:
            logger.error(f"Groq API error: {e}")
            return {
                "success": False,
                "error": f"Groq API error: {str(e)}",
                "text": "I encountered an error with the AI service. Please try again."
            }

    async def _call_anthropic(
        self,
        prompt: str,
        config: Dict[str, Any],
        complexity: QueryComplexity
    ) -> Dict[str, Any]:
        """Call Anthropic Claude API"""
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=config['max_tokens'],
                temperature=config['temperature'],
                system=config['system_prompt'],
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )

            response_text = response.content[0].text if response.content else ""

            # Update usage stats
            self._update_usage_stats(response.usage, config['estimated_cost'])

            return {
                "success": True,
                "text": response_text,
                "complexity": complexity.value,
                "tokens_used": {
                    "input": response.usage.input_tokens,
                    "output": response.usage.output_tokens
                },
                "estimated_cost": config['estimated_cost'],
                "model": self.model,
                "provider": "anthropic"
            }

        except Exception as e:
            logger.error(f"Anthropic API error: {e}")
            return {
                "success": False,
                "error": f"Anthropic API error: {str(e)}",
                "text": "I encountered an error with the AI service. Please try again."
            }

    def _build_analysis_prompt(
        self,
        query: str,
        market_data: Optional[Dict[str, Any]],
        user_context: Optional[Dict[str, Any]]
    ) -> str:
        """
        Build a comprehensive prompt with all context

        Args:
            query: User's question
            market_data: Market data if available
            user_context: User trading context

        Returns:
            Formatted prompt for Claude
        """
        prompt_parts = [f"User Query: {query}"]

        # Add market data if available
        if market_data:
            prompt_parts.append("\n--- Market Data ---")

            if "price_data" in market_data:
                price = market_data["price_data"].get("data", {})
                if price:
                    symbol = price.get('symbol', 'Unknown')
                    prompt_parts.append(f"Symbol: {symbol}")
                    prompt_parts.append(f"Current Price: ${price.get('price', 0):.2f}")
                    change = price.get('change', 0)
                    change_pct = price.get('change_percent', 0)
                    prompt_parts.append(f"Today's Change: ${change:+.2f} ({change_pct:+.2f}%)")
                    prompt_parts.append(f"Day High: ${price.get('day_high', 0):.2f}")
                    prompt_parts.append(f"Day Low: ${price.get('day_low', 0):.2f}")
                    prompt_parts.append(f"Open: ${price.get('open', 0):.2f}")
                    prompt_parts.append(f"Previous Close: ${price.get('previous_close', 0):.2f}")
                    vol = price.get('volume', 0)
                    if vol:
                        prompt_parts.append(f"Volume: {vol:,}")

                    # Add historical data if present
                    historical = price.get('historical', {})
                    if historical:
                        prompt_parts.append("\n--- Historical Data ---")
                        prompt_parts.append(f"Period: {historical.get('period', 'N/A')}")
                        prompt_parts.append(f"Period High: ${historical.get('high', 0):.2f}")
                        prompt_parts.append(f"Period Low: ${historical.get('low', 0):.2f}")
                        prompt_parts.append(f"Period Range: ${historical.get('range', 0):.2f}")
                        prompt_parts.append(f"Period Change: ${historical.get('period_change', 0):.2f} ({historical.get('period_change_percent', 0):+.2f}%)")
                        prompt_parts.append(f"Date Range: {historical.get('start_date', 'N/A')} to {historical.get('end_date', 'N/A')}")

            if "sentiment" in market_data:
                sentiment = market_data["sentiment"].get("data", {})
                if sentiment:
                    overall = sentiment.get("overall_sentiment", {})
                    prompt_parts.append(f"\nSentiment: {overall.get('label', 'N/A')} (score: {overall.get('score', 0):.2f})")

            if "news" in market_data:
                news = market_data["news"].get("data", {})
                if news and "articles" in news:
                    prompt_parts.append(f"Recent News: {len(news['articles'])} articles")

        # Add user context if available
        if user_context:
            prompt_parts.append("\n--- User Context ---")

            # Handle nested structure from context engine
            positions_data = user_context.get("current_positions", {})
            positions = positions_data.get("positions", {}) if isinstance(positions_data, dict) else {}

            if positions:
                prompt_parts.append(f"Current Positions: {len(positions)}")
                for symbol, data in list(positions.items())[:3]:  # Top 3
                    if isinstance(data, dict):
                        prompt_parts.append(f"  {symbol}: {data.get('quantity', 0)} shares @ ${data.get('avg_price', 0):.2f}")

            # Risk tolerance from preferences
            preferences = user_context.get("preferences", {})
            if "risk_tolerance" in preferences:
                prompt_parts.append(f"Risk Profile: {preferences['risk_tolerance']}")

            # Performance summary
            performance = user_context.get("performance_summary", {})
            if performance:
                daily_pnl = performance.get("daily_pnl", 0)
                if daily_pnl:
                    prompt_parts.append(f"Today's P&L: ${daily_pnl:+,.2f}")

            if "account_value" in user_context:
                prompt_parts.append(f"Account Value: ${user_context['account_value']:,.2f}")

        prompt_parts.append("\nProvide a helpful, conversational response based on the above data. Answer the user's specific question directly.")

        return "\n".join(prompt_parts)

    def _get_fallback_response(self, query: str, market_data: Optional[Dict[str, Any]]) -> str:
        """
        Generate basic response without LLM when API fails

        Args:
            query: User's query
            market_data: Available market data

        Returns:
            Fallback response text
        """
        query_lower = query.lower()

        # Try to provide basic data-driven response
        if market_data and "price_data" in market_data:
            price_info = market_data["price_data"].get("data", {})
            if price_info:
                symbol = price_info.get("symbol", "Asset")
                price = price_info.get("price", 0)
                change = price_info.get("change_percent", 0)

                if "price" in query_lower:
                    return f"{symbol} is currently at ${price:.2f}, {change:+.2f}% today."
                elif "buy" in query_lower or "sell" in query_lower:
                    direction = "up" if change > 0 else "down"
                    return f"{symbol} is {direction} {abs(change):.2f}% today at ${price:.2f}."

        # Generic fallback
        return "I'm having trouble accessing my analysis capabilities. The market data is available but I cannot provide detailed analysis at this moment."

    def _update_usage_stats(self, usage: Any, estimated_cost: float):
        """
        Track usage statistics for monitoring (Anthropic format)

        Args:
            usage: Claude API usage object
            estimated_cost: Estimated cost for this request
        """
        self.usage_stats["total_requests"] += 1
        self.usage_stats["total_input_tokens"] += usage.input_tokens
        self.usage_stats["total_output_tokens"] += usage.output_tokens
        self.usage_stats["estimated_cost"] += estimated_cost

        # Log every 10 requests
        if self.usage_stats["total_requests"] % 10 == 0:
            logger.info(f"LLM Usage Stats: {self.usage_stats}")

    def _update_usage_stats_manual(self, input_tokens: int, output_tokens: int, estimated_cost: float):
        """
        Track usage statistics manually (for Groq/OpenAI format)

        Args:
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            estimated_cost: Estimated cost for this request
        """
        self.usage_stats["total_requests"] += 1
        self.usage_stats["total_input_tokens"] += input_tokens
        self.usage_stats["total_output_tokens"] += output_tokens
        self.usage_stats["estimated_cost"] += estimated_cost

        # Log every 10 requests
        if self.usage_stats["total_requests"] % 10 == 0:
            logger.info(f"LLM Usage Stats: {self.usage_stats}")

    async def generate_trade_insight(
        self,
        symbol: str,
        action: str,
        market_data: Dict[str, Any]
    ) -> str:
        """
        Generate specific trading insights

        Args:
            symbol: Trading symbol
            action: Intended action (buy/sell/hold)
            market_data: Current market data

        Returns:
            Trading insight text
        """
        query = f"Should I {action} {symbol}? Provide a brief analysis."

        response = await self.analyze_market_data(
            query=query,
            market_data=market_data,
            complexity=QueryComplexity.MODERATE
        )

        return response.get("text", f"Unable to analyze {symbol} at this time.")

    async def explain_market_event(
        self,
        event_description: str,
        market_data: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Explain market events in user-friendly terms

        Args:
            event_description: Description of the event
            market_data: Related market data

        Returns:
            Explanation text
        """
        query = f"Explain this market event: {event_description}"

        response = await self.analyze_market_data(
            query=query,
            market_data=market_data,
            complexity=QueryComplexity.SIMPLE
        )

        return response.get("text", "Market event explanation unavailable.")

    def get_usage_report(self) -> Dict[str, Any]:
        """
        Get usage statistics report

        Returns:
            Usage statistics and estimated costs
        """
        return {
            "provider": self.provider,
            "model": self.model,
            "total_requests": self.usage_stats["total_requests"],
            "total_tokens": self.usage_stats["total_input_tokens"] + self.usage_stats["total_output_tokens"],
            "estimated_cost_usd": round(self.usage_stats["estimated_cost"], 4),
            "average_cost_per_request": round(
                self.usage_stats["estimated_cost"] / max(1, self.usage_stats["total_requests"]),
                4
            ),
            "is_configured": self.client is not None
        }

    # =========================================================================
    # Tool Calling Methods (LLM-First Architecture)
    # =========================================================================

    async def chat_with_tools(
        self,
        user_query: str,
        user_id: int,
        db: Any,
        use_premium: bool = False,
        conversation_history: Optional[List[Dict[str, str]]] = None
    ) -> Dict[str, Any]:
        """
        Main entry point for tool-calling architecture.
        Sends query to LLM with available tools, LLM decides which to call.

        Args:
            user_query: User's natural language query
            user_id: User's ID for context
            db: Database session
            use_premium: Use Anthropic (premium) instead of Groq (economy)
            conversation_history: Previous messages for context (enables multi-turn conversations)

        Returns:
            Response dictionary with text and metadata
        """
        from .aria_tools import (
            ARIA_TOOLS,
            get_tools_for_anthropic,
            get_tools_for_groq,
            ARIAToolExecutor,
            ARIA_TOOL_CALLING_SYSTEM_PROMPT
        )

        # Default to empty history if not provided
        if conversation_history is None:
            conversation_history = []

        # Determine which provider to use
        provider = "anthropic" if use_premium else self.provider

        # Check if we have a valid client
        if not self.client or self.provider == "none":
            return {
                "success": False,
                "text": "AI service not configured. Please check your LLM settings.",
                "tools_used": [],
                "provider": "none"
            }

        logger.info(f"Processing query with tools: '{user_query[:50]}...' using {provider}")

        try:
            # Initial LLM call with tools
            if provider == "anthropic":
                response = await self._call_anthropic_with_tools(
                    user_query,
                    get_tools_for_anthropic(),
                    ARIA_TOOL_CALLING_SYSTEM_PROMPT,
                    conversation_history
                )
            else:
                response = await self._call_groq_with_tools(
                    user_query,
                    get_tools_for_groq(),
                    ARIA_TOOL_CALLING_SYSTEM_PROMPT,
                    conversation_history
                )

            # Check if LLM wants to call tools
            tool_calls = response.get("tool_calls", [])

            if tool_calls:
                logger.info(f"LLM requested {len(tool_calls)} tool call(s)")

                # Execute the tools
                executor = ARIAToolExecutor(db, user_id)
                tool_results = await executor.execute_multiple(tool_calls)

                # Check for confirmation requirements
                for result in tool_results:
                    if result.get("result", {}).get("requires_confirmation"):
                        return {
                            "success": True,
                            "text": result["result"]["message"],
                            "requires_confirmation": True,
                            "pending_action": result["result"],
                            "tools_used": [tc.get("name", tc.get("function", {}).get("name")) for tc in tool_calls],
                            "provider": provider
                        }

                # Send tool results back to LLM for final response
                final_response = await self._get_final_response_with_tool_results(
                    user_query,
                    tool_calls,
                    tool_results,
                    provider,
                    ARIA_TOOL_CALLING_SYSTEM_PROMPT
                )

                return {
                    "success": True,
                    "text": final_response.get("text", ""),
                    "tools_used": [tc.get("name", tc.get("function", {}).get("name")) for tc in tool_calls],
                    "tool_results": tool_results,
                    "provider": provider
                }

            # No tools called - return direct response
            return {
                "success": True,
                "text": response.get("text", ""),
                "tools_used": [],
                "provider": provider
            }

        except Exception as e:
            logger.error(f"Tool calling error: {e}", exc_info=True)
            return {
                "success": False,
                "text": f"I encountered an error processing your request. Please try again.",
                "error": str(e),
                "tools_used": [],
                "provider": provider
            }

    async def _call_groq_with_tools(
        self,
        query: str,
        tools: List[Dict[str, Any]],
        system_prompt: str,
        conversation_history: Optional[List[Dict[str, str]]] = None
    ) -> Dict[str, Any]:
        """
        Call Groq API with tool definitions.

        Args:
            query: User query
            tools: List of tool definitions
            system_prompt: System prompt for the model
            conversation_history: Previous messages for context

        Returns:
            Response with potential tool calls
        """
        try:
            # Build messages with conversation history
            messages = [{"role": "system", "content": system_prompt}]

            # Add conversation history (previous turns)
            if conversation_history:
                messages.extend(conversation_history)

            # Add current user query
            messages.append({"role": "user", "content": query})

            response = self.client.chat.completions.create(
                model=self.model,
                max_tokens=1024,
                temperature=0.5,
                messages=messages,
                tools=tools,
                tool_choice="auto"
            )

            message = response.choices[0].message

            # Extract tool calls if any
            tool_calls = []
            if message.tool_calls:
                for tc in message.tool_calls:
                    tool_calls.append({
                        "id": tc.id,
                        "name": tc.function.name,
                        "arguments": tc.function.arguments
                    })

            return {
                "text": message.content or "",
                "tool_calls": tool_calls,
                "raw_response": response
            }

        except Exception as e:
            logger.error(f"Groq tool calling error: {e}")
            raise

    async def _call_anthropic_with_tools(
        self,
        query: str,
        tools: List[Dict[str, Any]],
        system_prompt: str,
        conversation_history: Optional[List[Dict[str, str]]] = None
    ) -> Dict[str, Any]:
        """
        Call Anthropic API with tool definitions.

        Args:
            query: User query
            tools: List of tool definitions in Anthropic format
            system_prompt: System prompt for the model
            conversation_history: Previous messages for context

        Returns:
            Response with potential tool calls
        """
        try:
            # Build messages with conversation history
            messages = []

            # Add conversation history (previous turns)
            if conversation_history:
                messages.extend(conversation_history)

            # Add current user query
            messages.append({"role": "user", "content": query})

            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=system_prompt,
                tools=tools,
                messages=messages
            )

            # Extract text and tool calls from Anthropic response
            text_content = ""
            tool_calls = []

            for block in response.content:
                if block.type == "text":
                    text_content = block.text
                elif block.type == "tool_use":
                    tool_calls.append({
                        "id": block.id,
                        "name": block.name,
                        "arguments": block.input
                    })

            return {
                "text": text_content,
                "tool_calls": tool_calls,
                "stop_reason": response.stop_reason,
                "raw_response": response
            }

        except Exception as e:
            logger.error(f"Anthropic tool calling error: {e}")
            raise

    async def _get_final_response_with_tool_results(
        self,
        original_query: str,
        tool_calls: List[Dict[str, Any]],
        tool_results: List[Dict[str, Any]],
        provider: str,
        system_prompt: str
    ) -> Dict[str, Any]:
        """
        Send tool results back to LLM to generate final response.

        Args:
            original_query: The user's original question
            tool_calls: Tool calls made by the LLM
            tool_results: Results from executing the tools
            provider: Which LLM provider to use
            system_prompt: System prompt

        Returns:
            Final response from LLM
        """
        try:
            if provider == "anthropic":
                return await self._get_anthropic_final_response(
                    original_query, tool_calls, tool_results, system_prompt
                )
            else:
                return await self._get_groq_final_response(
                    original_query, tool_calls, tool_results, system_prompt
                )
        except Exception as e:
            logger.error(f"Error getting final response: {e}")
            # Return a basic response based on tool results
            return self._format_fallback_tool_response(tool_results)

    async def _get_groq_final_response(
        self,
        original_query: str,
        tool_calls: List[Dict[str, Any]],
        tool_results: List[Dict[str, Any]],
        system_prompt: str
    ) -> Dict[str, Any]:
        """Get final response from Groq after tool execution"""
        # Build messages with tool results
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": original_query},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": tc["arguments"] if isinstance(tc["arguments"], str) else json.dumps(tc["arguments"])
                        }
                    }
                    for tc in tool_calls
                ]
            }
        ]

        # Add tool results
        for result in tool_results:
            messages.append({
                "role": "tool",
                "tool_call_id": result["tool_call_id"],
                "content": json.dumps(result["result"])
            })

        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=1024,
            temperature=0.5,
            messages=messages
        )

        return {
            "text": response.choices[0].message.content or "",
            "provider": "groq"
        }

    async def _get_anthropic_final_response(
        self,
        original_query: str,
        tool_calls: List[Dict[str, Any]],
        tool_results: List[Dict[str, Any]],
        system_prompt: str
    ) -> Dict[str, Any]:
        """Get final response from Anthropic after tool execution"""
        # Build messages with tool use and results
        messages = [
            {"role": "user", "content": original_query},
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": tc["name"],
                        "input": tc["arguments"] if isinstance(tc["arguments"], dict) else json.loads(tc["arguments"])
                    }
                    for tc in tool_calls
                ]
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": result["tool_call_id"],
                        "content": json.dumps(result["result"])
                    }
                    for result in tool_results
                ]
            }
        ]

        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=system_prompt,
            messages=messages
        )

        # Extract text from response
        text_content = ""
        for block in response.content:
            if block.type == "text":
                text_content = block.text

        return {
            "text": text_content,
            "provider": "anthropic"
        }

    def _format_fallback_tool_response(
        self,
        tool_results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Format a basic response from tool results when LLM fails.

        Args:
            tool_results: Results from tool execution

        Returns:
            Formatted response
        """
        parts = []

        for result in tool_results:
            name = result.get("name", "unknown")
            data = result.get("result", {})

            if "error" in data:
                parts.append(f"Error fetching {name}: {data['error']}")
            elif name == "get_stock_quote":
                symbol = data.get("symbol", "")
                price = data.get("price", 0)
                change_pct = data.get("change_percent", 0)
                direction = "up" if change_pct >= 0 else "down"
                parts.append(f"{symbol} is at ${price:.2f}, {direction} {abs(change_pct):.2f}% today.")
            elif name == "get_historical_data":
                symbol = data.get("symbol", "")
                if "open" in data and "close" in data:
                    parts.append(
                        f"{symbol} on {data.get('actual_date', 'requested date')}: "
                        f"Open ${data.get('open', 0):.2f}, Close ${data.get('close', 0):.2f}"
                    )
            elif name == "get_user_positions":
                total = data.get("total_positions", 0)
                parts.append(f"You have {total} open position(s).")
            elif name == "get_active_strategies":
                count = data.get("active_count", 0)
                parts.append(f"You have {count} active strategy(ies).")
            else:
                parts.append(f"Data retrieved for {name}.")

        return {
            "text": " ".join(parts) if parts else "I retrieved the data but couldn't format a response.",
            "provider": "fallback"
        }


# Helper class for response formatting
class ResponseFormatter:
    """
    Format LLM responses for different output contexts
    """

    @staticmethod
    def format_for_voice(text: str) -> str:
        """
        Format response for text-to-speech
        Remove markdown and special characters
        """
        # Remove markdown formatting
        text = text.replace("**", "").replace("*", "")
        text = text.replace("```", "").replace("`", "")
        text = text.replace("#", "").replace("-", "")

        # Remove emojis for voice
        import re
        emoji_pattern = re.compile("["
            u"\U0001F600-\U0001F64F"  # emoticons
            u"\U0001F300-\U0001F5FF"  # symbols & pictographs
            u"\U0001F680-\U0001F6FF"  # transport & map symbols
            u"\U0001F1E0-\U0001F1FF"  # flags
            "]+", flags=re.UNICODE)
        text = emoji_pattern.sub(r'', text)

        return text.strip()

    @staticmethod
    def format_for_chat(text: str) -> str:
        """
        Format response for chat display
        Keep markdown but ensure proper formatting
        """
        # Ensure bullet points have proper spacing
        lines = text.split('\n')
        formatted_lines = []

        for line in lines:
            if line.strip().startswith('•') or line.strip().startswith('-'):
                formatted_lines.append(line)
            else:
                formatted_lines.append(line)

        return '\n'.join(formatted_lines).strip()

    @staticmethod
    def add_confidence_indicator(text: str, confidence: float) -> str:
        """
        Add confidence indicator to response

        Args:
            text: Response text
            confidence: Confidence score (0-1)

        Returns:
            Text with confidence indicator
        """
        if confidence >= 0.8:
            indicator = "✅ High confidence"
        elif confidence >= 0.6:
            indicator = "⚠️ Moderate confidence"
        else:
            indicator = "❓ Low confidence"

        return f"{text}\n\n_{indicator}_"