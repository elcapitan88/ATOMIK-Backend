"""Add engine strategy support to subscriptions table

Revision ID: add_engine_strategy_subs
Revises: 
Create Date: 2024-01-09

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text

# revision identifiers
revision = 'add_engine_strategy_subs'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    """
    Safely extend webhook_subscriptions to support engine strategies.
    This migration is 100% backward compatible.
    """
    
    # Add new columns to support both webhook and engine strategies
    op.add_column('webhook_subscriptions', 
        sa.Column('strategy_type', sa.String(20), server_default='webhook', nullable=False)
    )
    
    op.add_column('webhook_subscriptions',
        sa.Column('strategy_id', sa.String(50), nullable=True)
    )
    
    op.add_column('webhook_subscriptions',
        sa.Column('strategy_code_id', sa.Integer(), nullable=True)
    )
    
    # Add foreign key for engine strategies
    op.create_foreign_key(
        'fk_webhook_subscriptions_strategy_code',
        'webhook_subscriptions', 
        'strategy_codes',
        ['strategy_code_id'], 
        ['id'],
        ondelete='CASCADE'
    )
    
    # Populate strategy_id for existing webhook subscriptions
    op.execute(text("""
        UPDATE webhook_subscriptions 
        SET strategy_id = webhook_id::VARCHAR 
        WHERE webhook_id IS NOT NULL
    """))
    
    # Create index for faster lookups
    op.create_index('idx_strategy_subscriptions_lookup', 
                    'webhook_subscriptions', 
                    ['user_id', 'strategy_type', 'strategy_id'])
    
    # Rename table to reflect new purpose (optional - can do later)
    # op.rename_table('webhook_subscriptions', 'strategy_subscriptions')
    
    print("✅ Successfully extended webhook_subscriptions table to support engine strategies")
    print("✅ All existing webhook subscriptions preserved")
    print("✅ Table ready for engine strategy subscriptions")


def downgrade():
    """
    Revert changes if needed - removes only new columns, preserves all data
    """
    # Remove index
    op.drop_index('idx_strategy_subscriptions_lookup', 'webhook_subscriptions')
    
    # Remove foreign key
    op.drop_constraint('fk_webhook_subscriptions_strategy_code', 'webhook_subscriptions', type_='foreignkey')
    
    # Remove new columns
    op.drop_column('webhook_subscriptions', 'strategy_code_id')
    op.drop_column('webhook_subscriptions', 'strategy_id')
    op.drop_column('webhook_subscriptions', 'strategy_type')
    
    print("✅ Reverted to original webhook_subscriptions structure")