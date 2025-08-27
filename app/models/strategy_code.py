"""Database model for user strategy code storage."""
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime

from ..db.base_class import Base


class StrategyCode(Base):
    """Model for storing user strategy code for Strategy Engine execution."""
    __tablename__ = "strategy_codes"

    # Primary Key
    id = Column(Integer, primary_key=True, index=True)

    # User relationship
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # Strategy identification
    name = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=True)
    
    # Strategy code
    code = Column(Text, nullable=False)
    symbols = Column(String(500), nullable=True)  # JSON string of symbols like ["ES", "NQ"]
    
    # Status and execution
    is_active = Column(Boolean, default=False, index=True)
    is_validated = Column(Boolean, default=False)
    validation_error = Column(Text, nullable=True)
    
    # Metadata
    version = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    activated_at = Column(DateTime, nullable=True)
    deactivated_at = Column(DateTime, nullable=True)
    
    # Performance tracking
    signals_generated = Column(Integer, default=0)
    last_signal_at = Column(DateTime, nullable=True)
    error_count = Column(Integer, default=0)
    last_error_at = Column(DateTime, nullable=True)
    last_error_message = Column(Text, nullable=True)

    # Relationships
    user = relationship("User", back_populates="strategy_codes")

    def __repr__(self):
        return f"<StrategyCode(id={self.id}, name='{self.name}', user_id={self.user_id}, active={self.is_active})>"

    @property
    def symbols_list(self):
        """Get symbols as a list."""
        if not self.symbols:
            return []
        import json
        try:
            return json.loads(self.symbols)
        except (json.JSONDecodeError, TypeError):
            return []

    def set_symbols_list(self, symbols_list):
        """Set symbols from a list."""
        import json
        self.symbols = json.dumps(symbols_list) if symbols_list else None

    def increment_signal_count(self):
        """Increment signal count and update timestamp."""
        self.signals_generated += 1
        self.last_signal_at = datetime.utcnow()

    def record_error(self, error_message: str):
        """Record an error for this strategy."""
        self.error_count += 1
        self.last_error_at = datetime.utcnow()
        self.last_error_message = error_message[:1000]  # Truncate long error messages