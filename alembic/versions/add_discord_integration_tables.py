"""Add Discord integration tables

Revision ID: discord_integration_001
Revises:
Create Date: 2024-11-30

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = 'discord_integration_001'
down_revision = None
branch_labels = ('discord',)
depends_on = None


def upgrade() -> None:
    # Create discord_links table
    op.create_table(
        'discord_links',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('discord_user_id', sa.String(32), nullable=False),
        sa.Column('discord_username', sa.String(100), nullable=True),
        sa.Column('discord_discriminator', sa.String(10), nullable=True),
        sa.Column('discord_avatar', sa.String(255), nullable=True),
        sa.Column('access_token', sa.Text(), nullable=True),
        sa.Column('refresh_token', sa.Text(), nullable=True),
        sa.Column('token_expires_at', sa.DateTime(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, default=True),
        sa.Column('linked_at', sa.DateTime(), nullable=False),
        sa.Column('last_used_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_discord_links_id', 'discord_links', ['id'])
    op.create_index('ix_discord_links_user_id', 'discord_links', ['user_id'])
    op.create_index('ix_discord_links_discord_user_id', 'discord_links', ['discord_user_id'], unique=True)

    # Create discord_user_threads table
    op.create_table(
        'discord_user_threads',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('discord_user_id', sa.String(32), nullable=False),
        sa.Column('discord_username', sa.String(100), nullable=True),
        sa.Column('thread_id', sa.String(32), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('last_active', sa.DateTime(), nullable=False),
        sa.Column('is_archived', sa.Boolean(), nullable=False, default=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_discord_user_threads_id', 'discord_user_threads', ['id'])
    op.create_index('ix_discord_user_threads_discord_user_id', 'discord_user_threads', ['discord_user_id'], unique=True)
    op.create_index('ix_discord_user_threads_thread_id', 'discord_user_threads', ['thread_id'])

    # Create pending_discord_links table
    op.create_table(
        'pending_discord_links',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('token', sa.String(64), nullable=False),
        sa.Column('discord_user_id', sa.String(32), nullable=False),
        sa.Column('discord_username', sa.String(100), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('is_used', sa.Boolean(), nullable=False, default=False),
        sa.Column('used_by_user_id', sa.Integer(), nullable=True),
        sa.Column('used_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['used_by_user_id'], ['users.id'], ondelete='SET NULL'),
    )
    op.create_index('ix_pending_discord_links_id', 'pending_discord_links', ['id'])
    op.create_index('ix_pending_discord_links_token', 'pending_discord_links', ['token'], unique=True)


def downgrade() -> None:
    op.drop_table('pending_discord_links')
    op.drop_table('discord_user_threads')
    op.drop_table('discord_links')
