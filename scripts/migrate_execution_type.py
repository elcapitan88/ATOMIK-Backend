#!/usr/bin/env python3
"""
Standalone script to add/update execution_type column in activated_strategies table.
Can be run independently of Alembic if needed.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
from psycopg2 import sql
from app.core.config import settings
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def check_column_exists(cursor, table_name, column_name):
    """Check if a column exists in a table."""
    cursor.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s
    """, (table_name, column_name))
    return cursor.fetchone() is not None

def add_execution_type_column():
    """Add execution_type column and populate it based on existing data."""

    conn = None
    cursor = None

    try:
        # Connect to database
        logger.info("Connecting to database...")
        # Use DEV_DATABASE_URL for external proxy access
        database_url = "postgresql://postgres:K2Q71c2OIVd1ZIXm8Ad1BFk5jF03Kj33@metro.proxy.rlwy.net:47089/railway"
        logger.info(f"Using database: metro.proxy.rlwy.net:47089")
        conn = psycopg2.connect(database_url)
        cursor = conn.cursor()

        # Check if column exists
        if check_column_exists(cursor, 'activated_strategies', 'execution_type'):
            logger.info("execution_type column already exists")

            # Update any NULL or empty values
            cursor.execute("""
                UPDATE activated_strategies
                SET execution_type = CASE
                    WHEN strategy_code_id IS NOT NULL THEN 'engine'
                    WHEN webhook_id IS NOT NULL THEN 'webhook'
                    ELSE 'webhook'
                END
                WHERE execution_type IS NULL OR execution_type = ''
            """)
            updated = cursor.rowcount
            if updated > 0:
                logger.info(f"Updated {updated} records with missing execution_type")
        else:
            logger.info("Adding execution_type column...")

            # Add column
            cursor.execute("""
                ALTER TABLE activated_strategies
                ADD COLUMN execution_type VARCHAR(20) DEFAULT 'webhook' NOT NULL
            """)
            logger.info("✓ Added execution_type column")

            # Update based on existing data
            cursor.execute("""
                UPDATE activated_strategies
                SET execution_type = CASE
                    WHEN strategy_code_id IS NOT NULL THEN 'engine'
                    ELSE 'webhook'
                END
            """)
            logger.info(f"✓ Updated {cursor.rowcount} records")

            # Add constraint
            cursor.execute("""
                ALTER TABLE activated_strategies
                ADD CONSTRAINT check_execution_type
                CHECK (execution_type IN ('webhook', 'engine'))
            """)
            logger.info("✓ Added check constraint")

            # Add index
            cursor.execute("""
                CREATE INDEX idx_execution_type
                ON activated_strategies(execution_type)
            """)
            logger.info("✓ Added index")

        # Handle special cases
        logger.info("\nUpdating special case strategies...")

        # Purple Reign
        cursor.execute("""
            UPDATE activated_strategies
            SET execution_type = 'engine'
            WHERE webhook_id = 'dsALfSReTUl2yEChwak3jM45sLlpmqGErbYdglmJEqc'
        """)
        purple_count = cursor.rowcount
        logger.info(f"✓ Updated {purple_count} Purple Reign strategies")

        # Break N Enter (webhook ID 117)
        cursor.execute("""
            UPDATE activated_strategies
            SET execution_type = 'engine'
            WHERE webhook_id IN (
                SELECT token FROM webhooks WHERE id = 117
            )
        """)
        break_count = cursor.rowcount
        logger.info(f"✓ Updated {break_count} Break N Enter strategies")

        # Get summary
        cursor.execute("""
            SELECT execution_type, COUNT(*) as count
            FROM activated_strategies
            GROUP BY execution_type
        """)

        logger.info("\nStrategy execution type summary:")
        for row in cursor.fetchall():
            logger.info(f"  {row[0]}: {row[1]} strategies")

        # Commit changes
        conn.commit()
        logger.info("\n✅ Migration completed successfully!")

        # Show some sample data
        cursor.execute("""
            SELECT id, strategy_type, execution_type,
                   webhook_id IS NOT NULL as has_webhook,
                   strategy_code_id IS NOT NULL as has_code,
                   ticker
            FROM activated_strategies
            LIMIT 10
        """)

        logger.info("\nSample strategies after migration:")
        logger.info("ID  | Type     | Execution | Webhook | Code | Ticker")
        logger.info("----|----------|-----------|---------|------|-------")
        for row in cursor.fetchall():
            logger.info(f"{row[0]:<4} | {row[1]:<8} | {row[2]:<9} | {str(row[3]):<7} | {str(row[4]):<4} | {row[5]}")

    except Exception as e:
        logger.error(f"Error during migration: {e}")
        if conn:
            conn.rollback()
        raise
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

def verify_migration():
    """Verify the migration was successful."""

    conn = None
    cursor = None

    try:
        # Use DEV_DATABASE_URL for external access
        database_url = "postgresql://postgres:K2Q71c2OIVd1ZIXm8Ad1BFk5jF03Kj33@metro.proxy.rlwy.net:47089/railway"
        conn = psycopg2.connect(database_url)
        cursor = conn.cursor()

        # Check for any strategies without execution_type
        cursor.execute("""
            SELECT COUNT(*)
            FROM activated_strategies
            WHERE execution_type IS NULL OR execution_type = ''
        """)
        null_count = cursor.fetchone()[0]

        if null_count > 0:
            logger.warning(f"⚠ Found {null_count} strategies without execution_type")
            return False

        # Check for any mismatched execution_type
        cursor.execute("""
            SELECT COUNT(*)
            FROM activated_strategies
            WHERE (strategy_code_id IS NOT NULL AND execution_type != 'engine')
               OR (strategy_code_id IS NULL AND webhook_id IS NOT NULL AND execution_type != 'webhook'
                   AND webhook_id NOT IN (
                       'dsALfSReTUl2yEChwak3jM45sLlpmqGErbYdglmJEqc',
                       (SELECT token FROM webhooks WHERE id = 117)
                   ))
        """)
        mismatch_count = cursor.fetchone()[0]

        if mismatch_count > 0:
            logger.warning(f"⚠ Found {mismatch_count} strategies with mismatched execution_type")

            # Show details
            cursor.execute("""
                SELECT id, execution_type, webhook_id, strategy_code_id
                FROM activated_strategies
                WHERE (strategy_code_id IS NOT NULL AND execution_type != 'engine')
                   OR (strategy_code_id IS NULL AND webhook_id IS NOT NULL AND execution_type != 'webhook'
                       AND webhook_id NOT IN (
                           'dsALfSReTUl2yEChwak3jM45sLlpmqGErbYdglmJEqc',
                           (SELECT token FROM webhooks WHERE id = 117)
                       ))
                LIMIT 5
            """)

            logger.info("Sample mismatched strategies:")
            for row in cursor.fetchall():
                logger.info(f"  ID {row[0]}: execution_type={row[1]}, webhook={row[2]}, code={row[3]}")

            return False

        logger.info("✅ All strategies have valid execution_type values")
        return True

    except Exception as e:
        logger.error(f"Error during verification: {e}")
        return False
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

if __name__ == "__main__":
    logger.info("Starting execution_type migration...")

    try:
        # Run migration
        add_execution_type_column()

        # Verify
        logger.info("\nVerifying migration...")
        if verify_migration():
            logger.info("\n🎉 Migration verified successfully!")
        else:
            logger.warning("\n⚠ Migration completed but verification found issues")
            logger.info("You may need to manually review the affected strategies")

    except Exception as e:
        logger.error(f"\n❌ Migration failed: {e}")
        sys.exit(1)