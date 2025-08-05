# app/models/strategy_metrics.py
from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey, Index, Date, UniqueConstraint, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid

from ..db.base_class import Base


class StrategyMetrics(Base):
    """Track only non-financial metrics that Stripe doesn't provide"""
    __tablename__ = "strategy_metrics"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    strategy_id = Column(UUID(as_uuid=True), ForeignKey("webhooks.id"), nullable=False)
    date = Column(Date, nullable=False)
    
    # Metrics Stripe doesn't track
    views = Column(Integer, default=0)
    unique_viewers = Column(Integer, default=0)
    trial_starts = Column(Integer, default=0)
    
    # Engagement metrics
    avg_view_duration = Column(Float, default=0.0)  # seconds
    shares = Column(Integer, default=0)
    
    # Conversion funnel (non-financial)
    monetization_page_views = Column(Integer, default=0)  # Viewed pricing
    checkout_starts = Column(Integer, default=0)  # Started checkout (before payment)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    # TODO: Uncomment after webhook metrics relationship is restored
    # strategy = relationship("Webhook", back_populates="metrics")
    
    # Ensure one record per strategy per day
    __table_args__ = (
        UniqueConstraint('strategy_id', 'date', name='uq_strategy_metrics_date'),
        Index('idx_strategy_metrics_date', 'strategy_id', 'date'),
    )


class CreatorDashboardCache(Base):
    """Cache expensive calculations for dashboard performance"""
    __tablename__ = "creator_dashboard_cache"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    creator_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    cache_key = Column(String, nullable=False)  # e.g., "revenue_30d", "subscribers_total"
    cache_value = Column(JSON, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    # TODO: Uncomment after user dashboard_cache relationship is restored
    # creator = relationship("User", back_populates="dashboard_cache")
    
    # Ensure unique cache keys per creator
    __table_args__ = (
        UniqueConstraint('creator_id', 'cache_key', name='uq_creator_cache_key'),
        Index('idx_creator_cache_expires', 'creator_id', 'expires_at'),
    )