"""Creator Earnings model for tracking payouts."""
from sqlalchemy import Column, String, Numeric, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
from enum import Enum

from app.db.base_class import Base


class PayoutStatus(str, Enum):
    """Enum for payout status."""
    PENDING = "pending"
    PROCESSING = "processing"
    PAID = "paid"
    FAILED = "failed"


class CreatorEarnings(Base):
    """Model for tracking creator earnings and payouts."""
    
    __tablename__ = "creator_earnings"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    creator_id = Column(UUID(as_uuid=True), ForeignKey("creator_profiles.id", ondelete="CASCADE"), nullable=False, index=True)
    purchase_id = Column(UUID(as_uuid=True), ForeignKey("strategy_purchases.id", ondelete="CASCADE"), nullable=False)
    
    # Financial details
    gross_amount = Column(Numeric(precision=10, scale=2), nullable=False)  # Total amount paid by user
    platform_fee = Column(Numeric(precision=10, scale=2), nullable=False)  # Atomik's fee
    net_amount = Column(Numeric(precision=10, scale=2), nullable=False)  # Creator's earnings after fee
    
    # Payout information
    payout_status = Column(String(50), nullable=False, default=PayoutStatus.PENDING, index=True)
    payout_date = Column(DateTime(timezone=True), index=True)
    stripe_transfer_id = Column(String(100))  # Stripe transfer ID for tracking
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Relationships
    creator = relationship("CreatorProfile", back_populates="earnings")
    purchase = relationship("StrategyPurchase", back_populates="earnings")
    
    @property
    def is_payable(self):
        """Check if earning is ready for payout."""
        return self.payout_status == PayoutStatus.PENDING
    
    @property
    def platform_fee_percentage(self):
        """Calculate platform fee percentage."""
        if self.gross_amount == 0:
            return 0
        return (float(self.platform_fee) / float(self.gross_amount)) * 100
    
    def mark_as_processing(self):
        """Mark earning as processing for payout."""
        if self.payout_status != PayoutStatus.PENDING:
            raise ValueError("Can only process pending earnings")
        self.payout_status = PayoutStatus.PROCESSING
        
    def mark_as_paid(self, transfer_id: str):
        """Mark earning as paid with transfer reference."""
        if self.payout_status != PayoutStatus.PROCESSING:
            raise ValueError("Can only mark processing earnings as paid")
        self.payout_status = PayoutStatus.PAID
        self.payout_date = func.now()
        self.stripe_transfer_id = transfer_id
        
    def mark_as_failed(self):
        """Mark earning payout as failed."""
        if self.payout_status != PayoutStatus.PROCESSING:
            raise ValueError("Can only mark processing earnings as failed")
        self.payout_status = PayoutStatus.FAILED