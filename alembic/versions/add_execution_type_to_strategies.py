"""Add execution_type column to activated_strategies table

Revision ID: add_execution_type_001
Revises:
Create Date: 2024-01-04 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text

# revision identifiers, used by Alembic.
revision = 'add_execution_type_001'
down_revision = None  # Update this with your latest migration
branch_labels = None
depends_on = None


def upgrade():
    """
    Add execution_type column to activated_strategies table if it doesn't exist,
    and populate it based on existing data.
    """

    # Check if column already exists
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('activated_strategies')]

    if 'execution_type' not in columns:
        # Add execution_type column with default value
        op.add_column('activated_strategies',
            sa.Column('execution_type', sa.String(20), nullable=False, server_default='webhook')
        )

        # Update existing records based on strategy_code_id presence
        # If strategy_code_id is not null, it's an engine strategy
        conn.execute(text("""
            UPDATE activated_strategies
            SET execution_type = CASE
                WHEN strategy_code_id IS NOT NULL THEN 'engine'
                ELSE 'webhook'
            END
        """))

        # Add constraint to ensure valid values
        op.create_check_constraint(
            'check_execution_type',
            'activated_strategies',
            "execution_type IN ('webhook', 'engine')"
        )

        # Add index for performance
        op.create_index('idx_execution_type', 'activated_strategies', ['execution_type'])

        print("✓ Added execution_type column to activated_strategies table")
    else:
        print("ℹ execution_type column already exists, updating values...")

        # Even if column exists, ensure all records have correct values
        conn.execute(text("""
            UPDATE activated_strategies
            SET execution_type = CASE
                WHEN strategy_code_id IS NOT NULL THEN 'engine'
                WHEN webhook_id IS NOT NULL THEN 'webhook'
                ELSE 'webhook'
            END
            WHERE execution_type IS NULL OR execution_type = ''
        """))

        print("✓ Updated execution_type values for existing records")

    # Handle special cases - Purple Reign and Break N Enter
    print("Updating special case strategies...")

    # Update Purple Reign strategies (webhook token: dsALfSReTUl2yEChwak3jM45sLlpmqGErbYdglmJEqc)
    result = conn.execute(text("""
        UPDATE activated_strategies
        SET execution_type = 'engine'
        WHERE webhook_id = 'dsALfSReTUl2yEChwak3jM45sLlpmqGErbYdglmJEqc'
        RETURNING id
    """))
    purple_reign_count = result.rowcount
    print(f"✓ Updated {purple_reign_count} Purple Reign strategies to engine execution")

    # Update Break N Enter strategies (webhook ID 117)
    result = conn.execute(text("""
        UPDATE activated_strategies
        SET execution_type = 'engine'
        WHERE webhook_id IN (
            SELECT token FROM webhooks WHERE id = 117
        )
        RETURNING id
    """))
    break_enter_count = result.rowcount
    print(f"✓ Updated {break_enter_count} Break N Enter strategies to engine execution")

    # Log summary
    result = conn.execute(text("""
        SELECT execution_type, COUNT(*) as count
        FROM activated_strategies
        GROUP BY execution_type
    """))

    print("\nStrategy execution type summary:")
    for row in result:
        print(f"  {row.execution_type}: {row.count} strategies")

    print("\n✅ Migration completed successfully")


def downgrade():
    """
    Remove execution_type column and related constraints/indexes.
    Note: This will lose the execution_type information!
    """

    # Check if column exists before trying to drop it
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('activated_strategies')]

    if 'execution_type' in columns:
        # Drop index
        op.drop_index('idx_execution_type', 'activated_strategies')

        # Drop constraint
        op.drop_constraint('check_execution_type', 'activated_strategies', type_='check')

        # Drop column
        op.drop_column('activated_strategies', 'execution_type')

        print("✓ Removed execution_type column from activated_strategies table")
    else:
        print("ℹ execution_type column doesn't exist, nothing to remove")