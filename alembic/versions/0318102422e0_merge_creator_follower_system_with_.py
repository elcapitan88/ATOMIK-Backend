"""Merge creator follower system with engine strategies

Revision ID: 0318102422e0
Revises: 20250923134728, add_engine_strategy_subs, add_strategy_engine_support
Create Date: 2025-09-23 13:48:17.718213

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0318102422e0'
down_revision: Union[str, None] = ('20250923134728', 'add_engine_strategy_subs', 'add_strategy_engine_support')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
