# In app/models/user.py
from sqlalchemy import Boolean, Column, Integer, String, DateTime, ForeignKey, JSON, Enum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
from ..db.base_class import Base

# Phase 1.2: User mode enum for strict user type separation
import enum

class UserMode(str, enum.Enum):
    SUBSCRIBER = "subscriber"
    PRIVATE_CREATOR = "private_creator"
    PUBLIC_CREATOR = "public_creator"


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

    # Phase 1.2: User mode for strict type separation
    user_mode = Column(
        Enum(UserMode, name='user_mode_enum'),
        default=UserMode.SUBSCRIBER,
        nullable=False,
        index=True
    )
    
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
    strategy_codes = relationship("StrategyCode", back_populates="user", cascade="all, delete-orphan")
    subscription = relationship("Subscription", back_populates="user", uselist=False)
    orders = relationship("Order", back_populates="user", cascade="all, delete-orphan")
    trades = relationship("Trade", back_populates="user", cascade="all, delete-orphan")
    affiliate = relationship("Affiliate", back_populates="user", uselist=False)
    
    # Creator marketplace relationships
    creator_profile = relationship("CreatorProfile", back_populates="user", uselist=False, foreign_keys="CreatorProfile.user_id")
    strategy_purchases = relationship("StrategyPurchase", back_populates="user", cascade="all, delete-orphan")
    
    # Analytics relationships (simplified)
    # TODO: Uncomment after creator_dashboard_cache table migration is fixed
    # dashboard_cache = relationship("CreatorDashboardCache", back_populates="creator", cascade="all, delete-orphan")
    
    # ARIA Assistant relationships
    trading_profile = relationship("UserTradingProfile", back_populates="user", uselist=False)
    
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

    # ==========================================================================
    # Phase 1.2: User Mode Helper Methods
    # ==========================================================================

    def is_subscriber(self) -> bool:
        """Check if user is in subscriber mode (cannot create strategies)"""
        return self.user_mode == UserMode.SUBSCRIBER

    def is_private_creator(self) -> bool:
        """Check if user is a private creator (can create but not publish)"""
        return self.user_mode == UserMode.PRIVATE_CREATOR

    def is_public_creator(self) -> bool:
        """Check if user is a public creator (can publish to marketplace)"""
        return self.user_mode == UserMode.PUBLIC_CREATOR

    def can_create_strategies(self) -> bool:
        """Check if user can create strategies (any creator mode)"""
        return self.user_mode in [UserMode.PRIVATE_CREATOR, UserMode.PUBLIC_CREATOR]

    def can_publish_strategies(self) -> bool:
        """Check if user can publish strategies to marketplace"""
        return self.user_mode == UserMode.PUBLIC_CREATOR

    def upgrade_to_private_creator(self):
        """Upgrade user to private creator mode"""
        if self.user_mode == UserMode.SUBSCRIBER:
            self.user_mode = UserMode.PRIVATE_CREATOR

    def upgrade_to_public_creator(self):
        """Upgrade user to public creator mode"""
        self.user_mode = UserMode.PUBLIC_CREATOR