# app/services/aria_assistant.py
from typing import Dict, List, Optional, Tuple, Any
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import json
import logging
import asyncio
from enum import Enum

from ..models.aria_context import (
    UserTradingProfile, 
    UserTradingSession, 
    ARIAInteraction, 
    ARIAContextCache
)
from ..models.user import User
from ..models.strategy import ActivatedStrategy
from ..models.broker import BrokerAccount
from .intent_service import IntentService, VoiceIntent
from .aria_context_engine import ARIAContextEngine
from .aria_action_executor import ARIAActionExecutor
from .llm_service import LLMService
# TEMPORARY: Market data service using yfinance - will migrate to atomik-data-hub
from .market_data_service import MarketDataService

logger = logging.getLogger(__name__)

class ARIAResponseType(Enum):
    TEXT = "text"
    VOICE = "voice"
    ACTION = "action"
    ERROR = "error"
    CONFIRMATION = "confirmation"

class ARIARiskLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class ARIAAssistant:
    """
    Main ARIA Assistant service - orchestrates all ARIA functionality

    This is the central coordinator that:
    1. Processes user input (voice/text)
    2. Understands intent and context
    3. Executes actions safely
    4. Generates intelligent responses
    5. Learns from interactions

    Supports two processing modes:
    - Tool Calling (recommended): LLM decides which tools to use
    - Legacy (deprecated): Rule-based intent detection
    """

    # Set to True to use LLM tool-calling architecture (recommended)
    USE_TOOL_CALLING = True

    def __init__(self, db: Session):
        self.db = db
        self.intent_service = IntentService()
        self.context_engine = ARIAContextEngine(db)
        self.action_executor = ARIAActionExecutor(db)
        self.llm_service = LLMService()
        # TEMPORARY: Market data service - will migrate to atomik-data-hub
        self.market_data_service = MarketDataService()
        
    async def process_user_input(
        self,
        user_id: int,
        input_text: str,
        input_type: str = "text",
        use_premium: bool = False
    ) -> Dict[str, Any]:
        """
        Main entry point for all ARIA interactions

        Args:
            user_id: User's database ID
            input_text: Raw user input (voice transcript or typed text)
            input_type: "voice" or "text"
            use_premium: Use premium LLM provider (Anthropic) instead of economy (Groq)

        Returns:
            Complete response with action results and ARIA reply
        """
        interaction_start = datetime.utcnow()
        logger.info(f"[ARIA] process_user_input started for user {user_id}: '{input_text[:100]}...'")

        # Route to tool-calling architecture if enabled
        if self.USE_TOOL_CALLING:
            logger.info("[ARIA] Using tool-calling architecture")
            return await self._process_with_tools(user_id, input_text, input_type, use_premium)

        # Legacy flow (deprecated) - kept for backward compatibility
        logger.info("[ARIA] Using legacy intent-based architecture")

        try:
            # 1. Get or create user trading profile
            logger.info(f"[ARIA] Step 1: Getting user profile for user {user_id}")
            user_profile = await self._get_or_create_user_profile(user_id)

            # 2. Get comprehensive user context
            logger.info(f"[ARIA] Step 2: Getting user context for user {user_id}")
            user_context = await self.context_engine.get_user_context(user_id)

            # 3. Process intent from user input
            logger.info(f"[ARIA] Step 3: Parsing intent from input")
            intent = await self.intent_service.parse_voice_command(input_text)
            logger.info(f"[ARIA] Intent detected: type={intent.type}, confidence={intent.confidence}, params={intent.parameters}")

            # 4. Determine risk level and confirmation requirements
            risk_level = self._assess_risk_level(intent, user_context)
            requires_confirmation = self._requires_confirmation(intent, risk_level)
            logger.info(f"[ARIA] Risk assessment: level={risk_level.value}, requires_confirmation={requires_confirmation}")
            
            # 5. Create interaction record
            logger.info(f"[ARIA] Step 5: Creating interaction record")
            interaction = await self._create_interaction_record(
                user_profile.id,
                input_text,
                input_type,
                intent,
                risk_level,
                requires_confirmation
            )
            logger.info(f"[ARIA] Interaction record created: id={interaction.id}")

            # 6. Handle confirmation flow if needed
            if requires_confirmation and not intent.confirmed:
                logger.info(f"[ARIA] Step 6: Confirmation required, returning confirmation request")
                return await self._handle_confirmation_request(interaction, intent, user_context)

            # 7. Execute action if required
            action_result = None
            if intent.requires_action:
                logger.info(f"[ARIA] Step 7: Executing action for intent type={intent.type}")
                action_result = await self.action_executor.execute_action(
                    user_id, intent, user_context
                )
                logger.info(f"[ARIA] Action result: success={action_result.get('success')}")

                # Update interaction with action results
                await self._update_interaction_action_result(
                    interaction, action_result
                )

            # 8. Generate ARIA response
            logger.info(f"[ARIA] Step 8: Generating ARIA response")
            response = await self._generate_aria_response(
                user_context, intent, action_result, input_type, original_query=input_text
            )
            logger.info(f"[ARIA] Response generated: '{response.get('text', 'N/A')[:100]}...'")

            # 9. Update interaction with response
            await self._update_interaction_response(interaction, response)

            # 10. Update user context cache
            await self.context_engine.update_context_cache(user_id)

            processing_time = int((datetime.utcnow() - interaction_start).total_seconds() * 1000)
            logger.info(f"[ARIA] Processing complete for user {user_id} in {processing_time}ms")

            return {
                "success": True,
                "interaction_id": interaction.id,
                "response": response,
                "action_result": action_result,
                "requires_confirmation": False,
                "risk_level": risk_level.value,
                "processing_time_ms": processing_time
            }

        except Exception as e:
            logger.error(f"[ARIA] Processing error for user {user_id}: {str(e)}")
            
            # Create error interaction record
            error_interaction = await self._create_error_interaction(
                user_id, input_text, input_type, str(e)
            )
            
            return {
                "success": False,
                "interaction_id": error_interaction.id,
                "error": str(e),
                "response": {
                    "text": "I'm sorry, I encountered an error processing your request. Please try again.",
                    "type": ARIAResponseType.ERROR.value
                },
                "processing_time_ms": int((datetime.utcnow() - interaction_start).total_seconds() * 1000)
            }
    
    async def _process_with_tools(
        self,
        user_id: int,
        input_text: str,
        input_type: str = "text",
        use_premium: bool = False
    ) -> Dict[str, Any]:
        """
        Process user input using LLM tool-calling architecture.

        This is the recommended approach where:
        1. User query goes directly to LLM with available tools
        2. LLM decides which tools (if any) to call
        3. Tool results are fed back to LLM for response generation

        Includes conversation memory for multi-turn context.

        Args:
            user_id: User's database ID
            input_text: Raw user input
            input_type: "voice" or "text"
            use_premium: Use premium LLM (Anthropic) vs economy (Groq)

        Returns:
            Complete response with action results and ARIA reply
        """
        from .aria_conversation_memory import conversation_memory

        interaction_start = datetime.utcnow()

        try:
            # 1. Get or create user profile (for interaction tracking)
            user_profile = await self._get_or_create_user_profile(user_id)

            # 2. Get conversation history for context
            conversation_history = conversation_memory.get_history(user_id)
            logger.info(f"[ARIA-Tools] Processing with {len(conversation_history)} previous messages")

            # 3. Use LLM with tools to process the query
            logger.info(f"[ARIA-Tools] Processing: '{input_text[:50]}...' with tools")

            response = await self.llm_service.chat_with_tools(
                user_query=input_text,
                user_id=user_id,
                db=self.db,
                use_premium=use_premium,
                conversation_history=conversation_history
            )

            # 3. Determine risk level and create interaction record
            # For tool-calling, we use LOW risk by default unless an action tool was used
            tools_used = response.get("tools_used", [])
            action_tools = ["activate_strategy", "deactivate_strategy"]
            has_action = any(t in action_tools for t in tools_used)

            risk_level = ARIARiskLevel.MEDIUM if has_action else ARIARiskLevel.LOW
            requires_confirmation = response.get("requires_confirmation", False)

            # Create a VoiceIntent for interaction tracking (simulated from tool response)
            intent = VoiceIntent(
                type="tool_calling",
                parameters={
                    "tools_used": tools_used,
                    "raw_query": input_text
                },
                confidence=0.9 if response.get("success") else 0.5,
                requires_action=has_action
            )

            # 4. Create interaction record
            interaction = await self._create_interaction_record(
                user_profile.id,
                input_text,
                input_type,
                intent,
                risk_level,
                requires_confirmation
            )

            # 5. Build response object
            processing_time = int((datetime.utcnow() - interaction_start).total_seconds() * 1000)

            response_obj = {
                "text": response.get("text", "I couldn't process that request."),
                "type": ARIAResponseType.CONFIRMATION.value if requires_confirmation else ARIAResponseType.TEXT.value,
                "tools_used": tools_used,
                "provider": response.get("provider", "unknown")
            }

            # Handle confirmation flow
            if requires_confirmation:
                pending_action = response.get("pending_action", {})
                response_obj["requires_confirmation"] = True
                response_obj["interaction_id"] = interaction.id
                response_obj["pending_action"] = pending_action

                await self._update_interaction_response(interaction, response_obj)

                return {
                    "success": True,
                    "interaction_id": interaction.id,
                    "response": response_obj,
                    "action_result": None,
                    "requires_confirmation": True,
                    "pending_action": pending_action,
                    "risk_level": risk_level.value,
                    "processing_time_ms": processing_time
                }

            # 6. Update interaction with response
            await self._update_interaction_response(interaction, response_obj)

            # 7. Store in conversation memory for multi-turn context
            conversation_memory.add_user_message(user_id, input_text)
            conversation_memory.add_assistant_message(
                user_id,
                response_obj["text"],
                tool_calls=tools_used
            )

            logger.info(f"[ARIA-Tools] Completed in {processing_time}ms, tools: {tools_used}")

            return {
                "success": response.get("success", True),
                "interaction_id": interaction.id,
                "response": response_obj,
                "action_result": None,
                "requires_confirmation": False,
                "risk_level": risk_level.value,
                "processing_time_ms": processing_time,
                "error": response.get("error")
            }

        except Exception as e:
            logger.error(f"[ARIA-Tools] Error for user {user_id}: {str(e)}", exc_info=True)

            # Create error interaction
            error_interaction = await self._create_error_interaction(
                user_id, input_text, input_type, str(e)
            )

            processing_time = int((datetime.utcnow() - interaction_start).total_seconds() * 1000)

            return {
                "success": False,
                "interaction_id": error_interaction.id,
                "error": str(e),
                "response": {
                    "text": "I'm sorry, I encountered an error processing your request. Please try again.",
                    "type": ARIAResponseType.ERROR.value
                },
                "processing_time_ms": processing_time
            }

    async def execute_voice_command(
        self,
        user_id: int,
        command: str
    ) -> Dict[str, Any]:
        """
        Specialized method for voice commands with optimized processing
        """
        return await self.process_user_input(user_id, command, "voice")
    
    async def handle_confirmation_response(
        self,
        user_id: int,
        interaction_id: int,
        confirmed: bool
    ) -> Dict[str, Any]:
        """
        Handle user's response to a confirmation request
        """
        logger.info(f"[ARIA] handle_confirmation_response: user={user_id}, interaction={interaction_id}, confirmed={confirmed}")

        try:
            # Get original interaction
            interaction = self.db.query(ARIAInteraction).filter(
                ARIAInteraction.id == interaction_id
            ).first()

            if not interaction:
                logger.error(f"[ARIA] Interaction {interaction_id} not found")
                raise ValueError(f"Interaction {interaction_id} not found")
            
            # Update confirmation status
            interaction.confirmation_provided = confirmed
            
            if confirmed:
                # Execute the original action
                intent = VoiceIntent(
                    type=interaction.detected_intent,
                    parameters=interaction.intent_parameters,
                    confidence=interaction.intent_confidence,
                    confirmed=True
                )
                
                user_context = await self.context_engine.get_user_context(user_id)
                action_result = await self.action_executor.execute_action(
                    user_id, intent, user_context
                )
                
                # Update interaction with results
                await self._update_interaction_action_result(interaction, action_result)

                response = await self._generate_aria_response(
                    user_context, intent, action_result, "text", original_query=""
                )
                
                await self._update_interaction_response(interaction, response)
                
                return {
                    "success": True,
                    "confirmed": True,
                    "action_result": action_result,
                    "response": response
                }
            else:
                # User declined - generate cancellation response
                response = {
                    "text": "Action cancelled. Is there anything else I can help you with?",
                    "type": ARIAResponseType.TEXT.value
                }
                
                await self._update_interaction_response(interaction, response)
                
                return {
                    "success": True,
                    "confirmed": False,
                    "response": response
                }
                
        except Exception as e:
            logger.error(f"Confirmation handling error: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "response": {
                    "text": "I encountered an error processing your confirmation. Please try again.",
                    "type": ARIAResponseType.ERROR.value
                }
            }
    
    async def get_user_context_summary(self, user_id: int) -> Dict[str, Any]:
        """
        Get a comprehensive summary of user's trading context for ARIA
        """
        return await self.context_engine.get_user_context(user_id)
    
    async def _get_or_create_user_profile(self, user_id: int) -> UserTradingProfile:
        """Get existing user profile or create a new one"""
        profile = self.db.query(UserTradingProfile).filter(
            UserTradingProfile.user_id == user_id
        ).first()
        
        if not profile:
            profile = UserTradingProfile(
                user_id=user_id,
                risk_tolerance="moderate",
                created_at=datetime.utcnow()
            )
            self.db.add(profile)
            self.db.commit()
            self.db.refresh(profile)
            
        return profile
    
    def _assess_risk_level(
        self, 
        intent: VoiceIntent, 
        user_context: Dict[str, Any]
    ) -> ARIARiskLevel:
        """
        Assess the risk level of the requested action
        """
        if intent.type == "position_query" or intent.type == "strategy_status":
            return ARIARiskLevel.LOW
        
        if intent.type == "strategy_control":
            return ARIARiskLevel.MEDIUM
        
        if intent.type == "trade_execution":
            # Check position size
            if intent.parameters.get("quantity", 0) > 1000:  # Large position
                return ARIARiskLevel.HIGH
            return ARIARiskLevel.MEDIUM
        
        if intent.type == "account_control":
            return ARIARiskLevel.CRITICAL
        
        return ARIARiskLevel.LOW
    
    def _requires_confirmation(
        self, 
        intent: VoiceIntent, 
        risk_level: ARIARiskLevel
    ) -> bool:
        """
        Determine if action requires user confirmation
        """
        # Always require confirmation for medium risk and above
        if risk_level in [ARIARiskLevel.MEDIUM, ARIARiskLevel.HIGH, ARIARiskLevel.CRITICAL]:
            return True
        
        # No confirmation needed for queries
        if intent.type in ["position_query", "strategy_status", "performance_query"]:
            return False
        
        return False
    
    async def _create_interaction_record(
        self,
        user_profile_id: int,
        raw_input: str,
        input_type: str,
        intent: VoiceIntent,
        risk_level: ARIARiskLevel,
        requires_confirmation: bool
    ) -> ARIAInteraction:
        """Create a new interaction record"""
        interaction = ARIAInteraction(
            user_profile_id=user_profile_id,
            interaction_type=input_type,
            input_method=input_type,
            raw_input=raw_input,
            detected_intent=intent.type,
            intent_confidence=intent.confidence,
            intent_parameters=intent.parameters,
            required_confirmation=requires_confirmation,
            risk_level=risk_level.value,
            timestamp=datetime.utcnow()
        )
        
        self.db.add(interaction)
        self.db.commit()
        self.db.refresh(interaction)
        
        return interaction
    
    async def _create_error_interaction(
        self,
        user_id: int,
        raw_input: str,
        input_type: str,
        error_message: str
    ) -> ARIAInteraction:
        """Create error interaction record"""
        user_profile = await self._get_or_create_user_profile(user_id)
        
        interaction = ARIAInteraction(
            user_profile_id=user_profile.id,
            interaction_type=input_type,
            input_method=input_type,
            raw_input=raw_input,
            aria_response=f"Error: {error_message}",
            response_type=ARIAResponseType.ERROR.value,
            action_success=False,
            timestamp=datetime.utcnow()
        )
        
        self.db.add(interaction)
        self.db.commit()
        self.db.refresh(interaction)
        
        return interaction
    
    async def _handle_confirmation_request(
        self,
        interaction: ARIAInteraction,
        intent: VoiceIntent,
        user_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate confirmation request for risky actions"""
        confirmation_text = self._generate_confirmation_text(intent, user_context)
        
        response = {
            "text": confirmation_text,
            "type": ARIAResponseType.CONFIRMATION.value,
            "requires_confirmation": True,
            "interaction_id": interaction.id,
            "intent_summary": self._generate_intent_summary(intent)
        }
        
        await self._update_interaction_response(interaction, response)
        
        return {
            "success": True,
            "requires_confirmation": True,
            "response": response,
            "interaction_id": interaction.id
        }
    
    def _generate_confirmation_text(
        self, 
        intent: VoiceIntent, 
        user_context: Dict[str, Any]
    ) -> str:
        """Generate appropriate confirmation text based on intent"""
        if intent.type == "strategy_control":
            strategy_name = intent.parameters.get("strategy_name", "strategy")
            action = intent.parameters.get("action", "activate")
            
            return f"I'll {action} your {strategy_name} strategy. This will affect your automated trading. Confirm: Yes or No?"
        
        elif intent.type == "trade_execution":
            action = intent.parameters.get("action", "buy")
            quantity = intent.parameters.get("quantity", "")
            symbol = intent.parameters.get("symbol", "")
            
            return f"I'll {action} {quantity} shares of {symbol}. Confirm this trade: Yes or No?"
        
        elif intent.type == "account_control":
            action = intent.parameters.get("action", "")
            return f"I'll {action} for your account. This is a high-risk action. Confirm: Yes or No?"
        
        return "Confirm this action: Yes or No?"
    
    def _generate_intent_summary(self, intent: VoiceIntent) -> Dict[str, Any]:
        """Generate human-readable intent summary"""
        return {
            "action": intent.type,
            "parameters": intent.parameters,
            "confidence": intent.confidence,
            "description": self._intent_to_description(intent)
        }
    
    def _intent_to_description(self, intent: VoiceIntent) -> str:
        """Convert intent to human-readable description"""
        if intent.type == "strategy_control":
            strategy = intent.parameters.get("strategy_name", "strategy")
            action = intent.parameters.get("action", "control")
            return f"{action.title()} {strategy} strategy"
        
        elif intent.type == "trade_execution":
            action = intent.parameters.get("action", "trade")
            symbol = intent.parameters.get("symbol", "")
            quantity = intent.parameters.get("quantity", "")
            return f"{action.title()} {quantity} {symbol}"
        
        return intent.type.replace("_", " ").title()
    
    async def _update_interaction_action_result(
        self,
        interaction: ARIAInteraction,
        action_result: Dict[str, Any]
    ):
        """Update interaction with action execution results"""
        interaction.action_attempted = action_result.get("action_type")
        interaction.action_parameters = action_result.get("parameters")
        interaction.action_success = action_result.get("success", False)
        interaction.action_result = action_result
        interaction.action_timestamp = datetime.utcnow()
        
        self.db.commit()
    
    async def _update_interaction_response(
        self,
        interaction: ARIAInteraction,
        response: Dict[str, Any]
    ):
        """Update interaction with ARIA response"""
        interaction.aria_response = response.get("text", "")
        interaction.response_type = response.get("type", ARIAResponseType.TEXT.value)
        interaction.response_timestamp = datetime.utcnow()
        
        self.db.commit()
    
    async def _generate_aria_response(
        self,
        user_context: Dict[str, Any],
        intent: VoiceIntent,
        action_result: Optional[Dict[str, Any]],
        input_type: str,
        original_query: str = ""
    ) -> Dict[str, Any]:
        """
        Generate intelligent ARIA response based on context and results
        Uses LLM for enhanced responses when available
        """

        # If action was executed, generate result-based response
        if action_result:
            if action_result.get("success"):
                return self._generate_success_response(intent, action_result, input_type)
            else:
                return self._generate_error_response(intent, action_result, input_type)

        # Query responses - try LLM first for richer responses
        if intent.type == "position_query":
            return await self._generate_position_response_with_llm(user_context, intent, input_type, original_query)

        elif intent.type == "strategy_status":
            return self._generate_strategy_status_response(user_context, intent, input_type)

        elif intent.type == "performance_query":
            return await self._generate_performance_response_with_llm(user_context, intent, input_type, original_query)

        elif intent.type == "help_request" or intent.type == "greeting":
            return await self._generate_conversational_response(user_context, intent, input_type, original_query)

        # TEMPORARY: Market data queries - will migrate to atomik-data-hub
        elif intent.type == "market_price_query":
            return await self._generate_market_price_response(intent, original_query)

        elif intent.type == "market_historical_query":
            return await self._generate_market_historical_response(intent, original_query)

        # General financial/trading questions (LLM-powered)
        elif intent.type == "general_financial_query":
            return await self._generate_general_financial_response(user_context, intent, original_query)

        elif intent.type == "unknown":
            # Check if the unknown intent contains a symbol - if so, try to help with market data
            symbol = intent.parameters.get("symbol")
            if symbol:
                logger.info(f"[ARIA] Unknown intent contains symbol {symbol}, attempting market data fetch")
                return await self._generate_smart_market_response(symbol, original_query, user_context)
            # Use LLM to handle unknown intents conversationally
            return await self._generate_conversational_response(user_context, intent, input_type, original_query)

        # Default response
        return {
            "text": "I understand your request. How else can I help you with your trading?",
            "type": ARIAResponseType.TEXT.value
        }

    async def _generate_position_response_with_llm(
        self,
        user_context: Dict[str, Any],
        intent: VoiceIntent,
        input_type: str,
        original_query: str
    ) -> Dict[str, Any]:
        """Generate position response with optional LLM enhancement"""
        # Get basic position data
        basic_response = self._generate_position_response(user_context, intent, input_type)

        # If LLM is available, enhance the response
        if self.llm_service.client and original_query:
            try:
                llm_result = await self.llm_service.analyze_market_data(
                    query=original_query,
                    user_context=user_context
                )
                if llm_result.get("success"):
                    return {
                        "text": llm_result["text"],
                        "type": ARIAResponseType.TEXT.value,
                        "position_data": basic_response.get("position_data"),
                        "llm_enhanced": True,
                        "provider": llm_result.get("provider")
                    }
            except Exception as e:
                logger.warning(f"LLM enhancement failed, using template: {e}")

        return basic_response

    async def _generate_performance_response_with_llm(
        self,
        user_context: Dict[str, Any],
        intent: VoiceIntent,
        input_type: str,
        original_query: str
    ) -> Dict[str, Any]:
        """Generate performance response with optional LLM enhancement"""
        # Get basic performance data
        basic_response = self._generate_performance_response(user_context, intent, input_type)

        # If LLM is available, enhance the response
        if self.llm_service.client and original_query:
            try:
                llm_result = await self.llm_service.analyze_market_data(
                    query=original_query,
                    user_context=user_context
                )
                if llm_result.get("success"):
                    return {
                        "text": llm_result["text"],
                        "type": ARIAResponseType.TEXT.value,
                        "performance_data": basic_response.get("performance_data"),
                        "llm_enhanced": True,
                        "provider": llm_result.get("provider")
                    }
            except Exception as e:
                logger.warning(f"LLM enhancement failed, using template: {e}")

        return basic_response

    async def _generate_conversational_response(
        self,
        user_context: Dict[str, Any],
        intent: VoiceIntent,
        input_type: str,
        original_query: str
    ) -> Dict[str, Any]:
        """Generate conversational response using LLM"""
        if self.llm_service.client and original_query:
            try:
                llm_result = await self.llm_service.analyze_market_data(
                    query=original_query,
                    user_context=user_context
                )
                if llm_result.get("success"):
                    return {
                        "text": llm_result["text"],
                        "type": ARIAResponseType.TEXT.value,
                        "llm_enhanced": True,
                        "provider": llm_result.get("provider")
                    }
            except Exception as e:
                logger.warning(f"LLM conversational response failed: {e}")

        # Fallback responses
        if intent.type == "greeting":
            return {
                "text": "Hello! I'm ARIA, your AI trading assistant. I can help you manage strategies, check positions, and analyze your trading performance. What would you like to do?",
                "type": ARIAResponseType.TEXT.value
            }
        elif intent.type == "help_request":
            return {
                "text": "I can help you with: activating/deactivating strategies, checking your positions, viewing performance, and executing trades. Try saying 'show my positions' or 'how did I do today?'",
                "type": ARIAResponseType.TEXT.value
            }

        return {
            "text": "I'm not sure I understood that. Could you rephrase? I can help with positions, strategies, performance, and trades.",
            "type": ARIAResponseType.TEXT.value
        }
    
    def _generate_success_response(
        self, 
        intent: VoiceIntent, 
        action_result: Dict[str, Any], 
        input_type: str
    ) -> Dict[str, Any]:
        """Generate response for successful actions"""
        if intent.type == "strategy_control":
            strategy_name = intent.parameters.get("strategy_name", "strategy")
            action = intent.parameters.get("action", "updated")
            text = f"✅ {strategy_name} strategy has been {action}. I'll monitor its performance for you."
        
        elif intent.type == "trade_execution":
            symbol = intent.parameters.get("symbol", "")
            action = intent.parameters.get("action", "executed")
            text = f"✅ Trade {action} for {symbol}. Order details: {action_result.get('order_id', 'Processing')}"
        
        else:
            text = f"✅ Action completed successfully."
        
        return {
            "text": text,
            "type": ARIAResponseType.TEXT.value,
            "action_result": action_result
        }
    
    def _generate_error_response(
        self, 
        intent: VoiceIntent, 
        action_result: Dict[str, Any], 
        input_type: str
    ) -> Dict[str, Any]:
        """Generate response for failed actions"""
        error_message = action_result.get("error", "Unknown error occurred")
        
        text = f"❌ I couldn't complete that action. {error_message}. Would you like me to try again or help you with something else?"
        
        return {
            "text": text,
            "type": ARIAResponseType.ERROR.value,
            "error_details": action_result
        }
    
    def _generate_position_response(
        self, 
        user_context: Dict[str, Any], 
        intent: VoiceIntent, 
        input_type: str
    ) -> Dict[str, Any]:
        """Generate response for position queries"""
        symbol = intent.parameters.get("symbol", "").upper()
        positions = user_context.get("current_positions", {})
        
        if symbol in positions:
            position = positions[symbol]
            text = f"📊 Your {symbol} position: {position.get('quantity', 0)} shares, P&L: ${position.get('unrealized_pnl', 0):.2f}"
        else:
            text = f"📊 You don't currently have a {symbol} position."
        
        return {
            "text": text,
            "type": ARIAResponseType.TEXT.value,
            "position_data": positions.get(symbol)
        }
    
    def _generate_strategy_status_response(
        self, 
        user_context: Dict[str, Any], 
        intent: VoiceIntent, 
        input_type: str
    ) -> Dict[str, Any]:
        """Generate response for strategy status queries"""
        strategies = user_context.get("active_strategies", [])
        
        if strategies:
            active_count = len([s for s in strategies if s.get("is_active")])
            text = f"🤖 You have {active_count} active strategies running: {', '.join([s.get('name', 'Unknown') for s in strategies[:3]])}"
            if len(strategies) > 3:
                text += f" and {len(strategies) - 3} more."
        else:
            text = "🤖 No strategies are currently active. Would you like me to help you activate one?"
        
        return {
            "text": text,
            "type": ARIAResponseType.TEXT.value,
            "strategy_data": strategies
        }
    
    def _generate_performance_response(
        self, 
        user_context: Dict[str, Any], 
        intent: VoiceIntent, 
        input_type: str
    ) -> Dict[str, Any]:
        """Generate response for performance queries"""
        performance = user_context.get("performance_summary", {})
        
        daily_pnl = performance.get("daily_pnl", 0)
        total_trades = performance.get("total_trades_today", 0)
        
        if daily_pnl > 0:
            emoji = "📈"
            status = "up"
        elif daily_pnl < 0:
            emoji = "📉"
            status = "down"
        else:
            emoji = "➡️"
            status = "flat"
        
        text = f"{emoji} Today you're {status} ${abs(daily_pnl):.2f} with {total_trades} trades."

        return {
            "text": text,
            "type": ARIAResponseType.TEXT.value,
            "performance_data": performance
        }

    # ================================================================
    # TEMPORARY: Market Data Methods - will migrate to atomik-data-hub
    # ================================================================

    async def _generate_market_price_response(
        self,
        intent: VoiceIntent,
        original_query: str
    ) -> Dict[str, Any]:
        """
        TEMPORARY: Generate market price response using yfinance

        This will be migrated to atomik-data-hub once data sources are configured.
        """
        symbol = intent.parameters.get("symbol", "").upper()

        if not symbol:
            return {
                "text": "I couldn't identify the stock symbol. Please try again with a specific symbol like AAPL or TSLA.",
                "type": ARIAResponseType.TEXT.value
            }

        try:
            # Fetch quote from market data service
            quote_result = await self.market_data_service.get_quote(symbol)

            if not quote_result.get("success"):
                return {
                    "text": f"I couldn't fetch data for {symbol}. Error: {quote_result.get('error', 'Unknown error')}",
                    "type": ARIAResponseType.ERROR.value
                }

            data = quote_result["data"]
            price = data.get("price", 0)
            change = data.get("change", 0)
            change_pct = data.get("change_percent", 0)
            high = data.get("day_high", 0)
            low = data.get("day_low", 0)
            volume = data.get("volume", 0)

            # Determine emoji based on change
            if change > 0:
                emoji = "📈"
                direction = "up"
            elif change < 0:
                emoji = "📉"
                direction = "down"
            else:
                emoji = "➡️"
                direction = "flat"

            # Try to enhance with LLM if available
            if self.llm_service.client:
                try:
                    llm_result = await self.llm_service.analyze_market_data(
                        query=original_query,
                        market_data=data
                    )
                    if llm_result.get("success"):
                        return {
                            "text": llm_result["text"],
                            "type": ARIAResponseType.TEXT.value,
                            "market_data": data,
                            "llm_enhanced": True,
                            "provider": llm_result.get("provider")
                        }
                except Exception as e:
                    logger.warning(f"LLM enhancement failed for market data: {e}")

            # Fallback to template response
            text = f"{emoji} {symbol} is trading at ${price:.2f}, {direction} ${abs(change):.2f} ({change_pct:+.2f}%) today. "
            text += f"Day range: ${low:.2f} - ${high:.2f}."

            if volume:
                text += f" Volume: {volume:,.0f}."

            return {
                "text": text,
                "type": ARIAResponseType.TEXT.value,
                "market_data": data
            }

        except Exception as e:
            logger.error(f"Market price query error: {e}")
            return {
                "text": f"I encountered an error fetching {symbol} data. Please try again.",
                "type": ARIAResponseType.ERROR.value,
                "error": str(e)
            }

    async def _generate_market_historical_response(
        self,
        intent: VoiceIntent,
        original_query: str
    ) -> Dict[str, Any]:
        """
        TEMPORARY: Generate market historical/range response using yfinance

        This will be migrated to atomik-data-hub once data sources are configured.
        Supports specific day queries like "last Friday" as well as period queries.
        """
        symbol = intent.parameters.get("symbol", "").upper()
        period_raw = intent.parameters.get("period", "week").lower()
        specific_date = intent.parameters.get("specific_date")

        if not symbol:
            return {
                "text": "I couldn't identify the stock symbol. Please try again with a specific symbol.",
                "type": ARIAResponseType.TEXT.value
            }

        try:
            # Check if this is a specific day query (e.g., "last Friday")
            if specific_date and specific_date.get("type") == "day_of_week":
                day_name = specific_date.get("day", "friday")
                modifier = specific_date.get("modifier", "last")

                logger.info(f"[ARIA] Fetching specific day data: {modifier} {day_name} for {symbol}")
                day_result = await self.market_data_service.get_specific_day_data(symbol, day_name, modifier)

                if day_result.get("success"):
                    data = day_result["data"]

                    # Try to enhance with LLM for natural response
                    if self.llm_service.client:
                        try:
                            llm_result = await self.llm_service.analyze_market_data(
                                query=original_query,
                                market_data={"price_data": {"data": data}}
                            )
                            if llm_result.get("success"):
                                return {
                                    "text": llm_result["text"],
                                    "type": ARIAResponseType.TEXT.value,
                                    "market_data": data,
                                    "llm_enhanced": True,
                                    "provider": llm_result.get("provider")
                                }
                        except Exception as e:
                            logger.warning(f"LLM enhancement failed for specific day data: {e}")

                    # Fallback to template response for specific day
                    actual_day = data.get("actual_day", day_name.capitalize())
                    actual_date = data.get("actual_date", "")
                    open_price = data.get("open", 0)
                    high = data.get("high", 0)
                    low = data.get("low", 0)
                    close = data.get("close", 0)
                    volume = data.get("volume", 0)

                    text = f"📊 {symbol} on {actual_day}, {actual_date}:\n"
                    text += f"• Open: ${open_price:.2f}\n"
                    text += f"• High: ${high:.2f}\n"
                    text += f"• Low: ${low:.2f}\n"
                    text += f"• Close: ${close:.2f}\n"
                    text += f"• Volume: {volume:,}"

                    return {
                        "text": text,
                        "type": ARIAResponseType.TEXT.value,
                        "market_data": data
                    }
                else:
                    # Fall back to period-based query if specific day fails
                    logger.warning(f"Specific day query failed, falling back to period query: {day_result.get('error')}")

            # Map period to yfinance format
            period_map = {
                "day": "1d",
                "today": "1d",
                "week": "1wk",
                "weekly": "1wk",
                "month": "1mo",
                "monthly": "1mo"
            }
            period = period_map.get(period_raw, "1wk")

            # Fetch historical data from market data service
            hist_result = await self.market_data_service.get_historical(symbol, period)

            if not hist_result.get("success"):
                return {
                    "text": f"I couldn't fetch historical data for {symbol}. Error: {hist_result.get('error', 'Unknown error')}",
                    "type": ARIAResponseType.ERROR.value
                }

            data = hist_result["data"]
            high = data.get("high", 0)
            low = data.get("low", 0)
            range_val = data.get("range", 0)
            period_change = data.get("period_change", 0)
            period_change_pct = data.get("period_change_percent", 0)
            start_date = data.get("start_date", "")
            end_date = data.get("end_date", "")

            # Determine emoji
            if period_change > 0:
                emoji = "📈"
                direction = "up"
            elif period_change < 0:
                emoji = "📉"
                direction = "down"
            else:
                emoji = "➡️"
                direction = "flat"

            # Try to enhance with LLM if available
            if self.llm_service.client:
                try:
                    llm_result = await self.llm_service.analyze_market_data(
                        query=original_query,
                        market_data={"price_data": {"data": data}}
                    )
                    if llm_result.get("success"):
                        return {
                            "text": llm_result["text"],
                            "type": ARIAResponseType.TEXT.value,
                            "market_data": data,
                            "llm_enhanced": True,
                            "provider": llm_result.get("provider")
                        }
                except Exception as e:
                    logger.warning(f"LLM enhancement failed for historical data: {e}")

            # Fallback to template response
            period_text = period_raw.replace("ly", "") if period_raw.endswith("ly") else period_raw
            text = f"{emoji} {symbol} {period_text} summary: "
            text += f"Range ${low:.2f} - ${high:.2f} (${range_val:.2f} spread). "
            text += f"{direction.title()} ${abs(period_change):.2f} ({period_change_pct:+.2f}%) over the period."

            return {
                "text": text,
                "type": ARIAResponseType.TEXT.value,
                "market_data": data
            }

        except Exception as e:
            logger.error(f"Market historical query error: {e}")
            return {
                "text": f"I encountered an error fetching {symbol} historical data. Please try again.",
                "type": ARIAResponseType.ERROR.value,
                "error": str(e)
            }

    async def _generate_general_financial_response(
        self,
        user_context: Dict[str, Any],
        intent: VoiceIntent,
        original_query: str
    ) -> Dict[str, Any]:
        """
        Generate response for general financial/trading questions using LLM.

        This handles questions like:
        - "When is the market going to crash?"
        - "What's the difference between a bull and bear market?"
        - "How does inflation affect stocks?"
        - "What is a put option?"
        """
        logger.info(f"[ARIA] Generating general financial response for: '{original_query[:50]}...'")

        # Try LLM first for natural, helpful response
        if self.llm_service.client:
            try:
                llm_result = await self.llm_service.analyze_market_data(
                    query=original_query,
                    user_context=user_context
                )
                if llm_result.get("success"):
                    return {
                        "text": llm_result["text"],
                        "type": ARIAResponseType.TEXT.value,
                        "llm_enhanced": True,
                        "provider": llm_result.get("provider"),
                        "query_type": "general_financial"
                    }
            except Exception as e:
                logger.warning(f"LLM general financial response failed: {e}")

        # Fallback response when LLM is not available
        query_lower = original_query.lower()

        # Try to provide helpful fallback based on common questions
        if any(word in query_lower for word in ['crash', 'bubble', 'recession']):
            return {
                "text": "Market timing is notoriously difficult, and no one can reliably predict crashes. It's generally better to focus on your long-term investment strategy rather than trying to time market events. Is there something specific about your portfolio I can help you with?",
                "type": ARIAResponseType.TEXT.value
            }
        elif any(word in query_lower for word in ['bull', 'bear']):
            return {
                "text": "A bull market is a period of rising prices and investor optimism, while a bear market sees prices declining at least 20% from recent highs. We appear to be in varied conditions depending on the asset class. Would you like me to check how any specific stocks are doing?",
                "type": ARIAResponseType.TEXT.value
            }
        elif any(word in query_lower for word in ['inflation', 'fed', 'interest']):
            return {
                "text": "Interest rates and inflation significantly impact market valuations. Higher rates typically pressure growth stocks while potentially benefiting financials. For personalized analysis, I'd need to check your current positions. Want me to review your portfolio?",
                "type": ARIAResponseType.TEXT.value
            }
        elif any(word in query_lower for word in ['option', 'put', 'call']):
            return {
                "text": "Options are contracts giving you the right (not obligation) to buy or sell at a set price. Calls profit when prices rise; puts profit when prices fall. Would you like me to explain any specific aspect of options trading?",
                "type": ARIAResponseType.TEXT.value
            }

        # Generic fallback
        return {
            "text": "That's a great question about the markets. While I'd love to give you a detailed answer, my AI analysis is currently limited. You can ask me about specific stock prices, your positions, or strategy status. What would you like to know?",
            "type": ARIAResponseType.TEXT.value
        }

    async def _generate_smart_market_response(
        self,
        symbol: str,
        original_query: str,
        user_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Generate intelligent market response for unknown intents containing symbols.

        Fetches market data and uses LLM to provide a helpful response.
        """
        try:
            logger.info(f"[ARIA] Smart market response for symbol: {symbol}")

            # Fetch current quote data
            quote_result = await self.market_data_service.get_quote(symbol)

            if not quote_result.get("success"):
                # Symbol might not be valid, fall back to conversational
                return {
                    "text": f"I couldn't find market data for '{symbol}'. Please check the symbol and try again. You can use the $ prefix for clarity, e.g., $SPY or $AAPL.",
                    "type": ARIAResponseType.TEXT.value
                }

            market_data = quote_result.get("data", {})

            # Check if we should also get historical data based on query
            historical_keywords = {'range', 'week', 'month', 'last', 'history', 'historical', 'yesterday', 'movement'}
            if any(kw in original_query.lower() for kw in historical_keywords):
                # Determine period
                period = "1wk"  # Default
                if 'month' in original_query.lower():
                    period = "1mo"
                elif 'day' in original_query.lower() or 'yesterday' in original_query.lower():
                    period = "1d"

                hist_result = await self.market_data_service.get_historical(symbol, period)
                if hist_result.get("success"):
                    market_data["historical"] = hist_result.get("data", {})

            # Try to use LLM to generate intelligent response
            if self.llm_service.client:
                try:
                    llm_result = await self.llm_service.analyze_market_data(
                        query=original_query,
                        market_data={"price_data": {"data": market_data}},
                        user_context=user_context
                    )
                    if llm_result.get("success"):
                        return {
                            "text": llm_result["text"],
                            "type": ARIAResponseType.TEXT.value,
                            "market_data": market_data,
                            "llm_enhanced": True,
                            "provider": llm_result.get("provider")
                        }
                except Exception as e:
                    logger.warning(f"LLM enhancement failed for smart response: {e}")

            # Fallback to formatted template response
            price = market_data.get("price", 0)
            change = market_data.get("change", 0)
            change_pct = market_data.get("change_percent", 0)
            high = market_data.get("day_high", 0)
            low = market_data.get("day_low", 0)

            # Determine emoji and direction
            if change > 0:
                emoji = "📈"
                direction = "up"
            elif change < 0:
                emoji = "📉"
                direction = "down"
            else:
                emoji = "➡️"
                direction = "flat"

            text = f"{emoji} {symbol} is currently at ${price:.2f}, {direction} ${abs(change):.2f} ({change_pct:+.2f}%) today."

            if high and low:
                text += f" Day range: ${low:.2f} - ${high:.2f}."

            # Add historical summary if available
            if "historical" in market_data:
                hist = market_data["historical"]
                hist_change = hist.get("period_change", 0)
                hist_change_pct = hist.get("period_change_percent", 0)
                hist_high = hist.get("high", 0)
                hist_low = hist.get("low", 0)
                text += f" Weekly range: ${hist_low:.2f} - ${hist_high:.2f} ({hist_change_pct:+.2f}% over the period)."

            return {
                "text": text,
                "type": ARIAResponseType.TEXT.value,
                "market_data": market_data
            }

        except Exception as e:
            logger.error(f"Smart market response error: {e}")
            return {
                "text": f"I encountered an error looking up {symbol}. Please try again or rephrase your question.",
                "type": ARIAResponseType.ERROR.value,
                "error": str(e)
            }