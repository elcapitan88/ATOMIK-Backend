"""add social media fields to users

Revision ID: nop789qrs012
Revises: mno678pqr901
Create Date: 2025-01-20 14:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'nop789qrs012'
down_revision = 'mno678pqr901'
branch_labels = None
depends_on = None


def upgrade():
    # Add social media fields to users table
    op.add_column('users', sa.Column('x_handle', sa.String(), nullable=True))
    op.add_column('users', sa.Column('tiktok_handle', sa.String(), nullable=True))
    op.add_column('users', sa.Column('instagram_handle', sa.String(), nullable=True))
    op.add_column('users', sa.Column('youtube_handle', sa.String(), nullable=True))
    
    # Note: discord_handle might already exist, so we'll check first
    # If it doesn't exist, add it
    from sqlalchemy import inspect
    from sqlalchemy import create_engine
    from app.core.config import settings
    
    # Create engine to inspect the database
    engine = create_engine(settings.DATABASE_URL)
    inspector = inspect(engine)
    columns = [col['name'] for col in inspector.get_columns('users')]
    
    if 'discord_handle' not in columns:
        op.add_column('users', sa.Column('discord_handle', sa.String(), nullable=True))
    
    # Also add website if it doesn't exist
    if 'website' not in columns:
        op.add_column('users', sa.Column('website', sa.String(), nullable=True))


def downgrade():
    # Remove the social media columns
    op.drop_column('users', 'youtube_handle')
    op.drop_column('users', 'instagram_handle')
    op.drop_column('users', 'tiktok_handle')
    op.drop_column('users', 'x_handle')
    # Note: We don't drop discord_handle or website as they might have existed before