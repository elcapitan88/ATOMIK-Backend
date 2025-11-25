# app/services/intent_service.py
import re
import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

# Common stock/ETF symbols for recognition
COMMON_SYMBOLS = {
    # Major ETFs
    'SPY', 'QQQ', 'IWM', 'DIA', 'VTI', 'VOO', 'VXX', 'UVXY',
    # Leveraged ETFs
    'SQQQ', 'TQQQ', 'SPXS', 'SPXL', 'UPRO', 'SDOW', 'UDOW',
    # Tech Giants
    'AAPL', 'MSFT', 'GOOGL', 'GOOG', 'AMZN', 'TSLA', 'META', 'NVDA', 'AMD', 'INTC', 'NFLX',
    # Finance
    'JPM', 'BAC', 'WFC', 'GS', 'V', 'MA', 'PYPL', 'SQ', 'COIN',
    # Energy
    'XOM', 'CVX', 'COP',
    # Other popular
    'BABA', 'NIO', 'PLTR', 'SOFI', 'RIVN', 'LCID',
    # Futures (common symbols)
    'ES', 'NQ', 'MES', 'MNQ', 'RTY', 'YM', 'CL', 'GC', 'SI', 'ZB', 'ZN'
}

# Market data related keywords
MARKET_KEYWORDS = {
    'price', 'trading', 'quote', 'doing', 'movement', 'moving', 'move',
    'up', 'down', 'green', 'red', 'positive', 'negative', 'flat',
    'range', 'high', 'low', 'open', 'close', 'volume',
    'today', 'yesterday', 'week', 'month', 'daily', 'weekly', 'monthly',
    'performance', 'performing', 'change', 'changed', 'percent'
}

@dataclass
class VoiceIntent:
    """Represents a parsed voice/text intent with parameters"""
    type: str
    parameters: Dict[str, Any]
    confidence: float
    requires_action: bool = True
    confirmed: bool = False
    
class IntentType(Enum):
    """Supported intent types for ARIA"""
    STRATEGY_CONTROL = "strategy_control"
    POSITION_QUERY = "position_query"
    TRADE_EXECUTION = "trade_execution"
    PERFORMANCE_QUERY = "performance_query"
    STRATEGY_STATUS = "strategy_status"
    ACCOUNT_CONTROL = "account_control"
    HELP_REQUEST = "help_request"
    GREETING = "greeting"
    # TEMPORARY: Market data intents - will migrate to atomik-data-hub
    MARKET_PRICE_QUERY = "market_price_query"
    MARKET_HISTORICAL_QUERY = "market_historical_query"
    UNKNOWN = "unknown"

