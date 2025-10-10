"""
Run SQL migration to convert market_schedule to JSON array
"""
import psycopg2

DATABASE_URL = "postgresql://postgres:K2Q71c2OIVd1ZIXm8Ad1BFk5jF03Kj33@metro.proxy.rlwy.net:47089/railway"

def run_migration():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()

        # Convert market_schedule from VARCHAR to JSON array
        sql = """
        ALTER TABLE activated_strategies
        ALTER COLUMN market_schedule TYPE JSON
        USING CASE
            WHEN market_schedule IS NULL THEN NULL
            WHEN market_schedule = '24/7' THEN '["24/7"]'::json
            ELSE json_build_array(market_schedule)
        END;
        """

        cursor.execute(sql)
        conn.commit()

        print("Migration completed successfully!")
        print("market_schedule column converted to JSON array")

        cursor.close()
        conn.close()

    except Exception as e:
        print(f"Error running migration: {e}")

if __name__ == "__main__":
    run_migration()
