"""Database model for user strategy code storage."""
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Numeric
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

    # Performance tracking (signals/errors)
    signals_generated = Column(Integer, default=0)
    last_signal_at = Column(DateTime, nullable=True)
    error_count = Column(Integer, default=0)
    last_error_at = Column(DateTime, nullable=True)
    last_error_message = Column(Text, nullable=True)

    # ==========================================================================
    # Phase 1.1: Cryptographic Hashing for Trust Verification
    # ==========================================================================

    # Hash fields for immutability verification
    code_hash = Column(String(64), nullable=True)  # SHA-256 of normalized code
    config_hash = Column(String(64), nullable=True)  # SHA-256 of config (symbols, etc)
    combined_hash = Column(String(64), nullable=True, unique=True, index=True)  # SHA-256(code_hash + config_hash)

    # Immutability tracking
    locked_at = Column(DateTime, nullable=True, index=True)  # When strategy became immutable
    parent_strategy_id = Column(Integer, ForeignKey("strategy_codes.id", ondelete="SET NULL"), nullable=True)

    # Live performance tracking (cached metrics for public verification)
    live_total_trades = Column(Integer, default=0, nullable=False)
    live_winning_trades = Column(Integer, default=0, nullable=False)
    live_total_pnl = Column(Numeric(12, 2), default=0, nullable=False)
    live_win_rate = Column(Numeric(5, 2), default=0, nullable=False)
    live_first_trade_at = Column(DateTime, nullable=True)
    live_last_trade_at = Column(DateTime, nullable=True)

    # Relationships
    user = relationship("User", back_populates="strategy_codes")
    activated_strategies = relationship("ActivatedStrategy", back_populates="strategy_code")

    # Self-referential relationship for version lineage
    parent = relationship("StrategyCode", remote_side=[id], backref="versions")

    # Trades linked to this specific version
    version_trades = relationship("Trade", back_populates="strategy_version", foreign_keys="Trade.strategy_version_id")

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

    # ==========================================================================
    # Phase 1.1: Hashing and Immutability Methods
    # ==========================================================================

    @property
    def is_locked(self) -> bool:
        """Check if strategy is locked (immutable)."""
        return self.locked_at is not None

    @property
    def short_hash(self) -> str:
        """Get shortened hash for display (first 8 characters)."""
        if self.combined_hash:
            return self.combined_hash[:8]
        return None

    def update_live_performance(self, pnl: float, is_win: bool):
        """Update cached live performance metrics after a trade closes."""
        from decimal import Decimal

        self.live_total_trades += 1
        if is_win:
            self.live_winning_trades += 1

        # Update PnL
        current_pnl = Decimal(str(self.live_total_pnl or 0))
        self.live_total_pnl = current_pnl + Decimal(str(pnl))

        # Recalculate win rate
        if self.live_total_trades > 0:
            self.live_win_rate = Decimal(str(
                (self.live_winning_trades / self.live_total_trades) * 100
            ))

        # Update timestamps
        now = datetime.utcnow()
        if not self.live_first_trade_at:
            self.live_first_trade_at = now
        self.live_last_trade_at = now

    def get_version_lineage(self) -> list:
        """Get list of all versions in this strategy's lineage."""
        lineage = []
        current = self
        while current.parent:
            lineage.append({
                'id': current.parent.id,
                'version': current.parent.version,
                'combined_hash': current.parent.combined_hash,
                'locked_at': current.parent.locked_at
            })
            current = current.parent
        return lineage

    def get_public_verification_data(self) -> dict:
        """Get data for public verification page."""
        return {
            'strategy_hash': self.combined_hash,
            'name': self.name,
            'version': self.version,
            'locked_at': self.locked_at.isoformat() if self.locked_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'performance': {
                'total_trades': self.live_total_trades,
                'winning_trades': self.live_winning_trades,
                'total_pnl': float(self.live_total_pnl) if self.live_total_pnl else 0,
                'win_rate': float(self.live_win_rate) if self.live_win_rate else 0,
                'first_trade': self.live_first_trade_at.isoformat() if self.live_first_trade_at else None,
                'last_trade': self.live_last_trade_at.isoformat() if self.live_last_trade_at else None,
            },
            'is_live_verified': True,  # All public metrics are live-only
            'parent_version_id': self.parent_strategy_id,
        }