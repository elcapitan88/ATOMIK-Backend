#!/usr/bin/env python
"""
Check if User 144 has a subscription to the stddev_breakout strategy.
"""
import os
import psycopg2
from dotenv import load_dotenv
from datetime import datetime

# Load environment variables
load_dotenv()

def main():
    """Check User 144's subscription status."""
    
    # Get database URL
    database_url = os.getenv("DEV_DATABASE_URL") or os.getenv("DATABASE_PRIVATE_URL") or os.getenv("DATABASE_URL")
    
    if not database_url:
        print("ERROR: No database URL found in environment variables")
        return
    
    print("=" * 80)
    print("USER 144 - STDDEV_BREAKOUT SUBSCRIPTION CHECK")
    print("=" * 80)
    print(f"Timestamp: {datetime.now()}")
    print()
    
    # Connect to database
    conn = psycopg2.connect(database_url)
    cursor = conn.cursor()
    
    try:
        # Step 1: Check if User 144 exists
        print("1. USER 144 INFORMATION:")
        print("-" * 60)
        
        cursor.execute("""
            SELECT id, username, email, created_at
            FROM users 
            WHERE id = 144
        """)
        
        user = cursor.fetchone()
        if not user:
            print("ERROR: User 144 not found")
            return
        
        user_id, username, email, created_at = user
        print(f"User: {username} ({email})")
        print(f"User ID: {user_id}")
        print(f"Member since: {created_at}")
        
        # Step 2: Check for stddev_breakout strategy
        print("\n2. STDDEV_BREAKOUT STRATEGY:")
        print("-" * 60)
        
        cursor.execute("""
            SELECT id, name, user_id, is_active, is_validated
            FROM strategy_codes 
            WHERE name = 'stddev_breakout'
        """)
        
        strategy = cursor.fetchone()
        if not strategy:
            print("ERROR: stddev_breakout strategy not found")
            return
        
        strat_id, strat_name, owner_id, is_active, is_validated = strategy
        print(f"Strategy Code ID: {strat_id}")
        print(f"Strategy Name: {strat_name}")
        print(f"Owner: User {owner_id}")
        print(f"Active: {is_active}, Validated: {is_validated}")
        
        # Step 3: Check for subscription
        print("\n3. SUBSCRIPTION STATUS:")
        print("-" * 60)
        
        cursor.execute("""
            SELECT 
                id,
                strategy_type,
                strategy_code_id,
                subscribed_at
            FROM webhook_subscriptions
            WHERE user_id = %s 
                AND strategy_type = 'engine'
                AND strategy_code_id = %s
        """, (144, strat_id))
        
        subscription = cursor.fetchone()
        
        if subscription:
            sub_id, strat_type, code_id, subscribed_at = subscription
            print(f"[SUBSCRIBED] User 144 has an active subscription!")
            print(f"  Subscription ID: {sub_id}")
            print(f"  Strategy Type: {strat_type}")
            print(f"  Strategy Code ID: {code_id}")
            print(f"  Subscribed at: {subscribed_at}")
        else:
            print("[NOT SUBSCRIBED] User 144 does NOT have a subscription to stddev_breakout")
            print("\nTo fix this, User 144 needs to:")
            print("1. Go to the marketplace")
            print("2. Find 'Standard Deviation Breakout' strategy")
            print("3. Click 'Subscribe'")
            print("\nOr run this SQL:")
            print(f"""
INSERT INTO webhook_subscriptions (user_id, strategy_type, strategy_id, strategy_code_id, subscribed_at)
VALUES (144, 'engine', '{strat_id}', {strat_id}, NOW());
            """)
        
        # Step 4: Check if User 144 can see it in my-strategies
        print("\n4. CHECKING MY-STRATEGIES ENDPOINT LOGIC:")
        print("-" * 60)
        
        # Check owned strategies
        cursor.execute("""
            SELECT COUNT(*) FROM strategy_codes 
            WHERE user_id = 144
        """)
        owned_count = cursor.fetchone()[0]
        print(f"Strategies owned by User 144: {owned_count}")
        
        # Check subscribed strategies
        cursor.execute("""
            SELECT COUNT(*) 
            FROM webhook_subscriptions
            WHERE user_id = 144 
                AND strategy_type = 'engine'
                AND strategy_code_id IS NOT NULL
        """)
        subscribed_count = cursor.fetchone()[0]
        print(f"Engine strategies subscribed by User 144: {subscribed_count}")
        
        if subscription:
            print("\n[RESULT] User 144 SHOULD see stddev_breakout in the ActivateStrategyModal dropdown")
        else:
            print("\n[RESULT] User 144 will NOT see stddev_breakout in the dropdown until they subscribe")
        
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    main()