class IntentService:
    """
    Advanced intent recognition service for ARIA voice and text commands
    
    Uses pattern matching combined with AI fallback for complex commands
    """
    
    def __init__(self):
        self.intent_patterns = self._initialize_patterns()
        self.confidence_threshold = 0.7

    def extract_symbol(self, text: str) -> Optional[str]:
        """
        Extract stock/ETF symbol from text.
        Handles: $SPY, $spy, SPY, spy, "spy", etc.

        Args:
            text: Raw user input text

        Returns:
            Uppercase symbol if found, None otherwise
        """
        # Pattern 1: $SYMBOL format (highest priority - explicit ticker notation)
        dollar_match = re.search(r'\$([a-zA-Z]{1,5})\b', text)
        if dollar_match:
            symbol = dollar_match.group(1).upper()
            logger.debug(f"Extracted symbol from $ notation: {symbol}")
            return symbol

        # Pattern 2: Check for known symbols (case-insensitive)
        words = re.findall(r'\b[a-zA-Z]{1,5}\b', text)
        for word in words:
            if word.upper() in COMMON_SYMBOLS:
                logger.debug(f"Extracted known symbol: {word.upper()}")
                return word.upper()

        # Pattern 3: Look for potential symbols near market keywords
        text_lower = text.lower()
        for keyword in MARKET_KEYWORDS:
            if keyword in text_lower:
                # Find 1-5 letter words that could be symbols
                potential_symbols = re.findall(r'\b([a-zA-Z]{2,5})\b', text_lower)
                for sym in potential_symbols:
                    sym_upper = sym.upper()
                    # Skip common English words
                    skip_words = {
                        'THE', 'AND', 'FOR', 'ARE', 'BUT', 'NOT', 'YOU', 'ALL', 'CAN',
                        'HAD', 'HER', 'WAS', 'ONE', 'OUR', 'OUT', 'DAY', 'GET', 'HAS',
                        'HIM', 'HIS', 'HOW', 'ITS', 'LET', 'MAY', 'NEW', 'NOW', 'OLD',
                        'SEE', 'WAY', 'WHO', 'BOY', 'DID', 'SAY', 'SHE', 'TOO', 'USE',
                        'WHAT', 'LAST', 'WEEK', 'THIS', 'THAT', 'WITH', 'HAVE', 'FROM',
                        'THEY', 'BEEN', 'CALL', 'WILL', 'EACH', 'MAKE', 'LIKE', 'TIME',
                        'VERY', 'WHEN', 'COME', 'MADE', 'FIND', 'TELL', 'ARIA', 'RANG',
                        'RANGE', 'PRICE', 'TODAY', 'ABOUT', 'DOING', 'HELLO', 'COULD',
                        'TELL', 'MOVE', 'MOVEMENT', 'TRADING', 'STOCK', 'MARKET'
                    }
                    if sym_upper not in skip_words:
                        logger.debug(f"Extracted potential symbol near keyword '{keyword}': {sym_upper}")
                        return sym_upper

        return None

    def extract_time_period(self, text: str) -> Optional[str]:
        """
        Extract time period from text.

        Returns: 'today', 'week', 'month', 'day', or None
        """
        text_lower = text.lower()

        if 'today' in text_lower or 'this morning' in text_lower:
            return 'today'
        elif 'yesterday' in text_lower:
            return 'day'
        elif 'last week' in text_lower or 'this week' in text_lower or 'weekly' in text_lower:
            return 'week'
        elif 'last month' in text_lower or 'this month' in text_lower or 'monthly' in text_lower:
            return 'month'
        elif 'daily' in text_lower:
            return 'day'

        return None

    def is_market_data_query(self, text: str) -> bool:
        """
        Check if the text appears to be a market data query.
        """
        text_lower = text.lower()

        # Check for $ symbol notation (definitive market query)
        if '$' in text:
            return True

        # Check for market keywords + potential symbol
        keyword_count = sum(1 for kw in MARKET_KEYWORDS if kw in text_lower)
        if keyword_count >= 1:
            # Also check if there's a potential symbol
            if self.extract_symbol(text):
                return True

        return False

    def _initialize_patterns(self) -> Dict[str, List[str]]:
        """Initialize regex patterns for intent recognition"""
        return {
            IntentType.STRATEGY_CONTROL.value: [
                # Turn on/activate strategy
                r"(?:turn on|activate|start|enable)\s+(?:my\s+)?(?P<strategy_name>[\w\s]+?)\s*strategy",
                r"(?:run|launch)\s+(?P<strategy_name>[\w\s]+?)(?:\s+strategy)?",
                
                # Turn off/disable strategy
                r"(?:turn off|disable|stop|deactivate)\s+(?:my\s+)?(?P<strategy_name>[\w\s]+?)\s*strategy",
                r"(?:halt|pause|kill)\s+(?P<strategy_name>[\w\s]+?)(?:\s+strategy)?",
                
                # General strategy control
                r"(?P<action>start|stop|pause|resume)\s+(?:all\s+)?(?:my\s+)?(?:trading\s+)?strategies",
                r"(?P<action>activate|deactivate)\s+(?P<strategy_name>[\w\s]+)"
            ],
            
            IntentType.POSITION_QUERY.value: [
                # Position queries
                r"(?:what'?s|show me|tell me about)\s+my\s+(?P<symbol>[A-Z]{1,5})\s+position",
                r"(?:how much|what)\s+(?P<symbol>[A-Z]{1,5})\s+(?:do I own|am I holding)",
                r"(?:show|display)\s+(?:my\s+)?(?P<symbol>[A-Z]{1,5})\s+holdings?",
                r"(?:position|holdings?)\s+(?:for\s+)?(?P<symbol>[A-Z]{1,5})",
                r"(?:what'?s|how'?s)\s+my\s+(?P<symbol>[A-Z]{1,5})\s+(?:doing|performing)",
                
                # General position queries
                r"(?:show|list|display)\s+(?:all\s+)?(?:my\s+)?(?:current\s+)?positions",
                r"what\s+(?:positions|holdings)\s+do\s+I\s+have",
                r"(?:portfolio|account)\s+summary"
            ],
            
            IntentType.TRADE_EXECUTION.value: [
                # Buy orders
                r"(?P<action>buy|purchase)\s+(?P<quantity>\d+)\s+(?:shares?\s+(?:of\s+)?)?(?P<symbol>[A-Z]{1,5})",
                r"(?P<action>go\s+long)\s+(?P<quantity>\d+)?\s*(?P<symbol>[A-Z]{1,5})",
                
                # Sell orders
                r"(?P<action>sell)\s+(?P<quantity>\d+)\s+(?:shares?\s+(?:of\s+)?)?(?P<symbol>[A-Z]{1,5})",
                r"(?P<action>short|go\s+short)\s+(?P<quantity>\d+)?\s*(?P<symbol>[A-Z]{1,5})",
                
                # Close positions
                r"(?P<action>close)\s+(?:my\s+)?(?P<symbol>[A-Z]{1,5})\s+position",
                r"(?P<action>exit|liquidate)\s+(?P<symbol>[A-Z]{1,5})",
                r"(?P<action>close)\s+(?:all\s+)?(?P<symbol>[A-Z]{1,5})\s+(?:trades|positions)",
                
                # Stop loss / Take profit
                r"(?:set\s+)?(?P<action>stop\s+loss)\s+(?:on\s+)?(?P<symbol>[A-Z]{1,5})\s+(?:at\s+)?(?P<price>[\d.]+)",
                r"(?:set\s+)?(?P<action>take\s+profit)\s+(?:on\s+)?(?P<symbol>[A-Z]{1,5})\s+(?:at\s+)?(?P<price>[\d.]+)"
            ],
            
            IntentType.PERFORMANCE_QUERY.value: [
                # Daily performance
                r"(?:how\s+(?:did\s+I\s+do|am\s+I\s+doing)\s+today|today'?s\s+(?:performance|results|pnl|p&l))",
                r"(?:what'?s\s+my\s+daily\s+(?:pnl|p&l|profit|loss))",
                r"(?:show\s+me\s+)?(?:today'?s|daily)\s+(?:trading\s+)?(?:results|performance)",
                
                # Weekly/Monthly performance
                r"(?:how\s+(?:did\s+I\s+do|am\s+I\s+doing)\s+this\s+(?P<period>week|month))",
                r"(?:what'?s\s+my\s+)?(?P<period>weekly|monthly)\s+(?:performance|pnl|p&l)",
                
                # General performance
                r"(?:how\s+am\s+I\s+performing|what'?s\s+my\s+performance)",
                r"(?:show\s+me\s+my\s+)?(?:trading\s+)?(?:statistics|stats|metrics)",
                r"(?:profit|loss)\s+(?:and\s+loss\s+)?(?:summary|report)"
            ],
            
            IntentType.STRATEGY_STATUS.value: [
                # Strategy status queries
                r"(?:what\s+strategies\s+are\s+(?:running|active)|show\s+(?:active\s+)?strategies)",
                r"(?:list|display)\s+(?:my\s+)?(?:active\s+|running\s+)?strategies",
                r"(?:which\s+strategies\s+are\s+(?:on|enabled|active))",
                r"(?:strategy\s+status|status\s+of\s+strategies)",
                r"(?:what'?s\s+running|what\s+strategies\s+do\s+I\s+have\s+active)"
            ],
            
            IntentType.ACCOUNT_CONTROL.value: [
                # High-risk account operations
                r"(?P<action>close\s+all)\s+(?:my\s+)?positions",
                r"(?P<action>liquidate)\s+(?:everything|all\s+positions|my\s+account)",
                r"(?P<action>stop\s+all)\s+(?:trading|strategies|everything)",
                r"(?P<action>emergency\s+stop|kill\s+switch)",
                r"(?P<action>disable\s+all)\s+(?:strategies|trading)"
            ],
            
            IntentType.HELP_REQUEST.value: [
                # Help and guidance
                r"(?:help|what\s+can\s+you\s+do|how\s+do\s+I)",
                r"(?:aria\s+)?(?:commands|options|features)",
                r"(?:how\s+(?:do\s+I|to))\s+.*",
                r"(?:can\s+you|are\s+you\s+able\s+to)\s+.*",
                r"(?:what'?s\s+possible|what\s+are\s+my\s+options)"
            ],
            
            IntentType.GREETING.value: [
                # Greetings and casual conversation
                r"(?:hello|hi|hey)\s+(?:aria|there)?",
                r"(?:good\s+(?:morning|afternoon|evening))",
                r"(?:how\s+are\s+you|what'?s\s+up)",
                r"(?:aria|assistant)(?:\s+hello|\s+hi)?",
                r"(?:thanks?|thank\s+you|thx)(?:\s+aria)?"
            ],

            # TEMPORARY: Market data patterns - will migrate to atomik-data-hub
            IntentType.MARKET_PRICE_QUERY.value: [
                # Price queries
                r"(?:what'?s|what\s+is)\s+(?:the\s+)?(?:price\s+of\s+)?(?P<symbol>[A-Z]{1,5})(?:\s+(?:trading|price|at))?",
                r"(?:how'?s|how\s+is)\s+(?P<symbol>[A-Z]{1,5})\s+(?:doing|trading|performing)?",
                r"(?:price|quote)\s+(?:of\s+|for\s+)?(?P<symbol>[A-Z]{1,5})",
                r"(?P<symbol>[A-Z]{1,5})\s+(?:stock\s+)?(?:price|quote)",
                r"(?:what'?s|get)\s+(?P<symbol>[A-Z]{1,5})\s+(?:trading\s+at|price)",
                r"(?:show\s+me\s+)?(?P<symbol>[A-Z]{1,5})\s+(?:stock|quote|price)",
                r"(?:how\s+much\s+is)\s+(?P<symbol>[A-Z]{1,5})"
            ],

            IntentType.MARKET_HISTORICAL_QUERY.value: [
                # Historical/range queries
                r"(?:what\s+was|what'?s)\s+(?P<symbol>[A-Z]{1,5})(?:'?s)?\s+(?:range|high|low)\s+(?:last\s+|this\s+)?(?P<period>week|month|day|today)?",
                r"(?P<symbol>[A-Z]{1,5})\s+(?:range|historical|history)\s+(?:last\s+|this\s+)?(?P<period>week|month|day)?",
                r"(?:show\s+me\s+)?(?P<symbol>[A-Z]{1,5})\s+(?:last\s+|this\s+)?(?P<period>week|month|day)'?s?\s+(?:data|range|history)?",
                r"(?:how\s+did)\s+(?P<symbol>[A-Z]{1,5})\s+(?:do|perform)\s+(?:last\s+|this\s+)?(?P<period>week|month)?",
                r"(?P<symbol>[A-Z]{1,5})\s+(?P<period>weekly|monthly|daily)\s+(?:range|performance|data)"
            ]
        }
    
    async def parse_voice_command(self, transcript: str) -> VoiceIntent:
        """
        Parse voice/text input and return structured intent
        
        Args:
            transcript: Raw user input text
            
        Returns:
            VoiceIntent with detected intent and parameters
        """
        transcript = transcript.strip().lower()
        
        # Try pattern matching first (fast and accurate for common commands)
        intent = self._pattern_match_intent(transcript)
        if intent.confidence >= self.confidence_threshold:
            return intent
        
        # Fallback to AI-based intent recognition for complex queries
        ai_intent = await self._ai_intent_recognition(transcript)
        
        # Return the higher confidence result
        return intent if intent.confidence > ai_intent.confidence else ai_intent
    
    def _pattern_match_intent(self, transcript: str) -> VoiceIntent:
        """Use regex patterns to identify intent and extract parameters"""
        best_match = None
        best_confidence = 0.0
        best_intent_type = IntentType.UNKNOWN.value
        best_parameters = {}
        
        for intent_type, patterns in self.intent_patterns.items():
            for pattern in patterns:
                match = re.search(pattern, transcript, re.IGNORECASE)
                if match:
                    # Calculate confidence based on match coverage
                    match_length = len(match.group(0))
                    transcript_length = len(transcript)
                    coverage = match_length / transcript_length
                    
                    # Boost confidence for exact keyword matches
                    if any(keyword in transcript for keyword in ['strategy', 'position', 'buy', 'sell']):
                        coverage += 0.2
                    
                    confidence = min(coverage, 1.0)
                    
                    if confidence > best_confidence:
                        best_confidence = confidence
                        best_intent_type = intent_type
                        best_match = match
                        best_parameters = match.groupdict() if match.groups else {}
        
        # Post-process parameters
        processed_parameters = self._process_parameters(
            best_intent_type, best_parameters, transcript
        )
        
        # Determine if action is required
        requires_action = self._requires_action(best_intent_type)
        
        return VoiceIntent(
            type=best_intent_type,
            parameters=processed_parameters,
            confidence=best_confidence,
            requires_action=requires_action
        )
    
    def _process_parameters(
        self, 
        intent_type: str, 
        raw_parameters: Dict[str, str], 
        transcript: str
    ) -> Dict[str, Any]:
        """Process and clean extracted parameters"""
        processed = {}
        
        for key, value in raw_parameters.items():
            if key == "strategy_name":
                processed[key] = self._clean_strategy_name(value)
            elif key == "symbol":
                processed[key] = value.upper()
            elif key == "quantity":
                try:
                    processed[key] = int(value)
                except ValueError:
                    processed[key] = value
            elif key == "price":
                try:
                    processed[key] = float(value)
                except ValueError:
                    processed[key] = value
            elif key == "action":
                processed[key] = self._normalize_action(value, intent_type)
            else:
                processed[key] = value.strip()
        
        # Add implicit parameters based on intent type
        if intent_type == IntentType.STRATEGY_CONTROL.value:
            if "action" not in processed:
                if any(word in transcript for word in ["turn on", "activate", "start", "enable", "run"]):
                    processed["action"] = "activate"
                elif any(word in transcript for word in ["turn off", "disable", "stop", "deactivate"]):
                    processed["action"] = "deactivate"
        
        return processed
    
    def _clean_strategy_name(self, name: str) -> str:
        """Clean and normalize strategy names"""
        # Remove common words
        cleaned = re.sub(r'\b(strategy|the|my|a|an)\b', '', name, flags=re.IGNORECASE)
        # Clean whitespace and capitalize
        cleaned = ' '.join(cleaned.split()).title()
        return cleaned
    
    def _normalize_action(self, action: str, intent_type: str) -> str:
        """Normalize action verbs to standard forms"""
        action = action.lower().strip()
        
        if intent_type == IntentType.STRATEGY_CONTROL.value:
            if action in ["turn on", "start", "enable", "run", "launch"]:
                return "activate"
            elif action in ["turn off", "stop", "disable", "halt", "pause", "kill"]:
                return "deactivate"
        
        elif intent_type == IntentType.TRADE_EXECUTION.value:
            if action in ["purchase", "go long"]:
                return "buy"
            elif action in ["go short"]:
                return "short"
            elif action in ["exit", "liquidate"]:
                return "close"
        
        return action
    
    def _requires_action(self, intent_type: str) -> bool:
        """Determine if intent requires action execution"""
        action_required_intents = [
            IntentType.STRATEGY_CONTROL.value,
            IntentType.TRADE_EXECUTION.value,
            IntentType.ACCOUNT_CONTROL.value
        ]
        return intent_type in action_required_intents
    
    async def _ai_intent_recognition(self, transcript: str) -> VoiceIntent:
        """
        Fallback AI-based intent recognition for complex queries

        Uses symbol extraction and market keyword detection when patterns fail.
        """
        # Try to detect if this is a market data query using our helpers
        if self.is_market_data_query(transcript):
            symbol = self.extract_symbol(transcript)
            period = self.extract_time_period(transcript)

            if symbol:
                # Determine if it's a historical query or current price query
                historical_keywords = {'range', 'week', 'month', 'last', 'history', 'historical', 'yesterday', 'daily', 'weekly', 'monthly'}
                is_historical = any(kw in transcript.lower() for kw in historical_keywords)

                if is_historical:
                    logger.info(f"[ARIA] AI fallback detected historical query for {symbol}, period={period}")
                    return VoiceIntent(
                        type=IntentType.MARKET_HISTORICAL_QUERY.value,
                        parameters={
                            "symbol": symbol,
                            "period": period or "week",
                            "raw_text": transcript
                        },
                        confidence=0.75,
                        requires_action=False
                    )
                else:
                    logger.info(f"[ARIA] AI fallback detected price query for {symbol}")
                    return VoiceIntent(
                        type=IntentType.MARKET_PRICE_QUERY.value,
                        parameters={
                            "symbol": symbol,
                            "raw_text": transcript
                        },
                        confidence=0.75,
                        requires_action=False
                    )

        # Check for greeting patterns more loosely
        greeting_words = {'hello', 'hi', 'hey', 'good morning', 'good afternoon', 'good evening'}
        if any(greet in transcript.lower() for greet in greeting_words):
            return VoiceIntent(
                type=IntentType.GREETING.value,
                parameters={},
                confidence=0.6,
                requires_action=False
            )

        # Default unknown intent - but still extract symbol if present for context
        symbol = self.extract_symbol(transcript)
        parameters = {"raw_text": transcript}
        if symbol:
            parameters["symbol"] = symbol

        return VoiceIntent(
            type=IntentType.UNKNOWN.value,
            parameters=parameters,
            confidence=0.1,
            requires_action=False
        )
    
    def validate_intent_parameters(self, intent: VoiceIntent) -> List[str]:
        """
        Validate intent parameters and return list of validation errors
        
        Returns:
            List of error messages, empty if valid
        """
        errors = []
        
        if intent.type == IntentType.STRATEGY_CONTROL.value:
            if not intent.parameters.get("strategy_name") and not intent.parameters.get("action"):
                errors.append("Strategy name or action is required")
        
        elif intent.type == IntentType.POSITION_QUERY.value:
            symbol = intent.parameters.get("symbol")
            if symbol and not re.match(r'^[A-Z]{1,5}$', symbol):
                errors.append(f"Invalid symbol format: {symbol}")
        
        elif intent.type == IntentType.TRADE_EXECUTION.value:
            symbol = intent.parameters.get("symbol")
            quantity = intent.parameters.get("quantity")
            
            if not symbol:
                errors.append("Symbol is required for trade execution")
            elif not re.match(r'^[A-Z]{1,5}$', symbol):
                errors.append(f"Invalid symbol format: {symbol}")
            
            if quantity and (not isinstance(quantity, int) or quantity <= 0):
                errors.append("Quantity must be a positive integer")
        
        return errors
    
    def get_intent_examples(self) -> Dict[str, List[str]]:
        """Get example commands for each intent type"""
        return {
            "Strategy Control": [
                "Turn on my Purple Reign strategy",
                "Disable the momentum strategy",
                "Start all strategies",
                "Stop Purple Reign"
            ],
            "Position Queries": [
                "What's my AAPL position?",
                "Show me my Tesla holdings",
                "How much MSFT do I own?",
                "Display all positions"
            ],
            "Trade Execution": [
                "Buy 100 shares of AAPL",
                "Sell 50 TSLA",
                "Close my NVDA position",
                "Set stop loss on MSFT at 300"
            ],
            "Performance": [
                "How did I do today?",
                "Show my daily P&L",
                "What's my weekly performance?",
                "Today's trading results"
            ],
            "Strategy Status": [
                "What strategies are running?",
                "Show active strategies",
                "List my strategies",
                "Strategy status"
            ],
            # TEMPORARY: Market data examples - will migrate to atomik-data-hub
            "Market Data": [
                "What's AAPL trading at?",
                "Price of TSLA",
                "How's SPY doing?",
                "NVDA stock price",
                "What was AAPL's range last week?",
                "MSFT weekly performance"
            ]
        }