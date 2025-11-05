"""
Direct SQL migration runner
"""
import psycopg2
from psycopg2 import sql

# Database connection string
DATABASE_URL = "postgresql://postgres:K2Q71c2OIVd1ZIXm8Ad1BFk5jF03Kj33@metro.proxy.rlwy.net:47089/railway"

# SQL migration script
MIGRATION_SQL = """
-- Add market_schedule column
ALTER TABLE activated_strategies
ADD COLUMN IF NOT EXISTS market_schedule VARCHAR(50);

-- Add schedule_active_state column
ALTER TABLE activated_strategies
ADD COLUMN IF NOT EXISTS schedule_active_state BOOLEAN;

-- Add last_scheduled_toggle column
ALTER TABLE activated_strategies
ADD COLUMN IF NOT EXISTS last_scheduled_toggle TIMESTAMP;

-- Insert into alembic_version to track this migration
INSERT INTO alembic_version (version_num)
VALUES ('add_strategy_scheduling')
ON CONFLICT (version_num) DO NOTHING;
"""

def run_migration():
    try:
        print("Connecting to database...")
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()

        print("Running migration...")
        cursor.execute(MIGRATION_SQL)

        print("Verifying columns...")
        cursor.execute("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'activated_strategies'
              AND column_name IN ('market_schedule', 'schedule_active_state', 'last_scheduled_toggle')
            ORDER BY column_name;
        """)

        results = cursor.fetchall()
        print("\n[SUCCESS] Migration completed successfully!")
        print("\nColumns added:")
        for row in results:
            print(f"  - {row[0]}: {row[1]} (nullable: {row[2]})")

        conn.commit()
        cursor.close()
        conn.close()

        print("\n[COMPLETE] Strategy scheduler database migration complete!")

    except Exception as e:
        print(f"\n[ERROR] Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    return True

if __name__ == "__main__":
    run_migration()
