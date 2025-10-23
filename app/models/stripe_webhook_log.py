"""
Stripe webhook event logging for retry and monitoring
"""
from sqlalchemy import Column, String, Integer, Boolean, DateTime, JSON, Text
from sqlalchemy.sql import func
from app.db.base_class import Base
import uuid

class StripeWebhookLog(Base):
    __tablename__ = "stripe_webhook_logs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    stripe_event_id = Column(String, unique=True, nullable=False, index=True)
    event_type = Column(String, nullable=False, index=True)
    webhook_endpoint = Column(String, nullable=False)

    # Processing status
    status = Column(String, nullable=False, default="pending")  # pending, processing, success, failed
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)

    # Event data
    event_data = Column(JSON)
    error_message = Column(Text)
    error_details = Column(JSON)

    # Timestamps
    received_at = Column(DateTime(timezone=True), server_default=func.now())
    processed_at = Column(DateTime(timezone=True))
    next_retry_at = Column(DateTime(timezone=True))

    # Metadata
    customer_id = Column(String, index=True)
    subscription_id = Column(String, index=True)
    user_id = Column(Integer, index=True)
    webhook_id = Column(Integer, index=True)

    def __repr__(self):
        return f"<StripeWebhookLog {self.stripe_event_id} - {self.event_type} - {self.status}>"