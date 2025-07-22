# In app/models/user.py
from sqlalchemy import Boolean, Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
from ..db.base_class import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    full_name = Column(String, nullable=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    is_active = Column(Boolean, default=True)
    app_role = Column(String, nullable=True)  # 'admin', 'moderator', 'beta_tester', None
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    
    # Profile fields
    profile_picture = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    website = Column(String, nullable=True)
    
    # Social media links
    x_handle = Column(String, nullable=True)  # X (formerly Twitter)
    tiktok_handle = Column(String, nullable=True)
    instagram_handle = Column(String, nullable=True)
    youtube_handle = Column(String, nullable=True)
    discord_handle = Column(String, nullable=True)
    
    # Add promo_code_id column
    promo_code_id = Column(Integer, ForeignKey("promo_codes.id", ondelete="SET NULL"), nullable=True)
    
    # Creator marketplace field
    creator_profile_id = Column(UUID(as_uuid=True), ForeignKey("creator_profiles.id", ondelete="SET NULL"), nullable=True)
    
    # Creator onboarding progress tracking
    onboarding_step = Column(Integer, nullable=True)  # 1, 2, 3, or None (completed)
    onboarding_data = Column(JSON, nullable=True)     # Temporary form data during onboarding

    # Relationships
    webhooks = relationship("Webhook", back_populates="user", cascade="all, delete-orphan")
    broker_accounts = relationship("BrokerAccount", back_populates="user", cascade="all, delete-orphan")
    strategies = relationship("ActivatedStrategy", back_populates="user", cascade="all, delete-orphan")
    subscription = relationship("Subscription", back_populates="user", uselist=False)
    orders = relationship("Order", back_populates="user", cascade="all, delete-orphan")
    trades = relationship("Trade", back_populates="user", cascade="all, delete-orphan")
    affiliate = relationship("Affiliate", back_populates="user", uselist=False)
    
    # Creator marketplace relationships
    creator_profile = relationship("CreatorProfile", back_populates="user", uselist=False, foreign_keys="CreatorProfile.user_id")
    strategy_purchases = relationship("StrategyPurchase", back_populates="user", cascade="all, delete-orphan")
    
    def __str__(self):
        return f"User(email={self.email})"
    
    # App role helper methods
    def is_admin(self) -> bool:
        """Check if user has admin app role"""
        return self.app_role == 'admin'
    
    def is_moderator(self) -> bool:
        """Check if user has moderator or admin app role"""
        return self.app_role in ['admin', 'moderator']
    
    def is_beta_tester(self) -> bool:
        """Check if user has beta tester, moderator, or admin app role"""
        return self.app_role in ['admin', 'moderator', 'beta_tester']
    
    def is_creator(self) -> bool:
        """Check if user is a verified creator"""
        return self.creator_profile is not None and self.creator_profile.is_verified
    
    def has_app_role(self, role: str) -> bool:
        """Check if user has a specific app role"""
        return self.app_role == role