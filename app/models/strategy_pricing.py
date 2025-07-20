"""Strategy Pricing model for monetized strategies."""
from sqlalchemy import Column, String, Integer, Boolean, Numeric, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
from enum import Enum

from app.db.base_class import Base


class PricingType(str, Enum):
    """Enum for strategy pricing types."""
    FREE = "free"
    ONE_TIME = "one_time"
    SUBSCRIPTION = "subscription"
    INITIATION_PLUS_SUB = "initiation_plus_sub"


class BillingInterval(str, Enum):
    """Enum for subscription billing intervals."""
    MONTHLY = "monthly"
    YEARLY = "yearly"


class StrategyPricing(Base):
    """Model for strategy pricing configurations."""
    
    __tablename__ = "strategy_pricing"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    webhook_id = Column(Integer, ForeignKey("webhooks.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    
    # Pricing configuration
    pricing_type = Column(String(50), nullable=False, index=True)  # free, one_time, subscription, initiation_plus_sub
    billing_interval = Column(String(20))  # monthly, yearly - only for subscription types
    base_amount = Column(Numeric(precision=10, scale=2))  # Main price
    yearly_amount = Column(Numeric(precision=10, scale=2))  # Yearly price (optional discount)
    setup_fee = Column(Numeric(precision=10, scale=2))  # For initiation_plus_sub model
    
    # Trial configuration
    trial_days = Column(Integer, default=0, nullable=False)
    is_trial_enabled = Column(Boolean, default=False, nullable=False)
    
    # Stripe integration
    stripe_price_id = Column(String(100))  # For monthly subscription pricing in Stripe
    stripe_yearly_price_id = Column(String(100))  # For yearly subscription pricing in Stripe
    
    # Status
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Relationships
    webhook = relationship("Webhook", back_populates="pricing")
    purchases = relationship("StrategyPurchase", back_populates="pricing", cascade="all, delete-orphan")
    
    @property
    def display_price(self):
        """Get formatted display price for UI."""
        if self.pricing_type == PricingType.FREE:
            return "Free"
        elif self.pricing_type == PricingType.ONE_TIME:
            return f"${self.base_amount:.2f}"
        elif self.pricing_type == PricingType.SUBSCRIPTION:
            if self.billing_interval == BillingInterval.YEARLY and self.yearly_amount:
                monthly_equivalent = self.yearly_amount / 12
                return f"${self.yearly_amount:.2f}/year (${monthly_equivalent:.2f}/mo)"
            return f"${self.base_amount:.2f}/month"
        elif self.pricing_type == PricingType.INITIATION_PLUS_SUB:
            if self.billing_interval == BillingInterval.YEARLY and self.yearly_amount:
                return f"${self.setup_fee:.2f} setup + ${self.yearly_amount:.2f}/year"
            return f"${self.setup_fee:.2f} setup + ${self.base_amount:.2f}/month"
        return "Custom pricing"
    
    @property
    def has_multiple_billing_options(self):
        """Check if strategy offers both monthly and yearly pricing."""
        if self.pricing_type not in [PricingType.SUBSCRIPTION, PricingType.INITIATION_PLUS_SUB]:
            return False
        return self.base_amount is not None and self.yearly_amount is not None
    
    def get_price_for_interval(self, interval: str):
        """Get price for specific billing interval."""
        if interval == BillingInterval.YEARLY and self.yearly_amount:
            return float(self.yearly_amount)
        return float(self.base_amount)
    
    @property
    def total_initial_cost(self):
        """Calculate total initial cost including setup fees."""
        if self.pricing_type == PricingType.FREE:
            return 0
        elif self.pricing_type == PricingType.INITIATION_PLUS_SUB:
            if self.is_trial_enabled:
                return float(self.setup_fee)  # Only setup fee during trial
            else:
                # Setup fee + first period payment
                if self.billing_interval == BillingInterval.YEARLY and self.yearly_amount:
                    return float(self.setup_fee) + float(self.yearly_amount)
                return float(self.setup_fee) + float(self.base_amount)
        elif self.pricing_type == PricingType.SUBSCRIPTION and self.is_trial_enabled:
            return 0  # No initial cost with trial
        elif self.pricing_type == PricingType.SUBSCRIPTION:
            # First period payment
            if self.billing_interval == BillingInterval.YEARLY and self.yearly_amount:
                return float(self.yearly_amount)
            return float(self.base_amount)
        else:
            return float(self.base_amount)
    
    def validate_pricing(self):
        """Validate pricing configuration."""
        if self.pricing_type == PricingType.FREE:
            return self.base_amount is None or self.base_amount == 0
        
        if self.pricing_type in [PricingType.ONE_TIME, PricingType.SUBSCRIPTION]:
            return self.base_amount is not None and self.base_amount > 0
        
        if self.pricing_type == PricingType.INITIATION_PLUS_SUB:
            return (self.base_amount is not None and self.base_amount > 0 and
                    self.setup_fee is not None and self.setup_fee > 0)
        
        return False