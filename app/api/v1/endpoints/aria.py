# app/api/v1/endpoints/aria.py
# ARIA Assistant API endpoints with comprehensive logging
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import text, desc
from pydantic import BaseModel, Field
import logging

from ....services.aria_assistant import ARIAAssistant
from ....models.user import User
from ....models.aria_context import UserTradingProfile, ARIAConversation, ARIAInteraction
from ....core.security import get_current_user
from ....db.base import get_db
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

router = APIRouter()

# Request/Response Models
class ARIAMessageRequest(BaseModel):
    """Request model for ARIA text/voice input"""
    message: str = Field(..., description="User's message or voice transcript")
    input_type: str = Field(default="text", description="Input type: 'text' or 'voice'")
    context: Optional[Dict[str, Any]] = Field(default=None, description="Additional context")
    conversation_id: Optional[int] = Field(default=None, description="Conversation ID to continue (optional)")

class ARIAConfirmationRequest(BaseModel):
    """Request model for confirmation responses"""
    interaction_id: int = Field(..., description="ID of the interaction requiring confirmation")
    confirmed: bool = Field(..., description="Whether the user confirmed the action")

class ARIAResponse(BaseModel):
    """Standardized ARIA response model"""
    success: bool
    response: Dict[str, Any]
    interaction_id: Optional[int] = None
    conversation_id: Optional[int] = None
    requires_confirmation: bool = False
    action_result: Optional[Dict[str, Any]] = None
    processing_time_ms: Optional[int] = None
    error: Optional[str] = None

class ARIAContextResponse(BaseModel):
    """Response model for user context"""
    user_profile: Dict[str, Any]
    current_positions: Dict[str, Any]
    active_strategies: list
    performance_summary: Dict[str, Any]
    risk_metrics: Dict[str, Any]
    broker_status: Dict[str, Any]
    market_context: Dict[str, Any]


# Conversation Models
class ConversationSummary(BaseModel):
    """Summary of a conversation for list views"""
    id: int
    title: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    message_count: int = 0
    preview: Optional[str] = None


class ConversationListResponse(BaseModel):
    """Response model for conversation list"""
    success: bool
    conversations: List[ConversationSummary]


class ConversationMessage(BaseModel):
    """A single message in a conversation"""
    id: int
    type: str  # "user" or "aria"
    content: str
    timestamp: datetime


class ConversationMessagesResponse(BaseModel):
    """Response model for conversation messages with pagination"""
    success: bool
    conversation_id: int
    messages: List[ConversationMessage]
    has_more: bool


class CreateConversationResponse(BaseModel):
    """Response model for creating a new conversation"""
    success: bool
    conversation: ConversationSummary


class UpdateConversationRequest(BaseModel):
    """Request model for updating conversation (rename)"""
    title: str = Field(..., max_length=255)


class UpdateConversationResponse(BaseModel):
    """Response model for conversation update"""
    success: bool
    conversation: ConversationSummary


class DeleteConversationResponse(BaseModel):
    """Response model for deleting (archiving) conversation"""
    success: bool
    message: str


# Endpoints

def generate_conversation_title(first_message: str) -> str:
    """Generate a title from the first user message."""
    title = first_message.strip()
    # Remove special characters that might be problematic
    title = ' '.join(title.split())  # Normalize whitespace
    if len(title) > 50:
        title = title[:47] + "..."
    return title


