"""Add strategy metrics tables for Phase 4

Revision ID: add_strategy_metrics_tables
Revises: add_position_tracking_456def
Create Date: 2025-01-26

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'add_strategy_metrics_tables'
down_revision = 'add_position_tracking_456def'
branch_labels = None
depends_on = None


def upgrade():
    # Create strategy_metrics table
    op.create_table('strategy_metrics',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('strategy_id', sa.Integer(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('views', sa.Integer(), server_default='0'),
        sa.Column('unique_viewers', sa.Integer(), server_default='0'),
        sa.Column('trial_starts', sa.Integer(), server_default='0'),
        sa.Column('avg_view_duration', sa.Float(), server_default='0.0'),
        sa.Column('shares', sa.Integer(), server_default='0'),
        sa.Column('monetization_page_views', sa.Integer(), server_default='0'),
        sa.Column('checkout_starts', sa.Integer(), server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['strategy_id'], ['webhooks.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('strategy_id', 'date', name='uq_strategy_metrics_date')
    )
    op.create_index('idx_strategy_metrics_date', 'strategy_metrics', ['strategy_id', 'date'], unique=False)

    # Create creator_dashboard_cache table
    op.create_table('creator_dashboard_cache',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('creator_id', sa.Integer(), nullable=False),
        sa.Column('cache_key', sa.String(), nullable=False),
        sa.Column('cache_value', sa.JSON(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['creator_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('creator_id', 'cache_key', name='uq_creator_cache_key')
    )
    op.create_index('idx_creator_cache_expires', 'creator_dashboard_cache', ['creator_id', 'expires_at'], unique=False)


def downgrade():
    # Drop indexes first
    op.drop_index('idx_creator_cache_expires', table_name='creator_dashboard_cache')
    op.drop_index('idx_strategy_metrics_date', table_name='strategy_metrics')
    
    # Drop tables
    op.drop_table('creator_dashboard_cache')
    op.drop_table('strategy_metrics')