# app/models/strategy_monetization.py
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, Numeric, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
from decimal import Decimal
from ..db.base_class import Base
import uuid


class StrategyMonetization(Base):
    """
    Main monetization tracking table for strategies.
    Links webhooks to Stripe products and tracks revenue metrics.
    """
    __tablename__ = "strategy_monetization"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    webhook_id = Column(Integer, ForeignKey("webhooks.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    stripe_product_id = Column(String(100), nullable=False, index=True)
    creator_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    total_subscribers = Column(Integer, nullable=False, default=0)
    estimated_monthly_revenue = Column(Numeric(10, 2), nullable=False, default=Decimal('0.00'))
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    webhook = relationship("Webhook", back_populates="strategy_monetization", uselist=False)
    creator = relationship("User", foreign_keys=[creator_user_id])
    prices = relationship("StrategyPrice", back_populates="monetization", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<StrategyMonetization(id={self.id}, webhook_id={self.webhook_id}, active={self.is_active})>"

    def to_dict(self) -> dict:
        """Convert to dictionary representation"""
        return {
            'id': str(self.id),
            'webhook_id': self.webhook_id,
            'stripe_product_id': self.stripe_product_id,
            'creator_user_id': self.creator_user_id,
            'is_active': self.is_active,
            'total_subscribers': self.total_subscribers,
            'estimated_monthly_revenue': float(self.estimated_monthly_revenue),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

    def calculate_monthly_revenue(self) -> Decimal:
        """Calculate estimated monthly revenue from active prices"""
        monthly_revenue = Decimal('0.00')
        
        for price in self.prices:
            if not price.is_active:
                continue
                
            if price.price_type == 'monthly':
                monthly_revenue += price.amount
            elif price.price_type == 'yearly':
                monthly_revenue += price.amount / 12
            elif price.price_type == 'lifetime':
                # Estimate lifetime as 24 months for revenue calculation
                monthly_revenue += price.amount / 24
                
        return monthly_revenue.quantize(Decimal('0.01'))

    def get_active_prices(self) -> list:
        """Get all active pricing options"""
        return [price for price in self.prices if price.is_active]

    def get_price_by_type(self, price_type: str):
        """Get active price by type (monthly, yearly, lifetime, setup)"""
        for price in self.prices:
            if price.price_type == price_type and price.is_active:
                return price
        return None

    def update_revenue_estimate(self):
        """Update the estimated monthly revenue based on current pricing"""
        self.estimated_monthly_revenue = self.calculate_monthly_revenue()


class StrategyPrice(Base):
    """
    Multiple pricing options per strategy (monthly, yearly, lifetime, setup).
    Each price corresponds to a Stripe Price object.
    """
    __tablename__ = "strategy_prices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    strategy_monetization_id = Column(UUID(as_uuid=True), ForeignKey("strategy_monetization.id", ondelete="CASCADE"), nullable=False, index=True)
    price_type = Column(String(20), nullable=False, index=True)  # 'monthly'|'yearly'|'lifetime'|'setup'
    stripe_price_id = Column(String(100), nullable=False, index=True)
    amount = Column(Numeric(10, 2), nullable=False)
    currency = Column(String(3), nullable=False, default='usd')
    billing_interval = Column(String(20), nullable=True)  # 'month'|'year'|NULL for one-time
    trial_period_days = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    monetization = relationship("StrategyMonetization", back_populates="prices")

    # Constraints
    __table_args__ = (
        CheckConstraint("price_type IN ('monthly', 'yearly', 'lifetime', 'setup')", name='ck_price_type_values'),
        CheckConstraint("currency IN ('usd', 'eur', 'gbp')", name='ck_currency_values'),
        CheckConstraint("billing_interval IS NULL OR billing_interval IN ('month', 'year')", name='ck_billing_interval_values'),
        CheckConstraint("amount > 0", name='ck_amount_positive'),
        CheckConstraint("trial_period_days >= 0", name='ck_trial_period_non_negative'),
    )

    def __repr__(self):
        return f"<StrategyPrice(id={self.id}, type={self.price_type}, amount={self.amount})>"

    def to_dict(self) -> dict:
        """Convert to dictionary representation"""
        return {
            'id': str(self.id),
            'strategy_monetization_id': str(self.strategy_monetization_id),
            'price_type': self.price_type,
            'stripe_price_id': self.stripe_price_id,
            'amount': float(self.amount),
            'currency': self.currency,
            'billing_interval': self.billing_interval,
            'trial_period_days': self.trial_period_days,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

    @property
    def is_subscription(self) -> bool:
        """Check if this is a subscription price (monthly/yearly)"""
        return self.price_type in ['monthly', 'yearly']

    @property
    def is_one_time(self) -> bool:
        """Check if this is a one-time payment (lifetime/setup)"""
        return self.price_type in ['lifetime', 'setup']

    @property
    def display_name(self) -> str:
        """Get user-friendly display name for price type"""
        display_names = {
            'monthly': 'Monthly Subscription',
            'yearly': 'Yearly Subscription',
            'lifetime': 'Lifetime Access',
            'setup': 'Setup Fee'
        }
        return display_names.get(self.price_type, self.price_type.title())

    @property
    def display_amount(self) -> str:
        """Get formatted amount for display"""
        amount_str = f"${self.amount:.2f}"
        
        if self.price_type == 'monthly':
            return f"{amount_str}/month"
        elif self.price_type == 'yearly':
            return f"{amount_str}/year"
        elif self.price_type == 'lifetime':
            return f"{amount_str} one-time"
        elif self.price_type == 'setup':
            return f"{amount_str} setup fee"
        
        return amount_str

    def deactivate(self):
        """Deactivate this price option"""
        self.is_active = False
        self.updated_at = datetime.utcnow()

    def reactivate(self):
        """Reactivate this price option"""
        self.is_active = True
        self.updated_at = datetime.utcnow()