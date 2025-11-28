"""Add ARIA conversations table and conversation_id to interactions

Revision ID: add_aria_conversations
Revises: update_market_schedule_json
Create Date: 2025-11-27

"""
from alembic import op
import sqlalchemy as sa
from datetime import datetime, timedelta

# revision identifiers, used by Alembic.
revision = 'add_aria_conversations'
down_revision = 'update_market_schedule_json'
branch_labels = None
depends_on = None


def upgrade():
    # Create aria_conversations table
    op.create_table('aria_conversations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('title', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True, default=datetime.utcnow),
        sa.Column('updated_at', sa.DateTime(), nullable=True, default=datetime.utcnow, onupdate=datetime.utcnow),
        sa.Column('is_archived', sa.Boolean(), nullable=True, default=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_aria_conversations_id'), 'aria_conversations', ['id'], unique=False)
    op.create_index(op.f('ix_aria_conversations_user_id'), 'aria_conversations', ['user_id'], unique=False)
    op.create_index(op.f('ix_aria_conversations_created_at'), 'aria_conversations', ['created_at'], unique=False)
    op.create_index(op.f('ix_aria_conversations_is_archived'), 'aria_conversations', ['is_archived'], unique=False)

    # Add conversation_id column to aria_interactions table
    op.add_column('aria_interactions',
        sa.Column('conversation_id', sa.Integer(), nullable=True)
    )
    op.create_foreign_key(
        'fk_aria_interactions_conversation_id',
        'aria_interactions',
        'aria_conversations',
        ['conversation_id'],
        ['id']
    )
    op.create_index(
        op.f('ix_aria_interactions_conversation_id'),
        'aria_interactions',
        ['conversation_id'],
        unique=False
    )


def downgrade():
    # Remove conversation_id from aria_interactions
    op.drop_index(op.f('ix_aria_interactions_conversation_id'), table_name='aria_interactions')
    op.drop_constraint('fk_aria_interactions_conversation_id', 'aria_interactions', type_='foreignkey')
    op.drop_column('aria_interactions', 'conversation_id')

    # Drop aria_conversations table
    op.drop_index(op.f('ix_aria_conversations_is_archived'), table_name='aria_conversations')
    op.drop_index(op.f('ix_aria_conversations_created_at'), table_name='aria_conversations')
    op.drop_index(op.f('ix_aria_conversations_user_id'), table_name='aria_conversations')
    op.drop_index(op.f('ix_aria_conversations_id'), table_name='aria_conversations')
    op.drop_table('aria_conversations')
