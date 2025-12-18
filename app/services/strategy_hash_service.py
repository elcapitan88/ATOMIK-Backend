"""
Strategy Hash Service - Phase 1.1 Trust Foundation

Provides cryptographic hashing for strategy code verification.
Ensures strategy immutability once locked/published.
"""
import hashlib
import json
from datetime import datetime
from typing import Optional, Dict, Any, Tuple
from sqlalchemy.orm import Session

from app.models.strategy_code import StrategyCode


class StrategyHashService:
    """Service for computing and managing strategy hashes."""

    def __init__(self, db: Session = None):
        self.db = db

    @staticmethod
    def normalize_code(code: str) -> str:
        """
        Normalize code for consistent hashing.
        Removes trailing whitespace and ensures consistent line endings.
        """
        if not code:
            return ""
        # Normalize line endings to \n and strip trailing whitespace
        lines = code.replace('\r\n', '\n').replace('\r', '\n').split('\n')
        normalized_lines = [line.rstrip() for line in lines]
        # Remove trailing empty lines but keep internal structure
        while normalized_lines and not normalized_lines[-1]:
            normalized_lines.pop()
        return '\n'.join(normalized_lines)

    @staticmethod
    def compute_code_hash(code: str) -> str:
        """
        Compute SHA-256 hash of normalized strategy code.

        Args:
            code: The strategy code to hash

        Returns:
            64-character hex string (SHA-256 hash)
        """
        normalized = StrategyHashService.normalize_code(code)
        return hashlib.sha256(normalized.encode('utf-8')).hexdigest()

    @staticmethod
    def compute_config_hash(
        symbols: list = None,
        **other_config
    ) -> str:
        """
        Compute SHA-256 hash of strategy configuration.
        Configuration includes symbols and any other config parameters.

        Args:
            symbols: List of trading symbols (e.g., ["ES", "NQ"])
            **other_config: Additional configuration parameters

        Returns:
            64-character hex string (SHA-256 hash)
        """
        config = {
            'symbols': sorted(symbols) if symbols else [],
            **{k: v for k, v in sorted(other_config.items()) if v is not None}
        }
        config_str = json.dumps(config, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(config_str.encode('utf-8')).hexdigest()

    @staticmethod
    def compute_combined_hash(code_hash: str, config_hash: str) -> str:
        """
        Compute combined hash from code and config hashes.
        This is the primary identifier for strategy verification.

        Args:
            code_hash: SHA-256 hash of the code
            config_hash: SHA-256 hash of the config

        Returns:
            64-character hex string (SHA-256 hash)
        """
        combined = f"{code_hash}:{config_hash}"
        return hashlib.sha256(combined.encode('utf-8')).hexdigest()

    def compute_strategy_hashes(self, strategy: StrategyCode) -> Dict[str, str]:
        """
        Compute all hashes for a strategy.

        Args:
            strategy: StrategyCode model instance

        Returns:
            Dict with code_hash, config_hash, and combined_hash
        """
        code_hash = self.compute_code_hash(strategy.code)
        config_hash = self.compute_config_hash(strategy.symbols_list)
        combined_hash = self.compute_combined_hash(code_hash, config_hash)

        return {
            'code_hash': code_hash,
            'config_hash': config_hash,
            'combined_hash': combined_hash
        }

    def lock_strategy(self, strategy: StrategyCode) -> StrategyCode:
        """
        Lock a strategy, making it immutable.
        Computes and stores all hashes, sets locked_at timestamp.

        Args:
            strategy: StrategyCode to lock

        Returns:
            The locked strategy

        Raises:
            ValueError: If strategy is already locked
            ValueError: If strategy is not validated
        """
        if strategy.locked_at:
            raise ValueError(
                f"Strategy {strategy.id} is already locked. "
                f"Locked at: {strategy.locked_at.isoformat()}, "
                f"Hash: {strategy.combined_hash}"
            )

        if not strategy.is_validated:
            raise ValueError(
                f"Strategy {strategy.id} must be validated before locking. "
                "Run validation first."
            )

        # Compute hashes
        hashes = self.compute_strategy_hashes(strategy)

        # Check for hash collision (shouldn't happen with SHA-256)
        if self.db:
            existing = self.db.query(StrategyCode).filter(
                StrategyCode.combined_hash == hashes['combined_hash'],
                StrategyCode.id != strategy.id
            ).first()
            if existing:
                raise ValueError(
                    f"Hash collision detected with strategy {existing.id}. "
                    "This is extremely rare - please contact support."
                )

        # Apply hashes and lock
        strategy.code_hash = hashes['code_hash']
        strategy.config_hash = hashes['config_hash']
        strategy.combined_hash = hashes['combined_hash']
        strategy.locked_at = datetime.utcnow()

        if self.db:
            self.db.commit()
            self.db.refresh(strategy)

        return strategy

    def create_new_version(
        self,
        parent_strategy: StrategyCode,
        new_code: str = None,
        new_symbols: list = None,
        new_name: str = None,
        new_description: str = None
    ) -> StrategyCode:
        """
        Create a new version of a locked strategy.
        The new version starts with a clean slate (no performance history).

        Args:
            parent_strategy: The parent strategy to version from
            new_code: Optional new code (defaults to parent's code)
            new_symbols: Optional new symbols (defaults to parent's symbols)
            new_name: Optional new name (defaults to parent's name)
            new_description: Optional new description (defaults to parent's description)

        Returns:
            New StrategyCode instance (not yet committed)

        Raises:
            ValueError: If database session not available
        """
        if not self.db:
            raise ValueError("Database session required for creating versions")

        new_strategy = StrategyCode(
            user_id=parent_strategy.user_id,
            name=new_name or parent_strategy.name,
            description=new_description or parent_strategy.description,
            code=new_code if new_code is not None else parent_strategy.code,
            symbols=json.dumps(new_symbols) if new_symbols is not None else parent_strategy.symbols,
            version=parent_strategy.version + 1,
            parent_strategy_id=parent_strategy.id,
            is_active=False,
            is_validated=False,
            # Reset all performance metrics for new version
            live_total_trades=0,
            live_winning_trades=0,
            live_total_pnl=0,
            live_win_rate=0,
            live_first_trade_at=None,
            live_last_trade_at=None,
            signals_generated=0,
            error_count=0
        )

        self.db.add(new_strategy)
        self.db.commit()
        self.db.refresh(new_strategy)

        return new_strategy

    def verify_strategy_hash(self, strategy: StrategyCode) -> Tuple[bool, Optional[str]]:
        """
        Verify that a strategy's stored hash matches its current code/config.
        Used to detect any tampering or corruption.

        Args:
            strategy: StrategyCode to verify

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not strategy.combined_hash:
            return False, "Strategy has no hash (not locked)"

        # Recompute hashes
        hashes = self.compute_strategy_hashes(strategy)

        if hashes['combined_hash'] != strategy.combined_hash:
            return False, (
                f"Hash mismatch! Stored: {strategy.combined_hash[:16]}..., "
                f"Computed: {hashes['combined_hash'][:16]}... "
                "Strategy may have been tampered with."
            )

        return True, None

    def get_strategy_by_hash(self, combined_hash: str) -> Optional[StrategyCode]:
        """
        Look up a strategy by its combined hash.

        Args:
            combined_hash: The 64-character combined hash

        Returns:
            StrategyCode if found, None otherwise
        """
        if not self.db:
            raise ValueError("Database session required")

        return self.db.query(StrategyCode).filter(
            StrategyCode.combined_hash == combined_hash,
            StrategyCode.locked_at.isnot(None)
        ).first()

    def get_version_history(self, strategy: StrategyCode) -> list:
        """
        Get the full version history for a strategy.

        Args:
            strategy: Any strategy in the version chain

        Returns:
            List of version info dicts, ordered oldest to newest
        """
        versions = []

        # Go to root
        root = strategy
        while root.parent:
            root = root.parent

        # Collect all versions
        def collect_versions(s):
            versions.append({
                'id': s.id,
                'version': s.version,
                'name': s.name,
                'combined_hash': s.combined_hash,
                'locked_at': s.locked_at.isoformat() if s.locked_at else None,
                'created_at': s.created_at.isoformat() if s.created_at else None,
                'is_current': s.id == strategy.id,
                'live_total_trades': s.live_total_trades,
                'live_total_pnl': float(s.live_total_pnl) if s.live_total_pnl else 0
            })
            for child in s.versions:
                collect_versions(child)

        collect_versions(root)

        # Sort by version number
        return sorted(versions, key=lambda v: v['version'])


# Singleton-style function for simple hash computation without DB
def compute_strategy_hash(code: str, symbols: list = None) -> str:
    """
    Convenience function to compute a strategy's combined hash.

    Args:
        code: Strategy code
        symbols: List of symbols

    Returns:
        64-character combined hash
    """
    service = StrategyHashService()
    code_hash = service.compute_code_hash(code)
    config_hash = service.compute_config_hash(symbols)
    return service.compute_combined_hash(code_hash, config_hash)
