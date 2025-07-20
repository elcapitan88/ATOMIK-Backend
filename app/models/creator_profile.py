"""Creator Profile model for marketplace creators."""
from sqlalchemy import Column, String, Integer, Boolean, Numeric, ForeignKey, DateTime, Text, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid

from app.db.base_class import Base


class CreatorProfile(Base):
    """Model for creator profiles in the marketplace."""
    
    __tablename__ = "creator_profiles"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    
    # Profile information
    display_name = Column(String(100))  # Will use atomik username
    bio = Column(Text)
    trading_experience = Column(String(50))  # beginner, intermediate, advanced, professional
    
    # Creator metrics
    total_subscribers = Column(Integer, default=0, nullable=False)
    current_tier = Column(String(20), default="bronze", nullable=False, index=True)  # bronze, silver, gold
    platform_fee_override = Column(Numeric(precision=3, scale=2))  # Admin override for platform fee
    
    # Stripe Connect
    stripe_connect_account_id = Column(String(100), unique=True, index=True)
    
    # Verification
    is_verified = Column(Boolean, default=False, nullable=False)
    two_fa_enabled = Column(Boolean, default=False, nullable=False)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Relationships
    user = relationship("User", back_populates="creator_profile", foreign_keys=[user_id])
    earnings = relationship("CreatorEarnings", back_populates="creator", cascade="all, delete-orphan")
    
    @property
    def platform_fee(self):
        """Calculate platform fee based on tier or override."""
        if self.platform_fee_override is not None:
            return float(self.platform_fee_override)
        
        # Tier-based fees
        tier_fees = {
            'bronze': 0.20,   # <100 subscribers
            'silver': 0.15,   # 100+ subscribers
            'gold': 0.10      # 200+ subscribers
        }
        return tier_fees.get(self.current_tier, 0.20)
    
    def calculate_tier(self):
        """Calculate creator tier based on total subscribers."""
        if self.total_subscribers >= 200:
            return 'gold'
        elif self.total_subscribers >= 100:
            return 'silver'
        else:
            return 'bronze'
    
    def update_tier(self):
        """Update tier based on current subscriber count."""
        new_tier = self.calculate_tier()
        if new_tier != self.current_tier:
            self.current_tier = new_tier
            return True
        return False