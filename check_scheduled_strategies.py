"""
Check which users have strategies with scheduling enabled
"""
import os
import sys
import json
from datetime import datetime
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Add the app directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.core.config import settings
from app.core.market_hours import is_market_open, get_market_info

def check_scheduled_strategies():
    """Check all scheduled strategies in the database"""

    # Create database connection
    engine = create_engine(settings.DATABASE_URL)
    Session = sessionmaker(bind=engine)

    with engine.connect() as conn:
        print("=" * 80)
        print("SCHEDULED STRATEGIES REPORT")
        print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 80)

        # First, check if columns exist
        result = conn.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'activated_strategies'
            AND column_name = 'market_schedule'
        """))

        if not result.fetchone():
            print("\n❌ ERROR: market_schedule column does not exist!")
            print("The database migration needs to be run first.")
            print("\nRun this SQL to add the columns:")
            print("-" * 40)
            print("""
ALTER TABLE activated_strategies
ADD COLUMN IF NOT EXISTS market_schedule JSON,
ADD COLUMN IF NOT EXISTS schedule_active_state BOOLEAN,
ADD COLUMN IF NOT EXISTS last_scheduled_toggle TIMESTAMP;
            """)
            return

        # Get all scheduled strategies with user info
        result = conn.execute(text("""
            SELECT
                s.id as strategy_id,
                s.user_id,
                u.email as user_email,
                s.ticker,
                s.strategy_type,
                s.is_active,
                s.market_schedule,
                s.schedule_active_state,
                s.last_scheduled_toggle,
                s.created_at,
                s.webhook_id,
                s.strategy_code_id,
                s.account_id,
                s.group_name
            FROM activated_strategies s
            JOIN users u ON s.user_id = u.id
            WHERE s.market_schedule IS NOT NULL
            ORDER BY s.user_id, s.created_at
        """))

        scheduled_strategies = result.fetchall()

        if not scheduled_strategies:
            print("\n📊 No strategies with scheduling enabled found.")
            print("\nUsers will need to:")
            print("1. Edit their existing strategies")
            print("2. Enable 'Schedule by Market Hours'")
            print("3. Select their preferred markets")
            return

        # Group by user
        users_with_schedules = {}
        for row in scheduled_strategies:
            user_id = row[1]
            if user_id not in users_with_schedules:
                users_with_schedules[user_id] = {
                    'email': row[2],
                    'strategies': []
                }

            # Parse market schedule
            market_schedule = row[6]
            if isinstance(market_schedule, str):
                try:
                    market_schedule = json.loads(market_schedule)
                except:
                    pass

            users_with_schedules[user_id]['strategies'].append({
                'id': row[0],
                'ticker': row[3],
                'type': row[4],
                'is_active': row[5],
                'markets': market_schedule,
                'schedule_state': row[7],
                'last_toggle': row[8],
                'created': row[9],
                'webhook_id': row[10],
                'strategy_code_id': row[11],
                'account_id': row[12],
                'group_name': row[13]
            })

        # Print report
        print(f"\n✅ Found {len(scheduled_strategies)} scheduled strategies from {len(users_with_schedules)} users")
        print("\n" + "=" * 80)
        print("USER BREAKDOWN:")
        print("=" * 80)

        for user_id, user_data in users_with_schedules.items():
            print(f"\n👤 User: {user_data['email']} (ID: {user_id})")
            print(f"   Scheduled Strategies: {len(user_data['strategies'])}")

            for strategy in user_data['strategies']:
                # Check current market status
                markets_status = []
                if strategy['markets']:
                    for market in strategy['markets']:
                        is_open = is_market_open(market)
                        status = "🟢" if is_open else "🔴"
                        markets_status.append(f"{market}{status}")

                print(f"\n   📊 Strategy ID: {strategy['id']}")
                print(f"      - Ticker: {strategy['ticker']}")
                print(f"      - Type: {strategy['type']}")
                print(f"      - Current State: {'🟢 ACTIVE' if strategy['is_active'] else '🔴 INACTIVE'}")
                print(f"      - Markets: {', '.join(markets_status) if markets_status else 'None'}")
                print(f"      - Last Auto-Toggle: {strategy['last_toggle'] or 'Never'}")

                # Determine what should happen
                if strategy['markets'] and '24/7' not in strategy['markets']:
                    any_market_open = any(is_market_open(m) for m in strategy['markets'])
                    should_be_active = any_market_open

                    if should_be_active != strategy['is_active']:
                        print(f"      ⚠️ NEEDS TOGGLE: Should be {'ACTIVE' if should_be_active else 'INACTIVE'}")
                        print(f"         (Will auto-toggle on next scheduler run)")

        # Summary
        print("\n" + "=" * 80)
        print("CURRENT MARKET STATUS:")
        print("=" * 80)

        markets = ['NYSE', 'LONDON', 'ASIA']
        for market in markets:
            info = get_market_info(market)
            status = "🟢 OPEN" if info['is_open'] else "🔴 CLOSED"
            print(f"{market:10} {status:10} | {info['display_hours']}")

        print("\n" + "=" * 80)
        print("WHAT HAPPENS NEXT:")
        print("=" * 80)
        print("\n✅ EXISTING SCHEDULED STRATEGIES WILL WORK AUTOMATICALLY!")
        print("\nOnce the backend is restarted:")
        print("1. The scheduler will run every minute")
        print("2. It will find all strategies with market_schedule set")
        print("3. It will auto-toggle them based on market hours")
        print("4. No user action required for existing scheduled strategies")

        if users_with_schedules:
            print("\n📋 Affected Users:")
            for user_id, user_data in users_with_schedules.items():
                print(f"   - {user_data['email']}: {len(user_data['strategies'])} scheduled strategies")

        # Check unscheduled strategies
        result = conn.execute(text("""
            SELECT COUNT(*)
            FROM activated_strategies
            WHERE market_schedule IS NULL
        """))
        unscheduled_count = result.fetchone()[0]

        if unscheduled_count > 0:
            print(f"\n📌 Note: {unscheduled_count} strategies without scheduling")
            print("   These will continue to operate manually as before")

if __name__ == "__main__":
    try:
        check_scheduled_strategies()
    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("\nTroubleshooting:")
        print("1. Make sure you're in the fastapi_backend directory")
        print("2. Check database connection settings")
        print("3. Ensure database is running")