"""Update market_schedule to JSON array

Revision ID: update_market_schedule_json
Revises: add_strategy_scheduling
Create Date: 2025-10-08

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON

# revision identifiers, used by Alembic.
revision = 'update_market_schedule_json'
down_revision = 'add_strategy_scheduling'
branch_labels = None
depends_on = None


def upgrade():
    # Change market_schedule from VARCHAR to JSON to support multiple markets
    op.alter_column('activated_strategies', 'market_schedule',
                   type_=JSON,
                   existing_type=sa.String(50),
                   postgresql_using='CASE WHEN market_schedule IS NULL THEN NULL ELSE json_build_array(market_schedule) END')


def downgrade():
    # Revert back to VARCHAR, taking first element if array
    op.alter_column('activated_strategies', 'market_schedule',
                   type_=sa.String(50),
                   existing_type=JSON,
                   postgresql_using='market_schedule->>0')
