# app/tasks/cleanup.py
"""
ARIA Conversation Cleanup Task

Handles automatic cleanup of old conversations and interactions.
Conversations older than 15 days are deleted to maintain database hygiene.
"""

import logging
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_

from ..models.aria_context import ARIAConversation, ARIAInteraction
from ..db.base import SessionLocal

logger = logging.getLogger(__name__)

# Retention period in days
CONVERSATION_RETENTION_DAYS = 15


async def cleanup_old_conversations(db: Session = None) -> dict:
    """
    Delete conversations and their interactions older than the retention period.

    Args:
        db: Optional database session. If not provided, creates a new one.

    Returns:
        Dictionary with cleanup statistics
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        cutoff_date = datetime.utcnow() - timedelta(days=CONVERSATION_RETENTION_DAYS)

        logger.info(f"[ARIA Cleanup] Starting cleanup of conversations older than {cutoff_date}")

        # Get conversations to delete
        old_conversations = db.query(ARIAConversation).filter(
            ARIAConversation.created_at < cutoff_date
        ).all()

        conversation_ids = [c.id for c in old_conversations]
        conversation_count = len(conversation_ids)

        if conversation_count == 0:
            logger.info("[ARIA Cleanup] No old conversations found to delete")
            return {
                "success": True,
                "conversations_deleted": 0,
                "interactions_deleted": 0,
                "cutoff_date": cutoff_date.isoformat()
            }

        # Delete interactions first (foreign key constraint)
        interaction_count = db.query(ARIAInteraction).filter(
            ARIAInteraction.conversation_id.in_(conversation_ids)
        ).delete(synchronize_session=False)

        # Also delete interactions without conversation_id that are old
        orphan_interactions_deleted = db.query(ARIAInteraction).filter(
            and_(
                ARIAInteraction.conversation_id.is_(None),
                ARIAInteraction.timestamp < cutoff_date
            )
        ).delete(synchronize_session=False)

        # Delete conversations
        db.query(ARIAConversation).filter(
            ARIAConversation.id.in_(conversation_ids)
        ).delete(synchronize_session=False)

        db.commit()

        total_interactions = interaction_count + orphan_interactions_deleted

        logger.info(
            f"[ARIA Cleanup] Completed - Deleted {conversation_count} conversations "
            f"and {total_interactions} interactions (including {orphan_interactions_deleted} orphaned)"
        )

        return {
            "success": True,
            "conversations_deleted": conversation_count,
            "interactions_deleted": total_interactions,
            "orphan_interactions_deleted": orphan_interactions_deleted,
            "cutoff_date": cutoff_date.isoformat()
        }

    except Exception as e:
        logger.error(f"[ARIA Cleanup] Error during cleanup: {str(e)}")
        db.rollback()
        return {
            "success": False,
            "error": str(e),
            "conversations_deleted": 0,
            "interactions_deleted": 0
        }

    finally:
        if close_db:
            db.close()


async def cleanup_archived_conversations(db: Session = None, days_archived: int = 7) -> dict:
    """
    Permanently delete conversations that have been archived for a certain period.

    Args:
        db: Optional database session
        days_archived: Days after archiving before permanent deletion

    Returns:
        Dictionary with cleanup statistics
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days_archived)

        logger.info(f"[ARIA Cleanup] Cleaning up archived conversations older than {cutoff_date}")

        # Get archived conversations to permanently delete
        archived_conversations = db.query(ARIAConversation).filter(
            and_(
                ARIAConversation.is_archived == True,
                ARIAConversation.updated_at < cutoff_date
            )
        ).all()

        conversation_ids = [c.id for c in archived_conversations]
        conversation_count = len(conversation_ids)

        if conversation_count == 0:
            logger.info("[ARIA Cleanup] No old archived conversations found")
            return {
                "success": True,
                "conversations_deleted": 0,
                "interactions_deleted": 0
            }

        # Delete interactions first
        interaction_count = db.query(ARIAInteraction).filter(
            ARIAInteraction.conversation_id.in_(conversation_ids)
        ).delete(synchronize_session=False)

        # Delete conversations
        db.query(ARIAConversation).filter(
            ARIAConversation.id.in_(conversation_ids)
        ).delete(synchronize_session=False)

        db.commit()

        logger.info(
            f"[ARIA Cleanup] Permanently deleted {conversation_count} archived conversations "
            f"and {interaction_count} interactions"
        )

        return {
            "success": True,
            "conversations_deleted": conversation_count,
            "interactions_deleted": interaction_count
        }

    except Exception as e:
        logger.error(f"[ARIA Cleanup] Error during archived cleanup: {str(e)}")
        db.rollback()
        return {
            "success": False,
            "error": str(e)
        }

    finally:
        if close_db:
            db.close()


def run_cleanup_sync() -> dict:
    """
    Synchronous wrapper for running cleanup from cron jobs or Celery tasks.

    Returns:
        Dictionary with combined cleanup statistics
    """
    import asyncio

    async def run_all_cleanups():
        result1 = await cleanup_old_conversations()
        result2 = await cleanup_archived_conversations()
        return {
            "old_conversations": result1,
            "archived_conversations": result2,
            "success": result1.get("success", False) and result2.get("success", False)
        }

    return asyncio.run(run_all_cleanups())


# For use with APScheduler or similar
def get_cleanup_job():
    """
    Returns the cleanup function for use with APScheduler.

    Example usage:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler

        scheduler = AsyncIOScheduler()
        scheduler.add_job(get_cleanup_job(), 'cron', hour=3)
        scheduler.start()
    """
    return cleanup_old_conversations
