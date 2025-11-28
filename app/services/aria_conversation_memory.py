# app/services/aria_conversation_memory.py
"""
ARIA Conversation Memory Service

Maintains conversation history for contextual multi-turn conversations.
Stores recent messages per user session to enable follow-up questions
like "What about its weekly range?" after asking about a stock.
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from collections import defaultdict
import threading

logger = logging.getLogger(__name__)


class ConversationMemory:
    """
    In-memory conversation history manager.

    Stores recent conversation turns per user to enable contextual responses.
    Messages are automatically expired after a configurable timeout.

    For production, consider persisting to Redis or database for:
    - Cross-server consistency
    - Persistence across restarts
    - Better scalability
    """

    def __init__(
        self,
        max_turns: int = 10,
        session_timeout_minutes: int = 30
    ):
        """
        Initialize conversation memory.

        Args:
            max_turns: Maximum conversation turns to keep per user
            session_timeout_minutes: Clear history after this many minutes of inactivity
        """
        self.max_turns = max_turns
        self.session_timeout = timedelta(minutes=session_timeout_minutes)

        # Store: user_id -> {"messages": [...], "last_activity": datetime}
        self._conversations: Dict[int, Dict[str, Any]] = defaultdict(
            lambda: {"messages": [], "last_activity": datetime.utcnow()}
        )
        self._lock = threading.Lock()

        logger.info(
            f"ConversationMemory initialized: max_turns={max_turns}, "
            f"timeout={session_timeout_minutes}min"
        )

    def add_user_message(self, user_id: int, content: str) -> None:
        """
        Add a user message to conversation history.

        Args:
            user_id: User's ID
            content: User's message content
        """
        with self._lock:
            self._cleanup_expired(user_id)
            conv = self._conversations[user_id]
            conv["messages"].append({
                "role": "user",
                "content": content
            })
            conv["last_activity"] = datetime.utcnow()
            self._trim_history(user_id)

    def add_assistant_message(
        self,
        user_id: int,
        content: str,
        tool_calls: Optional[List[Dict]] = None
    ) -> None:
        """
        Add an assistant message to conversation history.

        Args:
            user_id: User's ID
            content: Assistant's response content
            tool_calls: Optional tool calls made (for context)
        """
        with self._lock:
            conv = self._conversations[user_id]

            message = {
                "role": "assistant",
                "content": content
            }

            # Optionally store tool usage metadata (not sent to LLM, just for tracking)
            if tool_calls:
                message["_tool_calls"] = tool_calls

            conv["messages"].append(message)
            conv["last_activity"] = datetime.utcnow()
            self._trim_history(user_id)

    def get_history(self, user_id: int) -> List[Dict[str, str]]:
        """
        Get conversation history for a user.

        Args:
            user_id: User's ID

        Returns:
            List of message dicts with 'role' and 'content'
        """
        with self._lock:
            self._cleanup_expired(user_id)
            conv = self._conversations.get(user_id)

            if not conv:
                return []

            # Return clean messages (without internal metadata)
            return [
                {"role": m["role"], "content": m["content"]}
                for m in conv["messages"]
            ]

    def get_history_for_llm(
        self,
        user_id: int,
        include_current: bool = False,
        current_query: Optional[str] = None
    ) -> List[Dict[str, str]]:
        """
        Get conversation history formatted for LLM API call.

        Args:
            user_id: User's ID
            include_current: Whether to include the current query
            current_query: The current user query to append

        Returns:
            List of messages ready for LLM API
        """
        history = self.get_history(user_id)

        if include_current and current_query:
            history.append({"role": "user", "content": current_query})

        return history

    def clear_history(self, user_id: int) -> None:
        """
        Clear conversation history for a user.

        Args:
            user_id: User's ID
        """
        with self._lock:
            if user_id in self._conversations:
                del self._conversations[user_id]
                logger.info(f"Cleared conversation history for user {user_id}")

    def get_last_mentioned_symbol(self, user_id: int) -> Optional[str]:
        """
        Extract the last mentioned stock symbol from conversation.

        Useful for resolving pronouns like "it", "that stock", etc.

        Args:
            user_id: User's ID

        Returns:
            Last mentioned symbol or None
        """
        import re

        history = self.get_history(user_id)

        # Search backwards through messages for symbols
        for msg in reversed(history):
            content = msg.get("content", "")

            # Look for $SYMBOL pattern
            dollar_match = re.search(r'\$([A-Z]{1,5})\b', content.upper())
            if dollar_match:
                return dollar_match.group(1)

            # Look for "SYMBOL is at" or "SYMBOL is trading" patterns
            trading_match = re.search(
                r'\b([A-Z]{1,5})\s+is\s+(at|trading|currently)',
                content,
                re.IGNORECASE
            )
            if trading_match:
                return trading_match.group(1).upper()

        return None

    def _trim_history(self, user_id: int) -> None:
        """Trim history to max_turns (keep most recent)"""
        conv = self._conversations[user_id]
        if len(conv["messages"]) > self.max_turns * 2:  # *2 for user+assistant pairs
            # Keep the most recent messages
            conv["messages"] = conv["messages"][-(self.max_turns * 2):]

    def _cleanup_expired(self, user_id: int) -> None:
        """Clear history if session has timed out"""
        conv = self._conversations.get(user_id)
        if conv:
            if datetime.utcnow() - conv["last_activity"] > self.session_timeout:
                logger.info(f"Session timeout for user {user_id}, clearing history")
                del self._conversations[user_id]

    def get_stats(self) -> Dict[str, Any]:
        """Get memory usage statistics"""
        with self._lock:
            return {
                "active_sessions": len(self._conversations),
                "total_messages": sum(
                    len(c["messages"]) for c in self._conversations.values()
                ),
                "max_turns_per_session": self.max_turns,
                "session_timeout_minutes": self.session_timeout.total_seconds() / 60
            }


# Global instance for easy access across the application
# Updated to support longer conversations (100 messages = 50 turns)
# This is well within Groq's 128K token context window
conversation_memory = ConversationMemory(
    max_turns=50,  # 100 messages (50 user + 50 assistant)
    session_timeout_minutes=30
)
