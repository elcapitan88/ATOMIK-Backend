"""Phase 1: Trust Foundation - Hashing, User Modes, Performance Tracking

This migration implements the core trust mechanisms for the Atomik platform:
- Phase 1.1: Cryptographic strategy hashing for immutability verification
- Phase 1.2: User mode separation (subscriber/private_creator/public_creator)
- Phase 1.3: Trade version tracking for per-version performance history

Revision ID: 20251217_phase1
Revises: 0318102422e0
Create Date: 2025-12-17
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '20251217_phase1'
down_revision: Union[str, None] = '0318102422e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # =========================================================================
    # Phase 1.1: Strategy Hashing - Add hash columns to strategy_codes
    # =========================================================================

    # Hash fields for cryptographic verification
    op.add_column('strategy_codes', sa.Column('code_hash', sa.String(64), nullable=True))
    op.add_column('strategy_codes', sa.Column('config_hash', sa.String(64), nullable=True))
    op.add_column('strategy_codes', sa.Column('combined_hash', sa.String(64), nullable=True))
    op.add_column('strategy_codes', sa.Column('locked_at', sa.DateTime(), nullable=True))
    op.add_column('strategy_codes', sa.Column('parent_strategy_id', sa.Integer(), nullable=True))

    # Live performance tracking (cached metrics for public verification)
    op.add_column('strategy_codes', sa.Column('live_total_trades', sa.Integer(), server_default='0', nullable=False))
    op.add_column('strategy_codes', sa.Column('live_winning_trades', sa.Integer(), server_default='0', nullable=False))
    op.add_column('strategy_codes', sa.Column('live_total_pnl', sa.Numeric(12, 2), server_default='0', nullable=False))
    op.add_column('strategy_codes', sa.Column('live_win_rate', sa.Numeric(5, 2), server_default='0', nullable=False))
    op.add_column('strategy_codes', sa.Column('live_first_trade_at', sa.DateTime(), nullable=True))
    op.add_column('strategy_codes', sa.Column('live_last_trade_at', sa.DateTime(), nullable=True))

    # Create unique index on combined_hash for fast lookups and uniqueness
    op.create_index('ix_strategy_codes_combined_hash', 'strategy_codes', ['combined_hash'], unique=True)

    # Create index on locked_at for filtering locked/unlocked strategies
    op.create_index('ix_strategy_codes_locked_at', 'strategy_codes', ['locked_at'])

    # Self-referential foreign key for version lineage
    op.create_foreign_key(
        'fk_strategy_codes_parent',
        'strategy_codes', 'strategy_codes',
        ['parent_strategy_id'], ['id'],
        ondelete='SET NULL'
    )

    # =========================================================================
    # Phase 1.2: User Mode Separation
    # =========================================================================

    # Create enum type for user modes
    user_mode_enum = postgresql.ENUM('subscriber', 'private_creator', 'public_creator', name='user_mode_enum')
    user_mode_enum.create(op.get_bind(), checkfirst=True)

    # Add user_mode column with default 'subscriber'
    op.add_column('users', sa.Column(
        'user_mode',
        sa.Enum('subscriber', 'private_creator', 'public_creator', name='user_mode_enum'),
        server_default='subscriber',
        nullable=False
    ))

    # Create index on user_mode for filtering by user type
    op.create_index('ix_users_user_mode', 'users', ['user_mode'])

    # Add split resource counters to subscriptions
    op.add_column('subscriptions', sa.Column('owned_strategies_count', sa.Integer(), server_default='0', nullable=False))
    op.add_column('subscriptions', sa.Column('subscribed_strategies_count', sa.Integer(), server_default='0', nullable=False))

    # =========================================================================
    # Phase 1.3: Trade Version Tracking
    # =========================================================================

    # Add strategy version reference to trades
    op.add_column('trades', sa.Column('strategy_version_id', sa.Integer(), nullable=True))

    # Create enum type for execution environment
    exec_env_enum = postgresql.ENUM('live', 'paper', 'backtest', name='exec_env_enum')
    exec_env_enum.create(op.get_bind(), checkfirst=True)

    # Add execution environment tracking
    op.add_column('trades', sa.Column(
        'execution_environment',
        sa.Enum('live', 'paper', 'backtest', name='exec_env_enum'),
        server_default='live',
        nullable=False
    ))

    # Add live verification flag (set by system only, not user-editable)
    op.add_column('trades', sa.Column('is_verified_live', sa.Boolean(), server_default='false', nullable=False))

    # Create index for filtering trades by strategy version
    op.create_index('ix_trades_strategy_version_id', 'trades', ['strategy_version_id'])

    # Create index for filtering verified live trades
    op.create_index('ix_trades_is_verified_live', 'trades', ['is_verified_live'])

    # Foreign key linking trades to strategy code versions
    op.create_foreign_key(
        'fk_trades_strategy_version',
        'trades', 'strategy_codes',
        ['strategy_version_id'], ['id'],
        ondelete='SET NULL'
    )

    # =========================================================================
    # Data Migration: Set user_mode for existing users
    # =========================================================================

    # Set public_creator for users with verified creator profiles
    op.execute("""
        UPDATE users u
        SET user_mode = 'public_creator'
        FROM creator_profiles cp
        WHERE u.creator_profile_id = cp.id
        AND cp.is_verified = true
    """)

    # Set private_creator for users who have created strategies but aren't public creators
    op.execute("""
        UPDATE users u
        SET user_mode = 'private_creator'
        WHERE u.user_mode = 'subscriber'
        AND EXISTS (SELECT 1 FROM strategy_codes sc WHERE sc.user_id = u.id)
    """)

    # Initialize owned_strategies_count from existing active_strategies_count
    op.execute("""
        UPDATE subscriptions
        SET owned_strategies_count = COALESCE(active_strategies_count, 0)
    """)


def downgrade() -> None:
    # =========================================================================
    # Remove Phase 1.3: Trade Version Tracking
    # =========================================================================
    op.drop_constraint('fk_trades_strategy_version', 'trades', type_='foreignkey')
    op.drop_index('ix_trades_is_verified_live', table_name='trades')
    op.drop_index('ix_trades_strategy_version_id', table_name='trades')
    op.drop_column('trades', 'is_verified_live')
    op.drop_column('trades', 'execution_environment')
    op.drop_column('trades', 'strategy_version_id')

    # Drop execution environment enum
    exec_env_enum = postgresql.ENUM('live', 'paper', 'backtest', name='exec_env_enum')
    exec_env_enum.drop(op.get_bind(), checkfirst=True)

    # =========================================================================
    # Remove Phase 1.2: User Mode Separation
    # =========================================================================
    op.drop_column('subscriptions', 'subscribed_strategies_count')
    op.drop_column('subscriptions', 'owned_strategies_count')
    op.drop_index('ix_users_user_mode', table_name='users')
    op.drop_column('users', 'user_mode')

    # Drop user mode enum
    user_mode_enum = postgresql.ENUM('subscriber', 'private_creator', 'public_creator', name='user_mode_enum')
    user_mode_enum.drop(op.get_bind(), checkfirst=True)

    # =========================================================================
    # Remove Phase 1.1: Strategy Hashing
    # =========================================================================
    op.drop_constraint('fk_strategy_codes_parent', 'strategy_codes', type_='foreignkey')
    op.drop_index('ix_strategy_codes_locked_at', table_name='strategy_codes')
    op.drop_index('ix_strategy_codes_combined_hash', table_name='strategy_codes')
    op.drop_column('strategy_codes', 'live_last_trade_at')
    op.drop_column('strategy_codes', 'live_first_trade_at')
    op.drop_column('strategy_codes', 'live_win_rate')
    op.drop_column('strategy_codes', 'live_total_pnl')
    op.drop_column('strategy_codes', 'live_winning_trades')
    op.drop_column('strategy_codes', 'live_total_trades')
    op.drop_column('strategy_codes', 'parent_strategy_id')
    op.drop_column('strategy_codes', 'locked_at')
    op.drop_column('strategy_codes', 'combined_hash')
    op.drop_column('strategy_codes', 'config_hash')
    op.drop_column('strategy_codes', 'code_hash')
