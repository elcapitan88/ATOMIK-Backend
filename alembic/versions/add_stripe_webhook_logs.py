"""add stripe webhook logs table

Revision ID: add_stripe_webhook_logs
Revises:
Create Date: 2025-10-07 01:50:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = 'add_stripe_webhook_logs'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    # Create stripe_webhook_logs table
    op.create_table(
        'stripe_webhook_logs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('stripe_event_id', sa.String(), nullable=False),
        sa.Column('event_type', sa.String(), nullable=False),
        sa.Column('webhook_endpoint', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='pending'),
        sa.Column('retry_count', sa.Integer(), default=0),
        sa.Column('max_retries', sa.Integer(), default=3),
        sa.Column('event_data', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('error_details', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('received_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('customer_id', sa.String(), nullable=True),
        sa.Column('subscription_id', sa.String(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('webhook_id', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes for efficient querying
    op.create_index('ix_stripe_webhook_logs_stripe_event_id', 'stripe_webhook_logs', ['stripe_event_id'], unique=True)
    op.create_index('ix_stripe_webhook_logs_event_type', 'stripe_webhook_logs', ['event_type'])
    op.create_index('ix_stripe_webhook_logs_status', 'stripe_webhook_logs', ['status'])
    op.create_index('ix_stripe_webhook_logs_user_id', 'stripe_webhook_logs', ['user_id'])
    op.create_index('ix_stripe_webhook_logs_webhook_id', 'stripe_webhook_logs', ['webhook_id'])
    op.create_index('ix_stripe_webhook_logs_customer_id', 'stripe_webhook_logs', ['customer_id'])
    op.create_index('ix_stripe_webhook_logs_subscription_id', 'stripe_webhook_logs', ['subscription_id'])
    op.create_index('ix_stripe_webhook_logs_retry', 'stripe_webhook_logs', ['status', 'retry_count', 'next_retry_at'])

def downgrade():
    # Drop indexes
    op.drop_index('ix_stripe_webhook_logs_retry', table_name='stripe_webhook_logs')
    op.drop_index('ix_stripe_webhook_logs_subscription_id', table_name='stripe_webhook_logs')
    op.drop_index('ix_stripe_webhook_logs_customer_id', table_name='stripe_webhook_logs')
    op.drop_index('ix_stripe_webhook_logs_webhook_id', table_name='stripe_webhook_logs')
    op.drop_index('ix_stripe_webhook_logs_user_id', table_name='stripe_webhook_logs')
    op.drop_index('ix_stripe_webhook_logs_status', table_name='stripe_webhook_logs')
    op.drop_index('ix_stripe_webhook_logs_event_type', table_name='stripe_webhook_logs')
    op.drop_index('ix_stripe_webhook_logs_stripe_event_id', table_name='stripe_webhook_logs')

    # Drop table
    op.drop_table('stripe_webhook_logs')