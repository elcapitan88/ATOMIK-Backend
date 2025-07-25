"""Add strategy monetization tables and columns

Revision ID: strategy_monetization_v1
Revises: [previous_revision]
Create Date: 2025-07-25 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'strategy_monetization_v1'
down_revision = 'mno678pqr901'  # Current revision in database
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Phase 1 Migration: Add strategy monetization support while maintaining
    100% backward compatibility with existing webhooks system.
    """
    
    # 1. Add new columns to existing webhooks table (safe additions)
    op.add_column('webhooks', sa.Column('usage_intent', sa.String(20), nullable=False, server_default='personal'))
    op.add_column('webhooks', sa.Column('stripe_product_id', sa.String(100), nullable=True))
    
    # 2. Create strategy_monetization table
    op.create_table(
        'strategy_monetization',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('webhook_id', sa.Integer(), sa.ForeignKey('webhooks.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('stripe_product_id', sa.String(100), nullable=False),
        sa.Column('creator_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('total_subscribers', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('estimated_monthly_revenue', sa.Numeric(10, 2), nullable=False, server_default='0.00'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()'))
    )
    
    # 3. Create strategy_prices table for multiple pricing options
    op.create_table(
        'strategy_prices',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('strategy_monetization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('strategy_monetization.id', ondelete='CASCADE'), nullable=False),
        sa.Column('price_type', sa.String(20), nullable=False),  # 'monthly'|'yearly'|'lifetime'|'setup'
        sa.Column('stripe_price_id', sa.String(100), nullable=False),
        sa.Column('amount', sa.Numeric(10, 2), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False, server_default='usd'),
        sa.Column('billing_interval', sa.String(20), nullable=True),  # 'month'|'year'|NULL for one-time
        sa.Column('trial_period_days', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('subscriber_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_revenue', sa.Numeric(12, 2), nullable=False, server_default='0.00'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()'))
    )
    
    # 4. Create indexes for performance optimization
    op.create_index('idx_webhooks_usage_intent', 'webhooks', ['usage_intent'])
    op.create_index('idx_webhooks_stripe_product_id', 'webhooks', ['stripe_product_id'])
    op.create_index('idx_strategy_monetization_webhook_id', 'strategy_monetization', ['webhook_id'])
    op.create_index('idx_strategy_monetization_creator_user_id', 'strategy_monetization', ['creator_user_id'])
    op.create_index('idx_strategy_monetization_is_active', 'strategy_monetization', ['is_active'])
    op.create_index('idx_strategy_prices_strategy_monetization_id', 'strategy_prices', ['strategy_monetization_id'])
    op.create_index('idx_strategy_prices_price_type', 'strategy_prices', ['price_type'])
    op.create_index('idx_strategy_prices_stripe_price_id', 'strategy_prices', ['stripe_price_id'])
    op.create_index('idx_strategy_prices_is_active', 'strategy_prices', ['is_active'])
    
    # 5. Add check constraints for data validation
    op.create_check_constraint(
        'ck_usage_intent_values',
        'webhooks',
        "usage_intent IN ('personal', 'share_free', 'monetize')"
    )
    
    op.create_check_constraint(
        'ck_price_type_values',
        'strategy_prices',
        "price_type IN ('monthly', 'yearly', 'lifetime', 'setup')"
    )
    
    op.create_check_constraint(
        'ck_currency_values',
        'strategy_prices',
        "currency IN ('usd', 'eur', 'gbp')"
    )
    
    op.create_check_constraint(
        'ck_billing_interval_values',
        'strategy_prices',
        "billing_interval IS NULL OR billing_interval IN ('month', 'year')"
    )
    
    op.create_check_constraint(
        'ck_amount_positive',
        'strategy_prices',
        "amount > 0"
    )
    
    op.create_check_constraint(
        'ck_trial_period_non_negative',
        'strategy_prices',
        "trial_period_days >= 0"
    )
    
    # 6. Add trigger for updating updated_at timestamps
    op.execute("""
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ language 'plpgsql';
    """)
    
    op.execute("""
        CREATE TRIGGER update_strategy_monetization_updated_at
        BEFORE UPDATE ON strategy_monetization
        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    """)
    
    op.execute("""
        CREATE TRIGGER update_strategy_prices_updated_at
        BEFORE UPDATE ON strategy_prices
        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    """)


def downgrade() -> None:
    """
    Rollback migration - removes new tables and columns.
    IMPORTANT: This will lose all monetization data!
    """
    
    # Drop triggers
    op.execute("DROP TRIGGER IF EXISTS update_strategy_prices_updated_at ON strategy_prices;")
    op.execute("DROP TRIGGER IF EXISTS update_strategy_monetization_updated_at ON strategy_monetization;")
    op.execute("DROP FUNCTION IF EXISTS update_updated_at_column();")
    
    # Drop indexes
    op.drop_index('idx_strategy_prices_is_active')
    op.drop_index('idx_strategy_prices_stripe_price_id')
    op.drop_index('idx_strategy_prices_price_type')
    op.drop_index('idx_strategy_prices_strategy_monetization_id')
    op.drop_index('idx_strategy_monetization_is_active')
    op.drop_index('idx_strategy_monetization_creator_user_id')
    op.drop_index('idx_strategy_monetization_webhook_id')
    op.drop_index('idx_webhooks_stripe_product_id')
    op.drop_index('idx_webhooks_usage_intent')
    
    # Drop tables (cascades will handle foreign keys)
    op.drop_table('strategy_prices')
    op.drop_table('strategy_monetization')
    
    # Remove columns from webhooks table
    op.drop_column('webhooks', 'stripe_product_id')
    op.drop_column('webhooks', 'usage_intent')