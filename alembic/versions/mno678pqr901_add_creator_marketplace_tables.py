"""add creator marketplace tables

Revision ID: mno678pqr901
Revises: jkl345mno678
Create Date: 2025-01-20 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'mno678pqr901'
down_revision = 'jkl345mno678'
branch_labels = None
depends_on = None


def upgrade():
    # Create creator_profiles table
    op.create_table('creator_profiles',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('display_name', sa.String(100), nullable=True),
        sa.Column('bio', sa.Text(), nullable=True),
        sa.Column('trading_experience', sa.String(50), nullable=True),
        sa.Column('total_subscribers', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('current_tier', sa.String(20), nullable=False, server_default='bronze'),
        sa.Column('platform_fee_override', sa.Numeric(precision=3, scale=2), nullable=True),
        sa.Column('stripe_connect_account_id', sa.String(100), nullable=True),
        sa.Column('is_verified', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('two_fa_enabled', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_creator_profiles_user_id'), 'creator_profiles', ['user_id'], unique=True)
    op.create_index(op.f('ix_creator_profiles_stripe_connect_account_id'), 'creator_profiles', ['stripe_connect_account_id'], unique=True)
    op.create_index(op.f('ix_creator_profiles_current_tier'), 'creator_profiles', ['current_tier'])

    # Create strategy_pricing table
    op.create_table('strategy_pricing',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('webhook_id', sa.Integer(), nullable=False),
        sa.Column('pricing_type', sa.String(50), nullable=False),  # free, one_time, subscription, initiation_plus_sub
        sa.Column('billing_interval', sa.String(20), nullable=True),  # monthly, yearly - only for subscription types
        sa.Column('base_amount', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('yearly_amount', sa.Numeric(precision=10, scale=2), nullable=True),  # Yearly price (optional discount)
        sa.Column('setup_fee', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('trial_days', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_trial_enabled', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('stripe_price_id', sa.String(100), nullable=True),  # For subscription pricing
        sa.Column('stripe_yearly_price_id', sa.String(100), nullable=True),  # For yearly subscription pricing
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['webhook_id'], ['webhooks.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_strategy_pricing_webhook_id'), 'strategy_pricing', ['webhook_id'], unique=True)
    op.create_index(op.f('ix_strategy_pricing_pricing_type'), 'strategy_pricing', ['pricing_type'])
    op.create_index(op.f('ix_strategy_pricing_is_active'), 'strategy_pricing', ['is_active'])

    # Create strategy_purchases table
    op.create_table('strategy_purchases',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('webhook_id', sa.Integer(), nullable=False),
        sa.Column('pricing_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('stripe_payment_intent_id', sa.String(100), nullable=True),
        sa.Column('stripe_subscription_id', sa.String(100), nullable=True),
        sa.Column('amount_paid', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('platform_fee', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('creator_payout', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('purchase_type', sa.String(50), nullable=False),  # one_time, subscription
        sa.Column('status', sa.String(50), nullable=False, server_default='pending'),  # pending, completed, cancelled, refunded
        sa.Column('trial_ends_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('refunded_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('refund_amount', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('refund_reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['webhook_id'], ['webhooks.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['pricing_id'], ['strategy_pricing.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_strategy_purchases_user_id'), 'strategy_purchases', ['user_id'])
    op.create_index(op.f('ix_strategy_purchases_webhook_id'), 'strategy_purchases', ['webhook_id'])
    op.create_index(op.f('ix_strategy_purchases_status'), 'strategy_purchases', ['status'])
    op.create_index(op.f('ix_strategy_purchases_stripe_subscription_id'), 'strategy_purchases', ['stripe_subscription_id'])
    op.create_index(op.f('ix_strategy_purchases_trial_ends_at'), 'strategy_purchases', ['trial_ends_at'])
    
    # Create unique constraint to prevent duplicate active purchases
    op.create_unique_constraint(
        'uq_strategy_purchases_user_webhook_active',
        'strategy_purchases',
        ['user_id', 'webhook_id'],
        postgresql_where=sa.text("status IN ('pending', 'completed')")
    )

    # Create creator_earnings table
    op.create_table('creator_earnings',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('creator_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('purchase_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('gross_amount', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('platform_fee', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('net_amount', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('payout_status', sa.String(50), nullable=False, server_default='pending'),  # pending, processing, paid
        sa.Column('payout_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('stripe_transfer_id', sa.String(100), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['creator_id'], ['creator_profiles.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['purchase_id'], ['strategy_purchases.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_creator_earnings_creator_id'), 'creator_earnings', ['creator_id'])
    op.create_index(op.f('ix_creator_earnings_payout_status'), 'creator_earnings', ['payout_status'])
    op.create_index(op.f('ix_creator_earnings_payout_date'), 'creator_earnings', ['payout_date'])

    # Add creator_profile_id to users table
    op.add_column('users', sa.Column('creator_profile_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key('fk_users_creator_profile', 'users', 'creator_profiles', ['creator_profile_id'], ['id'], ondelete='SET NULL')

    # Add is_monetized flag to webhooks table
    op.add_column('webhooks', sa.Column('is_monetized', sa.Boolean(), nullable=False, server_default='false'))
    op.create_index(op.f('ix_webhooks_is_monetized'), 'webhooks', ['is_monetized'])


def downgrade():
    # Remove columns from existing tables
    op.drop_index(op.f('ix_webhooks_is_monetized'), table_name='webhooks')
    op.drop_column('webhooks', 'is_monetized')
    
    op.drop_constraint('fk_users_creator_profile', 'users', type_='foreignkey')
    op.drop_column('users', 'creator_profile_id')
    
    # Drop tables in reverse order due to foreign key dependencies
    op.drop_index(op.f('ix_creator_earnings_payout_date'), table_name='creator_earnings')
    op.drop_index(op.f('ix_creator_earnings_payout_status'), table_name='creator_earnings')
    op.drop_index(op.f('ix_creator_earnings_creator_id'), table_name='creator_earnings')
    op.drop_table('creator_earnings')
    
    op.drop_constraint('uq_strategy_purchases_user_webhook_active', 'strategy_purchases', type_='unique')
    op.drop_index(op.f('ix_strategy_purchases_trial_ends_at'), table_name='strategy_purchases')
    op.drop_index(op.f('ix_strategy_purchases_stripe_subscription_id'), table_name='strategy_purchases')
    op.drop_index(op.f('ix_strategy_purchases_status'), table_name='strategy_purchases')
    op.drop_index(op.f('ix_strategy_purchases_webhook_id'), table_name='strategy_purchases')
    op.drop_index(op.f('ix_strategy_purchases_user_id'), table_name='strategy_purchases')
    op.drop_table('strategy_purchases')
    
    op.drop_index(op.f('ix_strategy_pricing_is_active'), table_name='strategy_pricing')
    op.drop_index(op.f('ix_strategy_pricing_pricing_type'), table_name='strategy_pricing')
    op.drop_index(op.f('ix_strategy_pricing_webhook_id'), table_name='strategy_pricing')
    op.drop_table('strategy_pricing')
    
    op.drop_index(op.f('ix_creator_profiles_current_tier'), table_name='creator_profiles')
    op.drop_index(op.f('ix_creator_profiles_stripe_connect_account_id'), table_name='creator_profiles')
    op.drop_index(op.f('ix_creator_profiles_user_id'), table_name='creator_profiles')
    op.drop_table('creator_profiles')