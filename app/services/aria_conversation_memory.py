# app/services/aria_conversation_memory.py
"""
ARIA Conversation Memory Service

Maintains conversation history for contextual multi-turn conversations.
Stores recent messages per user session to enable follow-up questions
like "What about its weekly range?" after asking about a stock.

Uses Redis for shared state across multiple workers.
"""

import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

from ..core.redis_manager import get_redis_client

logger = logging.getLogger(__name__)

# Redis key prefix for conversation storage
CONVERSATION_KEY_PREFIX = "aria:conv:"
# TTL in seconds (30 minutes)
CONVERSATION_TTL = 1800


class ConversationMemory:
    """
    Redis-backed conversation history manager.

    Stores recent conversation turns per user to enable contextual responses.
    Messages are automatically expired after a configurable timeout via Redis TTL.

    Uses Redis for:
    - Cross-server consistency (multiple workers share state)
    - Persistence across restarts
    - Better scalability
    """

    def __init__(
        self,
        max_turns: int = 50,
        session_timeout_minutes: int = 30
    ):
        """
        Initialize conversation memory.

        Args:
            max_turns: Maximum conversation turns to keep per user
            session_timeout_minutes: Clear history after this many minutes of inactivity
        """
        self.max_turns = max_turns
        self.session_timeout_seconds = session_timeout_minutes * 60
        self._fallback_memory: Dict[int, List[Dict]] = {}  # Fallback if Redis unavailable

        logger.info(
            f"ConversationMemory initialized: max_turns={max_turns}, "
            f"timeout={session_timeout_minutes}min (Redis-backed)"
        )

    def _get_key(self, user_id: int) -> str:
        """Get Redis key for a user's conversation."""
        return f"{CONVERSATION_KEY_PREFIX}{user_id}"

    def _serialize_message(self, message: Dict) -> str:
        """Serialize a message dict to JSON string."""
        return json.dumps(message)

    def _deserialize_message(self, data: str) -> Dict:
        """Deserialize a JSON string to message dict."""
        return json.loads(data)

    def add_user_message(self, user_id: int, content: str) -> None:
        """
        Add a user message to conversation history.

        Args:
            user_id: User's ID
            content: User's message content
        """
        message = {
            "role": "user",
            "content": content,
            "timestamp": datetime.utcnow().isoformat()
        }
        self._add_message(user_id, message)

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
        message = {
            "role": "assistant",
            "content": content,
            "timestamp": datetime.utcnow().isoformat()
        }

        # Optionally store tool usage metadata (not sent to LLM, just for tracking)
        if tool_calls:
            message["_tool_calls"] = tool_calls

        self._add_message(user_id, message)

    def _add_message(self, user_id: int, message: Dict) -> None:
        """Add a message to Redis list."""
        client = get_redis_client()
        key = self._get_key(user_id)

        if client:
            try:
                # Add message to the end of the list
                client.rpush(key, self._serialize_message(message))

                # Trim to keep only the most recent messages (max_turns * 2 for pairs)
                max_messages = self.max_turns * 2
                client.ltrim(key, -max_messages, -1)

                # Reset TTL on activity
                client.expire(key, self.session_timeout_seconds)

                logger.debug(f"Added message to Redis for user {user_id}")
            except Exception as e:
                logger.warning(f"Redis error adding message, using fallback: {e}")
                self._add_to_fallback(user_id, message)
        else:
            # Redis not available, use fallback
            self._add_to_fallback(user_id, message)

    def _add_to_fallback(self, user_id: int, message: Dict) -> None:
        """Add message to in-memory fallback storage."""
        if user_id not in self._fallback_memory:
            self._fallback_memory[user_id] = []

        self._fallback_memory[user_id].append(message)

        # Trim fallback memory
        max_messages = self.max_turns * 2
        if len(self._fallback_memory[user_id]) > max_messages:
            self._fallback_memory[user_id] = self._fallback_memory[user_id][-max_messages:]

    def get_history(self, user_id: int) -> List[Dict[str, str]]:
        """
        Get conversation history for a user.

        Args:
            user_id: User's ID

        Returns:
            List of message dicts with 'role' and 'content'
        """
        client = get_redis_client()
        key = self._get_key(user_id)

        if client:
            try:
                # Get all messages from the list
                raw_messages = client.lrange(key, 0, -1)

                if not raw_messages:
                    logger.debug(f"No conversation history in Redis for user {user_id}")
                    return []

                # Deserialize and return clean messages (without internal metadata)
                messages = []
                for raw in raw_messages:
                    msg = self._deserialize_message(raw)
                    messages.append({
                        "role": msg["role"],
                        "content": msg["content"]
                    })

                logger.debug(f"Retrieved {len(messages)} messages from Redis for user {user_id}")
                return messages

            except Exception as e:
                logger.warning(f"Redis error getting history, using fallback: {e}")
                return self._get_from_fallback(user_id)
        else:
            return self._get_from_fallback(user_id)

    def _get_from_fallback(self, user_id: int) -> List[Dict[str, str]]:
        """Get messages from in-memory fallback storage."""
        messages = self._fallback_memory.get(user_id, [])
        return [
            {"role": m["role"], "content": m["content"]}
            for m in messages
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
        client = get_redis_client()
        key = self._get_key(user_id)

        if client:
            try:
                client.delete(key)
                logger.info(f"Cleared conversation history in Redis for user {user_id}")
            except Exception as e:
                logger.warning(f"Redis error clearing history: {e}")

        # Also clear fallback
        if user_id in self._fallback_memory:
            del self._fallback_memory[user_id]

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

            # Look for futures symbols mentioned in responses
            futures_match = re.search(
                r'\b(ES|NQ|MNQ|MES|RTY|YM|GC|SI|CL|ZB|ZN|ZT)\b',
                content.upper()
            )
            if futures_match:
                return futures_match.group(1)

        return None

    def get_stats(self) -> Dict[str, Any]:
        """Get memory usage statistics."""
        client = get_redis_client()

        if client:
            try:
                # Count keys matching our pattern
                keys = client.keys(f"{CONVERSATION_KEY_PREFIX}*")
                total_messages = 0

                for key in keys:
                    total_messages += client.llen(key)

                return {
                    "storage": "redis",
                    "active_sessions": len(keys),
                    "total_messages": total_messages,
                    "max_turns_per_session": self.max_turns,
                    "session_timeout_minutes": self.session_timeout_seconds / 60,
                    "fallback_sessions": len(self._fallback_memory)
                }
            except Exception as e:
                logger.error(f"Error getting Redis stats: {e}")
                return {
                    "storage": "redis",
                    "status": "error",
                    "error": str(e),
                    "fallback_sessions": len(self._fallback_memory)
                }
        else:
            return {
                "storage": "fallback_memory",
                "active_sessions": len(self._fallback_memory),
                "total_messages": sum(
                    len(msgs) for msgs in self._fallback_memory.values()
                ),
                "max_turns_per_session": self.max_turns,
                "session_timeout_minutes": self.session_timeout_seconds / 60
            }


# Global instance for easy access across the application
# Updated to support longer conversations (100 messages = 50 turns)
# This is well within Groq's 128K token context window
conversation_memory = ConversationMemory(
    max_turns=50,  # 100 messages (50 user + 50 assistant)
    session_timeout_minutes=30
)
