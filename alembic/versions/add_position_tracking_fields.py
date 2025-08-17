"""Add position tracking fields for partial exits

Revision ID: add_position_tracking_456def
Revises: adecf4b21951
Create Date: 2025-01-17 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_position_tracking_456def'
down_revision = 'adecf4b21951'
branch_labels = None
depends_on = None


def upgrade():
    # Add position tracking columns to activated_strategies table
    op.add_column('activated_strategies', 
                  sa.Column('last_known_position', sa.Integer(), nullable=True, default=0))
    op.add_column('activated_strategies', 
                  sa.Column('last_exit_type', sa.String(50), nullable=True))
    op.add_column('activated_strategies', 
                  sa.Column('partial_exits_count', sa.Integer(), nullable=True, default=0))
    op.add_column('activated_strategies', 
                  sa.Column('last_position_update', sa.DateTime(), nullable=True))


def downgrade():
    # Remove position tracking columns
    op.drop_column('activated_strategies', 'last_position_update')
    op.drop_column('activated_strategies', 'partial_exits_count')
    op.drop_column('activated_strategies', 'last_exit_type')
    op.drop_column('activated_strategies', 'last_known_position')