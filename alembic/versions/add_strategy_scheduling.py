"""Add strategy scheduling fields

Revision ID: add_strategy_scheduling
Revises: 0318102422e0
Create Date: 2025-01-08

"""
from alembic import op
import sqlalchemy as sa
from datetime import datetime

# revision identifiers
revision = 'add_strategy_scheduling'
down_revision = '0318102422e0'
branch_labels = None
depends_on = None


def upgrade():
    """Add scheduling fields to activated_strategies table"""
    # Add market_schedule column - which market hours to follow
    op.add_column('activated_strategies',
        sa.Column('market_schedule', sa.String(50), nullable=True))

    # Add schedule_active_state column - tracks if currently scheduled on/off
    op.add_column('activated_strategies',
        sa.Column('schedule_active_state', sa.Boolean(), nullable=True))

    # Add last_scheduled_toggle column - last time scheduler toggled this strategy
    op.add_column('activated_strategies',
        sa.Column('last_scheduled_toggle', sa.DateTime(), nullable=True))


def downgrade():
    """Remove scheduling fields from activated_strategies table"""
    op.drop_column('activated_strategies', 'last_scheduled_toggle')
    op.drop_column('activated_strategies', 'schedule_active_state')
    op.drop_column('activated_strategies', 'market_schedule')
