"""Add Strategy Engine support to activated_strategies

Revision ID: add_strategy_engine_support
Revises: 
Create Date: 2025-08-28 20:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_strategy_engine_support'
down_revision = '847628fe0ade'
branch_labels = None
depends_on = None


def upgrade():
    # Add strategy_code_id to activated_strategies for Strategy Engine linking
    op.add_column('activated_strategies', sa.Column('strategy_code_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_activated_strategies_strategy_code_id', 'activated_strategies', 'strategy_codes', ['strategy_code_id'], ['id'])
    
    # Add index for performance
    op.create_index('ix_activated_strategies_strategy_code_id', 'activated_strategies', ['strategy_code_id'])
    
    # Add execution_type to distinguish between webhook and engine strategies
    op.add_column('activated_strategies', sa.Column('execution_type', sa.String(20), nullable=False, server_default='webhook'))
    op.create_index('ix_activated_strategies_execution_type', 'activated_strategies', ['execution_type'])
    
    # Add strategy engine specific settings
    op.add_column('activated_strategies', sa.Column('engine_settings', sa.Text(), nullable=True))  # JSON settings for engine strategies
    

def downgrade():
    # Remove added columns and indexes
    op.drop_index('ix_activated_strategies_execution_type', table_name='activated_strategies')
    op.drop_column('activated_strategies', 'execution_type')
    
    op.drop_column('activated_strategies', 'engine_settings')
    
    op.drop_index('ix_activated_strategies_strategy_code_id', table_name='activated_strategies')
    op.drop_constraint('fk_activated_strategies_strategy_code_id', 'activated_strategies', type_='foreignkey')
    op.drop_column('activated_strategies', 'strategy_code_id')