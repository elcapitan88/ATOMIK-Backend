"""merge_all_strategy_engine_branches

Revision ID: 847628fe0ade
Revises: abc789def012, merge_strategy_monetization, g6f7e8d9c0a1, add_digital_ocean_columns, add_strategy_codes, add_strategy_metrics_tables
Create Date: 2025-08-27 13:31:25.377437

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '847628fe0ade'
down_revision: Union[str, None] = ('abc789def012', 'merge_strategy_monetization', 'g6f7e8d9c0a1', 'add_digital_ocean_columns', 'add_strategy_codes', 'add_strategy_metrics_tables')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
