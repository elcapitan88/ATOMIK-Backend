"""Merge strategy monetization branch

Revision ID: merge_strategy_monetization
Revises: strategy_monetization_v1, stu123vwx456
Create Date: 2025-01-25 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'merge_strategy_monetization'
down_revision = ('strategy_monetization_v1', 'stu123vwx456')
branch_labels = None
depends_on = None

def upgrade():
    # This is a merge migration, no schema changes needed
    pass

def downgrade():
    # This is a merge migration, no schema changes needed
    pass