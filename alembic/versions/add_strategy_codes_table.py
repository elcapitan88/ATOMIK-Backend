"""Add strategy codes table for Strategy Engine

Revision ID: add_strategy_codes
Revises: [latest_revision]
Create Date: 2025-01-27 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from datetime import datetime

# revision identifiers
revision = 'add_strategy_codes'
down_revision = None  # Will need to be updated to latest revision
branch_labels = None
depends_on = None


def upgrade():
    """Add strategy_codes table."""
    # Check if table already exists
    from sqlalchemy import inspect
    from alembic import context
    
    conn = op.get_bind()
    inspector = inspect(conn)
    tables = inspector.get_table_names()
    
    if 'strategy_codes' in tables:
        # Table already exists, skip creation
        return
    
    op.create_table(
        'strategy_codes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('code', sa.Text(), nullable=False),
        sa.Column('symbols', sa.String(length=500), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('is_validated', sa.Boolean(), nullable=True),
        sa.Column('validation_error', sa.Text(), nullable=True),
        sa.Column('version', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('activated_at', sa.DateTime(), nullable=True),
        sa.Column('deactivated_at', sa.DateTime(), nullable=True),
        sa.Column('signals_generated', sa.Integer(), nullable=True),
        sa.Column('last_signal_at', sa.DateTime(), nullable=True),
        sa.Column('error_count', sa.Integer(), nullable=True),
        sa.Column('last_error_at', sa.DateTime(), nullable=True),
        sa.Column('last_error_message', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for performance
    op.create_index(op.f('ix_strategy_codes_id'), 'strategy_codes', ['id'], unique=False)
    op.create_index(op.f('ix_strategy_codes_user_id'), 'strategy_codes', ['user_id'], unique=False)
    op.create_index(op.f('ix_strategy_codes_name'), 'strategy_codes', ['name'], unique=False)
    op.create_index(op.f('ix_strategy_codes_is_active'), 'strategy_codes', ['is_active'], unique=False)


def downgrade():
    """Remove strategy_codes table."""
    op.drop_index(op.f('ix_strategy_codes_is_active'), table_name='strategy_codes')
    op.drop_index(op.f('ix_strategy_codes_name'), table_name='strategy_codes')
    op.drop_index(op.f('ix_strategy_codes_user_id'), table_name='strategy_codes')
    op.drop_index(op.f('ix_strategy_codes_id'), table_name='strategy_codes')
    op.drop_table('strategy_codes')