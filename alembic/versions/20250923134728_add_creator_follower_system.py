"""Add creator follower system and follower_count

Revision ID: 20250923134728
Revises: stu123vwx456
Create Date: 2025-09-23 13:47:28.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20250923134728'
down_revision = 'stu123vwx456'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create creator_followers table
    op.create_table(
        'creator_followers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('follower_user_id', sa.Integer(), nullable=False),
        sa.Column('creator_user_id', sa.Integer(), nullable=False),
        sa.Column('followed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['creator_user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['follower_user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('follower_user_id', 'creator_user_id', name='_follower_creator_uc')
    )

    # Create indexes for performance
    op.create_index('ix_creator_followers_id', 'creator_followers', ['id'])
    op.create_index('ix_creator_followers_creator_user_id', 'creator_followers', ['creator_user_id'])
    op.create_index('ix_creator_followers_follower_user_id', 'creator_followers', ['follower_user_id'])

    # Add follower_count column to creator_profiles
    op.add_column('creator_profiles', sa.Column('follower_count', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    # Remove follower_count column from creator_profiles
    op.drop_column('creator_profiles', 'follower_count')

    # Drop indexes
    op.drop_index('ix_creator_followers_follower_user_id', table_name='creator_followers')
    op.drop_index('ix_creator_followers_creator_user_id', table_name='creator_followers')
    op.drop_index('ix_creator_followers_id', table_name='creator_followers')

    # Drop creator_followers table
    op.drop_table('creator_followers')