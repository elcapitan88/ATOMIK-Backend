"""
Simple test to check scheduled strategies in database
"""
import psycopg2
from datetime import datetime
import json

# Database connection
# Update with your actual database credentials
DB_CONFIG = {
    'host': 'localhost',
    'database': 'atomik',
    'user': 'postgres',
    'password': 'K2Q71c2OIVd1ZIXm8Ad1BFk5jF03'  # Update this
}

def test_database_directly():
    """Test database directly with SQL"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()

        print("=" * 60)
        print("DATABASE TEST - Direct SQL")
        print("=" * 60)

        # Check if columns exist
        print("\n1. Checking if schedule columns exist:")
        cur.execute("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'activated_strategies'
            AND column_name IN ('market_schedule', 'schedule_active_state', 'last_scheduled_toggle')
            ORDER BY column_name;
        """)
        columns = cur.fetchall()

        if columns:
            print("✅ Schedule columns found:")
            for col in columns:
                print(f"   - {col[0]}: {col[1]}")
        else:
            print("❌ Schedule columns NOT found! Running migration...")
            # Try to add columns if they don't exist
            try:
                cur.execute("""
                    ALTER TABLE activated_strategies
                    ADD COLUMN IF NOT EXISTS market_schedule JSON;
                """)
                cur.execute("""
                    ALTER TABLE activated_strategies
                    ADD COLUMN IF NOT EXISTS schedule_active_state BOOLEAN;
                """)
                cur.execute("""
                    ALTER TABLE activated_strategies
                    ADD COLUMN IF NOT EXISTS last_scheduled_toggle TIMESTAMP;
                """)
                conn.commit()
                print("✅ Schedule columns added successfully!")
            except Exception as e:
                print(f"❌ Failed to add columns: {e}")
                conn.rollback()

        # Check for scheduled strategies
        print("\n2. Checking for scheduled strategies:")
        cur.execute("""
            SELECT
                id,
                ticker,
                is_active,
                market_schedule,
                schedule_active_state,
                last_scheduled_toggle
            FROM activated_strategies
            WHERE market_schedule IS NOT NULL
            LIMIT 10;
        """)
        strategies = cur.fetchall()

        if strategies:
            print(f"✅ Found {len(strategies)} scheduled strategies:")
            for s in strategies:
                print(f"\n   Strategy ID: {s[0]}")
                print(f"   - Ticker: {s[1]}")
                print(f"   - Active: {s[2]}")
                print(f"   - Markets: {s[3]}")
                print(f"   - Schedule State: {s[4]}")
                print(f"   - Last Toggle: {s[5]}")
        else:
            print("⚠️ No scheduled strategies found")
            print("\nCreating a test scheduled strategy...")

            # Get a user ID
            cur.execute("SELECT id FROM users LIMIT 1;")
            user = cur.fetchone()

            if user:
                user_id = user[0]
                # Create test strategy with schedule
                cur.execute("""
                    INSERT INTO activated_strategies
                    (user_id, strategy_type, ticker, webhook_id, account_id, quantity, is_active, market_schedule)
                    VALUES
                    (%s, 'single', 'TEST_SCHED', 'test-webhook-sched', 'TEST_ACC', 1, true, %s)
                    RETURNING id;
                """, (user_id, json.dumps(['NYSE', 'LONDON'])))

                strategy_id = cur.fetchone()[0]
                conn.commit()
                print(f"✅ Created test scheduled strategy with ID: {strategy_id}")
                print("   Markets: NYSE, LONDON")

        # Check all strategies count
        print("\n3. Strategy statistics:")
        cur.execute("SELECT COUNT(*) FROM activated_strategies;")
        total = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM activated_strategies WHERE market_schedule IS NOT NULL;")
        scheduled = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM activated_strategies WHERE is_active = true;")
        active = cur.fetchone()[0]

        print(f"   Total strategies: {total}")
        print(f"   Scheduled strategies: {scheduled}")
        print(f"   Active strategies: {active}")

        # Test market hours
        print("\n4. Current market status:")
        from app.core.market_hours import is_market_open

        markets = ['NYSE', 'LONDON', 'ASIA']
        for market in markets:
            is_open = is_market_open(market)
            status = "🟢 OPEN" if is_open else "🔴 CLOSED"
            print(f"   {market}: {status}")

        print("\n" + "=" * 60)
        print("RECOMMENDATIONS:")
        print("=" * 60)

        if scheduled == 0:
            print("1. No scheduled strategies found!")
            print("   - Create a strategy with market hours enabled in the UI")
            print("   - Select NYSE, LONDON, or ASIA markets when creating")
        else:
            print(f"1. Found {scheduled} scheduled strategies")
            print("   - Monitor logs for 'Checking X scheduled strategies'")
            print("   - Watch for auto-toggle messages every minute")

        print("\n2. To monitor scheduler:")
        print("   - Check backend logs for scheduler activity")
        print("   - Look for 'Strategy X activated/deactivated by scheduler'")

        print("\n3. Market hours are calculated correctly")
        print("   - NYSE: 9:30 AM - 4:00 PM EST (Mon-Fri)")
        print("   - LONDON: 3:00 AM - 11:30 AM EST (Mon-Fri)")
        print("   - ASIA: 7:00 PM - 1:00 AM EST (Mon-Fri)")

        cur.close()
        conn.close()

    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        print("\nPlease update DB_CONFIG with correct credentials")

if __name__ == "__main__":
    test_database_directly()