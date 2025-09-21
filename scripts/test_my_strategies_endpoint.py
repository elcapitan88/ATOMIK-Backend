#!/usr/bin/env python
"""
Test the /my-strategies endpoint for both User 39 and User 144 to see 
what strategies are returned.
"""
import os
import psycopg2
from dotenv import load_dotenv
from datetime import datetime

# Load environment variables
load_dotenv()

def test_my_strategies_logic(user_id, username):
    """Test the logic of /my-strategies endpoint for a specific user."""
    
    # Get database URL
    database_url = os.getenv("DEV_DATABASE_URL") or os.getenv("DATABASE_PRIVATE_URL") or os.getenv("DATABASE_URL")
    conn = psycopg2.connect(database_url)
    cursor = conn.cursor()
    
    print(f"\n{'='*80}")
    print(f"TESTING /MY-STRATEGIES ENDPOINT LOGIC FOR USER {user_id} ({username})")
    print(f"{'='*80}")
    print(f"Timestamp: {datetime.now()}")
    
    try:
        # Step 1: Get strategies the user owns
        print(f"\n1. STRATEGIES OWNED BY USER {user_id}:")
        print("-" * 60)
        
        cursor.execute("""
            SELECT id, name, user_id, is_active, is_validated, created_at
            FROM strategy_codes 
            WHERE user_id = %s
            ORDER BY created_at DESC
        """, (user_id,))
        
        owned_strategies = cursor.fetchall()
        
        if owned_strategies:
            print(f"Found {len(owned_strategies)} owned strategy code(s):")
            for strategy in owned_strategies:
                id, name, owner_id, is_active, is_validated, created_at = strategy
                print(f"  - {name} (ID: {id}) - Active: {is_active}, Validated: {is_validated}")
        else:
            print(f"User {user_id} owns 0 strategy codes")
        
        # Step 2: Get strategy IDs the user is subscribed to
        print(f"\n2. ENGINE STRATEGY SUBSCRIPTIONS FOR USER {user_id}:")
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
                AND strategy_code_id IS NOT NULL
        """, (user_id,))
        
        subscriptions = cursor.fetchall()
        subscribed_strategy_ids = []
        
        if subscriptions:
            print(f"Found {len(subscriptions)} engine subscription(s):")
            for sub in subscriptions:
                sub_id, strategy_type, code_id, subscribed_at = sub
                subscribed_strategy_ids.append(code_id)
                print(f"  - Subscription {sub_id}: Strategy Code ID {code_id} (subscribed: {subscribed_at})")
        else:
            print(f"User {user_id} has 0 engine strategy subscriptions")
        
        # Step 3: Get the subscribed strategies details
        subscribed_strategies = []
        if subscribed_strategy_ids:
            print(f"\n3. SUBSCRIBED STRATEGY DETAILS:")
            print("-" * 60)
            
            placeholders = ','.join(['%s'] * len(subscribed_strategy_ids))
            cursor.execute(f"""
                SELECT id, name, user_id, is_active, is_validated, created_at
                FROM strategy_codes 
                WHERE id IN ({placeholders})
            """, subscribed_strategy_ids)
            
            subscribed_strategies = cursor.fetchall()
            
            for strategy in subscribed_strategies:
                id, name, owner_id, is_active, is_validated, created_at = strategy
                print(f"  - {name} (ID: {id}) - Owner: User {owner_id}, Active: {is_active}, Validated: {is_validated}")
        else:
            print(f"\n3. No subscribed strategies to fetch details for")
        
        # Step 4: Combine and show final result
        print(f"\n4. FINAL COMBINED RESULT (What /my-strategies should return):")
        print("-" * 60)
        
        # Simulate the endpoint logic
        all_strategies = {}
        
        # Add owned strategies
        for strategy in owned_strategies:
            all_strategies[strategy[0]] = strategy  # strategy[0] is the ID
        
        # Add subscribed strategies (avoid duplicates)
        for strategy in subscribed_strategies:
            if strategy[0] not in all_strategies:  # Only add if not already owned
                all_strategies[strategy[0]] = strategy
        
        if all_strategies:
            print(f"Total strategies accessible to User {user_id}: {len(all_strategies)}")
            for strategy_id, strategy in all_strategies.items():
                id, name, owner_id, is_active, is_validated, created_at = strategy
                access_type = "OWNED" if owner_id == user_id else "SUBSCRIBED"
                print(f"  - {name} (ID: {id}) - {access_type} - Active: {is_active}, Validated: {is_validated}")
        else:
            print(f"User {user_id} has NO accessible strategies (neither owned nor subscribed)")
        
        # Step 5: Check what should appear in ActivateStrategyModal
        print(f"\n5. WHAT SHOULD APPEAR IN ACTIVATESTRATEGYMODAL:")
        print("-" * 60)
        
        active_strategies = [s for s in all_strategies.values() if s[3] and s[4]]  # is_active and is_validated
        
        if active_strategies:
            print(f"Strategies that should appear in dropdown: {len(active_strategies)}")
            for strategy in active_strategies:
                id, name, owner_id, is_active, is_validated, created_at = strategy
                display_name = name
                if name == 'stddev_breakout':
                    display_name = 'Standard Deviation Breakout'
                elif name == 'momentum_scalper':
                    display_name = 'Momentum Scalper'
                elif name == 'mean_reversion':
                    display_name = 'Mean Reversion'
                
                access_type = "OWNED" if owner_id == user_id else "SUBSCRIBED"
                print(f"  - {display_name} ({access_type})")
        else:
            print(f"NO strategies should appear in dropdown for User {user_id}")
            print("Reasons could be:")
            print("  - User has no owned or subscribed strategies")
            print("  - Strategies are not active or not validated")
        
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        cursor.close()
        conn.close()

def main():
    """Test both users."""
    print("TESTING /MY-STRATEGIES ENDPOINT LOGIC")
    
    # Test User 39 (Elcapitan14)
    test_my_strategies_logic(39, "Elcapitan14")
    
    # Test User 144 (newbierichie)  
    test_my_strategies_logic(144, "newbierichie")
    
    print(f"\n{'='*80}")
    print("TESTING COMPLETE")
    print(f"{'='*80}")

if __name__ == "__main__":
    main()