"""Strategy Purchase model for tracking strategy sales."""
from sqlalchemy import Column, String, Boolean, Numeric, ForeignKey, DateTime, Text, UniqueConstraint, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
from enum import Enum

from app.database import Base


class PurchaseStatus(str, Enum):
    """Enum for purchase status."""
    PENDING = "pending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class PurchaseType(str, Enum):
    """Enum for purchase types."""
    ONE_TIME = "one_time"
    SUBSCRIPTION = "subscription"


class StrategyPurchase(Base):
    """Model for tracking strategy purchases and subscriptions."""
    
    __tablename__ = "strategy_purchases"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    webhook_id = Column(Integer, ForeignKey("webhooks.id", ondelete="CASCADE"), nullable=False, index=True)
    pricing_id = Column(UUID(as_uuid=True), ForeignKey("strategy_pricing.id", ondelete="CASCADE"), nullable=False)
    
    # Payment information
    stripe_payment_intent_id = Column(String(100))  # For one-time payments
    stripe_subscription_id = Column(String(100), index=True)  # For subscriptions
    
    # Financial details
    amount_paid = Column(Numeric(precision=10, scale=2), nullable=False)
    platform_fee = Column(Numeric(precision=10, scale=2), nullable=False)
    creator_payout = Column(Numeric(precision=10, scale=2), nullable=False)
    
    # Purchase details
    purchase_type = Column(String(50), nullable=False)  # one_time, subscription
    status = Column(String(50), nullable=False, default=PurchaseStatus.PENDING, index=True)
    
    # Trial information
    trial_ends_at = Column(DateTime(timezone=True), index=True)
    
    # Cancellation/Refund
    cancelled_at = Column(DateTime(timezone=True))
    refunded_at = Column(DateTime(timezone=True))
    refund_amount = Column(Numeric(precision=10, scale=2))
    refund_reason = Column(Text)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Relationships
    user = relationship("User", back_populates="strategy_purchases")
    webhook = relationship("Webhook", back_populates="purchases")
    pricing = relationship("StrategyPricing", back_populates="purchases")
    earnings = relationship("CreatorEarnings", back_populates="purchase", cascade="all, delete-orphan")
    
    # Constraints
    __table_args__ = (
        UniqueConstraint(
            'user_id', 'webhook_id',
            name='uq_strategy_purchases_user_webhook_active'
            # Note: Partial unique constraint (only active purchases) should be implemented
            # via database migration or trigger for production use
        ),
    )
    
    @property
    def is_active(self):
        """Check if purchase is currently active."""
        return self.status in [PurchaseStatus.PENDING, PurchaseStatus.COMPLETED]
    
    @property
    def is_in_trial(self):
        """Check if purchase is currently in trial period."""
        if not self.trial_ends_at:
            return False
        return self.trial_ends_at > func.now() and self.status == PurchaseStatus.COMPLETED
    
    @property
    def can_refund(self):
        """Check if purchase is eligible for refund (within 7 days)."""
        if self.status != PurchaseStatus.COMPLETED:
            return False
        if self.refunded_at:
            return False
        
        # 7-day refund window
        from datetime import datetime, timedelta
        refund_window = self.created_at + timedelta(days=7)
        return datetime.now() < refund_window
    
    def calculate_refund_amount(self):
        """Calculate refund amount based on usage."""
        if not self.can_refund:
            return 0
        
        # For now, full refund within 7 days
        # Future: Implement pro-rated refunds
        return float(self.amount_paid)