@router.post("/chat", response_model=ARIAResponse)
async def aria_chat(
    request: ARIAMessageRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Main ARIA chat endpoint for text and voice interactions

    Process user input and return ARIA's response with any actions taken.
    Supports conversation persistence via optional conversation_id parameter.
    If no conversation_id provided, creates a new conversation automatically.
    """
    logger.info(f"[ARIA] Chat request received from user {current_user.id}: '{request.message[:100]}...' (type: {request.input_type})")

    try:
        conversation_id = request.conversation_id
        is_new_conversation = False

        # Handle conversation - create new if not provided
        if conversation_id:
            # Verify conversation belongs to user and exists
            conversation = db.query(ARIAConversation).filter(
                ARIAConversation.id == conversation_id,
                ARIAConversation.user_id == current_user.id,
                ARIAConversation.is_archived == False
            ).first()

            if not conversation:
                logger.warning(f"[ARIA] Conversation {conversation_id} not found for user {current_user.id}, creating new one")
                conversation_id = None

        if not conversation_id:
            # Create new conversation
            conversation = ARIAConversation(
                user_id=current_user.id,
                title=generate_conversation_title(request.message),
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                is_archived=False
            )
            db.add(conversation)
            db.commit()
            db.refresh(conversation)
            conversation_id = conversation.id
            is_new_conversation = True
            logger.info(f"[ARIA] Created new conversation {conversation_id} for user {current_user.id}")
        else:
            # Update conversation timestamp
            conversation.updated_at = datetime.utcnow()
            # Set title if still null (shouldn't happen but safety check)
            if not conversation.title:
                conversation.title = generate_conversation_title(request.message)
            db.commit()

        aria = ARIAAssistant(db)

        logger.info(f"[ARIA] Processing input for user {current_user.id} in conversation {conversation_id}...")
        result = await aria.process_user_input(
            user_id=current_user.id,
            input_text=request.message,
            input_type=request.input_type,
            conversation_id=conversation_id
        )

        logger.info(f"[ARIA] Response generated for user {current_user.id}: success={result.get('success')}, interaction_id={result.get('interaction_id')}")
        logger.info(f"[ARIA] Response text: '{result.get('response', {}).get('text', 'N/A')[:100]}...'")

        return ARIAResponse(
            success=result["success"],
            response=result["response"],
            interaction_id=result.get("interaction_id"),
            conversation_id=conversation_id,
            requires_confirmation=result.get("requires_confirmation", False),
            action_result=result.get("action_result"),
            processing_time_ms=result.get("processing_time_ms"),
            error=result.get("error")
        )

    except Exception as e:
        logger.error(f"[ARIA] Chat error for user {current_user.id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"ARIA processing failed: {str(e)}"
        )

@router.post("/voice", response_model=ARIAResponse)
async def aria_voice_command(
    request: ARIAMessageRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Specialized endpoint for voice commands with optimized processing
    """
    logger.info(f"[ARIA] Voice command received from user {current_user.id}: '{request.message[:100]}...'")

    try:
        aria = ARIAAssistant(db)

        result = await aria.execute_voice_command(
            user_id=current_user.id,
            command=request.message
        )

        logger.info(f"[ARIA] Voice response for user {current_user.id}: success={result.get('success')}")

        return ARIAResponse(
            success=result["success"],
            response=result["response"],
            interaction_id=result.get("interaction_id"),
            requires_confirmation=result.get("requires_confirmation", False),
            action_result=result.get("action_result"),
            processing_time_ms=result.get("processing_time_ms"),
            error=result.get("error")
        )

    except Exception as e:
        logger.error(f"[ARIA] Voice command error for user {current_user.id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Voice command processing failed: {str(e)}"
        )

@router.post("/confirm", response_model=ARIAResponse)
async def aria_confirmation(
    request: ARIAConfirmationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Handle user confirmations for pending actions
    """
    logger.info(f"[ARIA] Confirmation received from user {current_user.id}: interaction_id={request.interaction_id}, confirmed={request.confirmed}")

    try:
        aria = ARIAAssistant(db)

        result = await aria.handle_confirmation_response(
            user_id=current_user.id,
            interaction_id=request.interaction_id,
            confirmed=request.confirmed
        )

        logger.info(f"[ARIA] Confirmation processed for user {current_user.id}: success={result.get('success')}")

        return ARIAResponse(
            success=result["success"],
            response=result["response"],
            action_result=result.get("action_result"),
            error=result.get("error")
        )

    except Exception as e:
        logger.error(f"[ARIA] Confirmation error for user {current_user.id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Confirmation processing failed: {str(e)}"
        )

@router.get("/context", response_model=ARIAContextResponse)
async def get_aria_context(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get comprehensive user context for ARIA
    
    Returns current positions, strategies, performance, and other context
    """
    try:
        aria = ARIAAssistant(db)
        
        context = await aria.get_user_context_summary(current_user.id)
        
        return ARIAContextResponse(
            user_profile=context.get("user_profile", {}),
            current_positions=context.get("current_positions", {}),
            active_strategies=context.get("active_strategies", []),
            performance_summary=context.get("performance_summary", {}),
            risk_metrics=context.get("risk_metrics", {}),
            broker_status=context.get("broker_status", {}),
            market_context=context.get("market_context", {})
        )
        
    except Exception as e:
        logger.error(f"ARIA context error for user {current_user.id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Context retrieval failed: {str(e)}"
        )

@router.get("/examples")
async def get_aria_examples():
    """
    Get example commands and usage patterns for ARIA
    """
    try:
        from ....services.intent_service import IntentService
        
        intent_service = IntentService()
        examples = intent_service.get_intent_examples()
        
        return {
            "success": True,
            "examples": examples,
            "voice_tips": [
                "Speak clearly and use natural language",
                "Include specific details like 'Purple Reign strategy' or 'AAPL position'",
                "ARIA will ask for confirmation on important actions",
                "You can say 'Yes' or 'No' to confirm or cancel actions"
            ],
            "sample_conversations": [
                {
                    "user": "Turn on my Purple Reign strategy",
                    "aria": "I'll activate your Purple Reign strategy. This will affect your automated trading. Confirm: Yes or No?",
                    "user": "Yes",
                    "aria": "✅ Purple Reign strategy has been activated. I'll monitor its performance for you."
                },
                {
                    "user": "What's my Tesla position?",
                    "aria": "📊 Your TSLA position: -50 shares, P&L: $165.00 (1.34% gain)"
                },
                {
                    "user": "How did I do today?",
                    "aria": "📈 Today you're up $250.75 with 8 trades. Your win rate is 62.5%."
                }
            ]
        }
        
    except Exception as e:
        logger.error(f"ARIA examples error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Examples retrieval failed: {str(e)}"
        )

@router.get("/health")
async def aria_health_check(
    db: Session = Depends(get_db)
):
    """
    Health check endpoint for ARIA services
    """
    try:
        # Test database connection
        db.execute(text("SELECT 1"))

        # Test ARIA service initialization
        aria = ARIAAssistant(db)

        # Get LLM status
        llm_report = aria.llm_service.get_usage_report()

        return {
            "success": True,
            "status": "healthy",
            "services": {
                "database": "connected",
                "aria_assistant": "initialized",
                "intent_service": "ready",
                "context_engine": "ready",
                "action_executor": "ready",
                "llm_service": {
                    "provider": llm_report.get("provider", "none"),
                    "model": llm_report.get("model"),
                    "configured": llm_report.get("is_configured", False)
                }
            },
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
        
    except Exception as e:
        logger.error(f"ARIA health check failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"ARIA services unhealthy: {str(e)}"
        )


# ==================== Conversation Endpoints ====================

@router.get("/conversations", response_model=ConversationListResponse)
async def get_conversations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get list of user's conversations from the last 15 days.
    Returns conversations ordered by most recently updated.
    """
    try:
        # Calculate cutoff date (15 days ago)
        cutoff_date = datetime.utcnow() - timedelta(days=15)

        # Query conversations for this user
        conversations = db.query(ARIAConversation).filter(
            ARIAConversation.user_id == current_user.id,
            ARIAConversation.is_archived == False,
            ARIAConversation.created_at >= cutoff_date
        ).order_by(desc(ARIAConversation.updated_at)).all()

        conversation_summaries = []
        for conv in conversations:
            # Get message count
            message_count = db.query(ARIAInteraction).filter(
                ARIAInteraction.conversation_id == conv.id
            ).count()

            # Get preview from first user message
            first_interaction = db.query(ARIAInteraction).filter(
                ARIAInteraction.conversation_id == conv.id,
                ARIAInteraction.raw_input.isnot(None)
            ).order_by(ARIAInteraction.timestamp).first()

            preview = None
            if first_interaction and first_interaction.raw_input:
                preview = first_interaction.raw_input[:100]
                if len(first_interaction.raw_input) > 100:
                    preview += "..."

            conversation_summaries.append(ConversationSummary(
                id=conv.id,
                title=conv.title,
                created_at=conv.created_at,
                updated_at=conv.updated_at,
                message_count=message_count,
                preview=preview
            ))

        logger.info(f"[ARIA] Retrieved {len(conversation_summaries)} conversations for user {current_user.id}")

        return ConversationListResponse(
            success=True,
            conversations=conversation_summaries
        )

    except Exception as e:
        logger.error(f"[ARIA] Get conversations error for user {current_user.id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve conversations: {str(e)}"
        )


@router.get("/conversations/{conversation_id}/messages", response_model=ConversationMessagesResponse)
async def get_conversation_messages(
    conversation_id: int,
    limit: int = Query(default=30, ge=1, le=100),
    before_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get messages for a specific conversation with cursor-based pagination.

    - limit: Number of messages to return (default 30, max 100)
    - before_id: Get messages older than this message ID (for pagination)
    """
    try:
        # Verify conversation belongs to user
        conversation = db.query(ARIAConversation).filter(
            ARIAConversation.id == conversation_id,
            ARIAConversation.user_id == current_user.id
        ).first()

        if not conversation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found"
            )

        # Build query for interactions
        query = db.query(ARIAInteraction).filter(
            ARIAInteraction.conversation_id == conversation_id
        )

        if before_id:
            query = query.filter(ARIAInteraction.id < before_id)

        # Get messages ordered by timestamp descending (newest first for pagination)
        interactions = query.order_by(desc(ARIAInteraction.timestamp)).limit(limit + 1).all()

        # Check if there are more messages
        has_more = len(interactions) > limit
        if has_more:
            interactions = interactions[:limit]

        # Convert to messages (reverse to show oldest first in response)
        messages = []
        for interaction in reversed(interactions):
            # Add user message
            if interaction.raw_input:
                messages.append(ConversationMessage(
                    id=interaction.id,
                    type="user",
                    content=interaction.raw_input,
                    timestamp=interaction.timestamp
                ))

            # Add ARIA response
            if interaction.aria_response:
                messages.append(ConversationMessage(
                    id=interaction.id + 10000000,  # Offset ID for response
                    type="aria",
                    content=interaction.aria_response,
                    timestamp=interaction.response_timestamp or interaction.timestamp
                ))

        logger.info(f"[ARIA] Retrieved {len(messages)} messages for conversation {conversation_id}")

        return ConversationMessagesResponse(
            success=True,
            conversation_id=conversation_id,
            messages=messages,
            has_more=has_more
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ARIA] Get messages error for conversation {conversation_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve messages: {str(e)}"
        )


@router.post("/conversations", response_model=CreateConversationResponse)
async def create_conversation(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Create a new conversation.
    Title will be auto-generated from the first message.
    """
    try:
        conversation = ARIAConversation(
            user_id=current_user.id,
            title=None,  # Will be set from first message
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            is_archived=False
        )

        db.add(conversation)
        db.commit()
        db.refresh(conversation)

        logger.info(f"[ARIA] Created new conversation {conversation.id} for user {current_user.id}")

        return CreateConversationResponse(
            success=True,
            conversation=ConversationSummary(
                id=conversation.id,
                title=conversation.title,
                created_at=conversation.created_at,
                updated_at=conversation.updated_at,
                message_count=0,
                preview=None
            )
        )

    except Exception as e:
        logger.error(f"[ARIA] Create conversation error for user {current_user.id}: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create conversation: {str(e)}"
        )


@router.patch("/conversations/{conversation_id}", response_model=UpdateConversationResponse)
async def update_conversation(
    conversation_id: int,
    request: UpdateConversationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Update a conversation (rename).
    """
    try:
        conversation = db.query(ARIAConversation).filter(
            ARIAConversation.id == conversation_id,
            ARIAConversation.user_id == current_user.id
        ).first()

        if not conversation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found"
            )

        conversation.title = request.title
        conversation.updated_at = datetime.utcnow()

        db.commit()
        db.refresh(conversation)

        # Get message count
        message_count = db.query(ARIAInteraction).filter(
            ARIAInteraction.conversation_id == conversation.id
        ).count()

        logger.info(f"[ARIA] Updated conversation {conversation_id} title to '{request.title}'")

        return UpdateConversationResponse(
            success=True,
            conversation=ConversationSummary(
                id=conversation.id,
                title=conversation.title,
                created_at=conversation.created_at,
                updated_at=conversation.updated_at,
                message_count=message_count,
                preview=None
            )
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ARIA] Update conversation error for {conversation_id}: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update conversation: {str(e)}"
        )


@router.delete("/conversations/{conversation_id}", response_model=DeleteConversationResponse)
async def delete_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Delete (archive) a conversation.
    Uses soft delete - sets is_archived flag to true.
    """
    try:
        conversation = db.query(ARIAConversation).filter(
            ARIAConversation.id == conversation_id,
            ARIAConversation.user_id == current_user.id
        ).first()

        if not conversation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found"
            )

        conversation.is_archived = True
        conversation.updated_at = datetime.utcnow()

        db.commit()

        logger.info(f"[ARIA] Archived conversation {conversation_id} for user {current_user.id}")

        return DeleteConversationResponse(
            success=True,
            message="Conversation archived successfully"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ARIA] Delete conversation error for {conversation_id}: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete conversation: {str(e)}"
        )


# Voice-specific endpoints for future mobile integration

@router.post("/voice/start-session")
async def start_voice_session(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Start a voice interaction session (future: WebRTC, real-time processing)
    """
    try:
        return {
            "success": True,
            "session_id": f"voice_session_{current_user.id}_{int(datetime.utcnow().timestamp())}",
            "message": "Voice session started. You can now send voice commands.",
            "supported_formats": ["audio/webm", "audio/wav", "audio/mp3"],
            "max_duration_seconds": 30
        }
        
    except Exception as e:
        logger.error(f"Voice session start error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Voice session start failed: {str(e)}"
        )

@router.post("/voice/end-session")
async def end_voice_session(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    End a voice interaction session
    """
    try:
        return {
            "success": True,
            "session_id": session_id,
            "message": "Voice session ended successfully.",
            "session_duration": "45 seconds",  # Would track actual duration
            "commands_processed": 3  # Would track actual commands
        }
        
    except Exception as e:
        logger.error(f"Voice session end error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Voice session end failed: {str(e)}"
        )

# Analytics endpoints for ARIA usage

@router.get("/analytics/interactions")
async def get_aria_analytics(
    days: int = 7,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get ARIA interaction analytics for the user
    """
    try:
        from ....models.aria_context import ARIAInteraction
        from datetime import datetime, timedelta
        
        start_date = datetime.utcnow() - timedelta(days=days)
        
        # Get user's trading profile to access interactions
        user_profile = db.query(UserTradingProfile).filter(
            UserTradingProfile.user_id == current_user.id
        ).first()
        
        if not user_profile:
            return {
                "success": True,
                "analytics": {
                    "total_interactions": 0,
                    "voice_interactions": 0,
                    "text_interactions": 0,
                    "successful_actions": 0,
                    "failed_actions": 0,
                    "most_used_intents": [],
                    "average_response_time_ms": 0
                }
            }
        
        interactions = db.query(ARIAInteraction).filter(
            ARIAInteraction.user_profile_id == user_profile.id,
            ARIAInteraction.timestamp >= start_date
        ).all()
        
        # Calculate analytics
        total_interactions = len(interactions)
        voice_interactions = len([i for i in interactions if i.interaction_type == "voice"])
        text_interactions = len([i for i in interactions if i.interaction_type == "text"])
        successful_actions = len([i for i in interactions if i.action_success == True])
        failed_actions = len([i for i in interactions if i.action_success == False])
        
        # Intent frequency
        intent_counts = {}
        response_times = []
        
        for interaction in interactions:
            if interaction.detected_intent:
                intent_counts[interaction.detected_intent] = intent_counts.get(interaction.detected_intent, 0) + 1
            
            if interaction.response_time_ms:
                response_times.append(interaction.response_time_ms)
        
        most_used_intents = sorted(intent_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        avg_response_time = sum(response_times) / len(response_times) if response_times else 0
        
        return {
            "success": True,
            "analytics": {
                "period_days": days,
                "total_interactions": total_interactions,
                "voice_interactions": voice_interactions,
                "text_interactions": text_interactions,
                "successful_actions": successful_actions,
                "failed_actions": failed_actions,
                "success_rate": successful_actions / max(successful_actions + failed_actions, 1),
                "most_used_intents": most_used_intents,
                "average_response_time_ms": int(avg_response_time),
                "voice_usage_percentage": voice_interactions / max(total_interactions, 1) * 100
            }
        }
        
    except Exception as e:
        logger.error(f"ARIA analytics error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Analytics retrieval failed: {str(e)}"
        )


# ==================== Internal Endpoints (for Discord Bot) ====================

from fastapi import Header
from ....api.deps import verify_internal_api_key


class InternalARIARequest(BaseModel):
    """Request model for internal ARIA calls from Discord bot."""
    message: str
    input_type: str = "text"
    source: str = "discord"
    conversation_id: Optional[int] = None


class InternalConfirmRequest(BaseModel):
    """Request model for internal confirmation calls."""
    interaction_id: int
    confirmed: bool


@router.post("/internal/chat", response_model=ARIAResponse)
async def internal_aria_chat(
    request: InternalARIARequest,
    x_user_id: str = Header(..., alias="X-User-ID"),
    db: Session = Depends(get_db),
    _: bool = Depends(verify_internal_api_key)
):
    """
    Internal ARIA chat endpoint for Discord bot.

    Requires internal API key and X-User-ID header.
    """
    try:
        user_id = int(x_user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid X-User-ID header"
        )

    # Verify user exists
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    logger.info(f"[ARIA Internal] Chat from Discord for user {user_id}: '{request.message[:50]}...'")

    try:
        conversation_id = request.conversation_id
        is_new_conversation = False

        # Handle conversation - create new if not provided
        if conversation_id:
            conversation = db.query(ARIAConversation).filter(
                ARIAConversation.id == conversation_id,
                ARIAConversation.user_id == user_id,
                ARIAConversation.is_archived == False
            ).first()
            if not conversation:
                conversation_id = None

        if not conversation_id:
            is_new_conversation = True
            title = generate_conversation_title(request.message)
            conversation = ARIAConversation(
                user_id=user_id,
                title=title
            )
            db.add(conversation)
            db.flush()
            conversation_id = conversation.id

        aria = ARIAAssistant(db)

        result = await aria.process_user_input(
            user_id=user_id,
            message=request.message,
            input_type=request.input_type,
            context={"source": request.source, "platform": "discord"},
            conversation_id=conversation_id
        )

        # Update conversation timestamp
        if not is_new_conversation:
            conversation = db.query(ARIAConversation).filter(
                ARIAConversation.id == conversation_id
            ).first()
            if conversation:
                conversation.updated_at = datetime.utcnow()

        db.commit()

        return ARIAResponse(
            success=result["success"],
            response=result["response"],
            interaction_id=result.get("interaction_id"),
            conversation_id=conversation_id,
            requires_confirmation=result.get("requires_confirmation", False),
            action_result=result.get("action_result"),
            processing_time_ms=result.get("processing_time_ms"),
            error=result.get("error")
        )

    except Exception as e:
        logger.error(f"[ARIA Internal] Error for user {user_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"ARIA processing failed: {str(e)}"
        )


@router.post("/internal/confirm", response_model=ARIAResponse)
async def internal_aria_confirm(
    request: InternalConfirmRequest,
    x_user_id: str = Header(..., alias="X-User-ID"),
    db: Session = Depends(get_db),
    _: bool = Depends(verify_internal_api_key)
):
    """
    Internal confirmation endpoint for Discord bot.

    Requires internal API key and X-User-ID header.
    """
    try:
        user_id = int(x_user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid X-User-ID header"
        )

    logger.info(f"[ARIA Internal] Confirmation from Discord for user {user_id}: interaction={request.interaction_id}")

    try:
        aria = ARIAAssistant(db)

        result = await aria.handle_confirmation_response(
            user_id=user_id,
            interaction_id=request.interaction_id,
            confirmed=request.confirmed
        )

        return ARIAResponse(
            success=result["success"],
            response=result["response"],
            action_result=result.get("action_result"),
            error=result.get("error")
        )

    except Exception as e:
        logger.error(f"[ARIA Internal] Confirmation error for user {user_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Confirmation processing failed: {str(e)}"
        )