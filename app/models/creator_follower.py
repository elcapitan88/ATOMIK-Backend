"""Creator Follower model for social following system."""
from sqlalchemy import Column, Integer, ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base_class import Base


class CreatorFollower(Base):
    """Model for tracking creator-follower relationships."""

    __tablename__ = "creator_followers"

    id = Column(Integer, primary_key=True, index=True)
    follower_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    creator_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    followed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Ensure a user can't follow the same creator twice
    __table_args__ = (
        UniqueConstraint('follower_user_id', 'creator_user_id', name='_follower_creator_uc'),
    )

    # Relationships
    follower = relationship("User", foreign_keys=[follower_user_id], backref="following")
    creator = relationship("User", foreign_keys=[creator_user_id], backref="followers")

    def __repr__(self):
        return f"<CreatorFollower(follower_id={self.follower_user_id}, creator_id={self.creator_user_id})>"