# app/models/discord.py
# Discord integration models for ARIA

from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime

from ..db.base_class import Base


class DiscordLink(Base):
    """
    Links Discord accounts to Atomik user accounts.

    Enables ARIA to identify users messaging from Discord
    and associate them with their trading data.
    """
    __tablename__ = "discord_links"

    id = Column(Integer, primary_key=True, index=True)

    # Atomik user reference
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    # Discord identifiers (stored as strings for large snowflake IDs)
    discord_user_id = Column(String(32), unique=True, index=True, nullable=False)
    discord_username = Column(String(100), nullable=True)
    discord_discriminator = Column(String(10), nullable=True)  # Legacy, Discord removed these
    discord_avatar = Column(String(255), nullable=True)

    # OAuth tokens (for future use if needed)
    access_token = Column(Text, nullable=True)
    refresh_token = Column(Text, nullable=True)
    token_expires_at = Column(DateTime, nullable=True)

    # Link metadata
    is_active = Column(Boolean, default=True, nullable=False)
    linked_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_used_at = Column(DateTime, nullable=True)

    # Relationship to User
    user = relationship("User", backref="discord_link")

    def __repr__(self):
        return f"<DiscordLink user_id={self.user_id} discord={self.discord_username}>"


class DiscordUserThread(Base):
    """
    Maps Discord users to their ARIA conversation threads.

    Each user gets a dedicated thread in the ARIA channel
    for organized, persistent conversations.
    """
    __tablename__ = "discord_user_threads"

    id = Column(Integer, primary_key=True, index=True)

    # Discord identifiers
    discord_user_id = Column(String(32), unique=True, index=True, nullable=False)
    discord_username = Column(String(100), nullable=True)
    thread_id = Column(String(32), nullable=False, index=True)

    # Thread metadata
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_active = Column(DateTime, default=datetime.utcnow, nullable=False)
    is_archived = Column(Boolean, default=False, nullable=False)

    def __repr__(self):
        return f"<DiscordUserThread discord_user={self.discord_username} thread={self.thread_id}>"


class PendingDiscordLink(Base):
    """
    Temporary storage for pending Discord account links.

    Used for magic link flow where Discord-first users
    need to authenticate on the web before linking.
    """
    __tablename__ = "pending_discord_links"

    id = Column(Integer, primary_key=True, index=True)

    # Link token (magic link)
    token = Column(String(64), unique=True, index=True, nullable=False)

    # Discord info from the bot
    discord_user_id = Column(String(32), nullable=False)
    discord_username = Column(String(100), nullable=True)

    # Expiration
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)

    # Status
    is_used = Column(Boolean, default=False, nullable=False)
    used_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    used_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<PendingDiscordLink discord={self.discord_username} token={self.token[:8]}...>"
