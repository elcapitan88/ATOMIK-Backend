# app/services/llm_service.py
"""
LLM Service for ARIA - Multi-provider support
Supports Groq (economy) and Anthropic Claude (premium)
Implements smart configuration based on query complexity
"""

import logging
from typing import Dict, Any, Optional, List
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
        """Initialize Groq client (OpenAI-compatible API)"""
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
            self.model = getattr(settings, 'GROQ_MODEL', 'llama-3.1-70b-versatile')
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
                'max_tokens': settings.ARIA_SIMPLE_MAX_TOKENS if hasattr(settings, 'ARIA_SIMPLE_MAX_TOKENS') else 150,
                'temperature': 0.3,
                'system_prompt': """You are ARIA, an expert AI trading assistant.
                Be extremely concise. Answer in 1-2 sentences maximum.
                Focus only on the specific data requested.""",
                'estimated_cost': 0.0015,
                'timeout': 10
            },
            QueryComplexity.MODERATE: {
                'max_tokens': settings.ARIA_MODERATE_MAX_TOKENS if hasattr(settings, 'ARIA_MODERATE_MAX_TOKENS') else 300,
                'temperature': 0.5,
                'system_prompt': """You are ARIA, an expert AI trading assistant.
                Provide clear, actionable analysis with key points.
                Use bullet points for clarity. Be concise but thorough.""",
                'estimated_cost': 0.003,
                'timeout': 15
            },
            QueryComplexity.COMPLEX: {
                'max_tokens': settings.ARIA_COMPLEX_MAX_TOKENS if hasattr(settings, 'ARIA_COMPLEX_MAX_TOKENS') else 800,
                'temperature': 0.7,
                'system_prompt': """You are ARIA, an expert AI trading assistant.
                Provide comprehensive analysis with actionable insights.
                Consider multiple factors and explain your reasoning.
                Structure your response with clear sections.""",
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