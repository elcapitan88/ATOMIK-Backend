#!/usr/bin/env python
"""
Script to analyze all users subscribed to the stddev_breakout strategy.
Identifies all active and inactive activations for comprehensive review.
"""
import os
import psycopg2
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def main():
    """Analyze all stddev_breakout strategy subscriptions."""
    
    # Get database URL
    database_url = os.getenv("DEV_DATABASE_URL") or os.getenv("DATABASE_PRIVATE_URL") or os.getenv("DATABASE_URL")
    
    if not database_url:
        print("ERROR: No database URL found in environment variables")
        return
    
    print("=" * 70)
    print("STDDEV BREAKOUT STRATEGY - SUBSCRIPTION ANALYSIS")
    print("=" * 70)
    
    # Connect to database
    conn = psycopg2.connect(database_url)
    cursor = conn.cursor()
    
    try:
        # Step 1: Get the strategy code
        print("\n1. STRATEGY INFORMATION:")
        print("-" * 50)
        
        cursor.execute("""
            SELECT id, user_id, name, is_active, created_at, updated_at
            FROM strategy_codes 
            WHERE name = 'stddev_breakout'
        """)
        strategy_code = cursor.fetchone()
        
        if not strategy_code:
            print("ERROR: stddev_breakout strategy not found in database")
            return
        
        strategy_id, owner_user_id, name, is_active, created_at, updated_at = strategy_code
        print(f"Strategy Code ID: {strategy_id}")
        print(f"Strategy Name: {name}")
        print(f"Owner User ID: {owner_user_id}")
        print(f"Active: {is_active}")
        print(f"Created: {created_at}")
        print(f"Updated: {updated_at}")
        
        # Step 2: Get ALL activations (active and inactive)
        print(f"\n2. ALL STRATEGY ACTIVATIONS:")
        print("-" * 50)
        
        cursor.execute("""
            SELECT 
                ast.id,
                ast.user_id, 
                ast.account_id,
                ast.ticker,
                ast.quantity,
                ast.is_active,
                ast.created_at,
                ast.updated_at,
                ast.execution_type,
                ast.strategy_type
            FROM activated_strategies ast
            WHERE ast.strategy_code_id = %s
            ORDER BY ast.user_id, ast.created_at DESC
        """, (strategy_id,))
        
        all_activations = cursor.fetchall()
        
        if not all_activations:
            print("No activations found for this strategy")
            return
            
        print(f"Found {len(all_activations)} total activations:")
        print()
        
        # Group by user for better analysis
        user_activations = {}
        for activation in all_activations:
            (act_id, user_id, account_id, ticker, quantity, is_active, 
             created_at, updated_at, execution_type, strategy_type) = activation
            
            if user_id not in user_activations:
                user_activations[user_id] = []
            user_activations[user_id].append(activation)
        
        # Step 3: Analyze each user's activations
        print("BREAKDOWN BY USER:")
        print("-" * 30)
        
        active_users = []
        inactive_users = []
        
        for user_id in sorted(user_activations.keys()):
            user_acts = user_activations[user_id]
            active_acts = [act for act in user_acts if act[5]]  # is_active = True
            
            print(f"\nUser ID {user_id}:")
            
            # Get user details
            cursor.execute("""
                SELECT username, email, created_at
                FROM users 
                WHERE id = %s
            """, (user_id,))
            user_info = cursor.fetchone()
            
            if user_info:
                username, email, user_created = user_info
                print(f"  Name: {username} ({email})")
                print(f"  User created: {user_created}")
            else:
                print(f"  Name: [User not found]")
            
            # Show activation details
            print(f"  Total activations: {len(user_acts)}")
            print(f"  Active activations: {len(active_acts)}")
            
            for i, activation in enumerate(user_acts, 1):
                (act_id, _, account_id, ticker, quantity, is_active, 
                 created_at, updated_at, execution_type, strategy_type) = activation
                
                status = "ACTIVE" if is_active else "INACTIVE"
                print(f"    #{i} - ID {act_id}: {status}")
                print(f"         Account: {account_id}")
                print(f"         Ticker: {ticker}, Quantity: {quantity}")
                print(f"         Type: {execution_type}/{strategy_type}")
                print(f"         Created: {created_at}")
                print(f"         Updated: {updated_at}")
            
            # Categorize user
            if active_acts:
                active_users.append(user_id)
            else:
                inactive_users.append(user_id)
        
        # Step 4: Check broker accounts for all involved users
        print(f"\n3. BROKER ACCOUNT VERIFICATION:")
        print("-" * 50)
        
        all_user_ids = list(user_activations.keys())
        if all_user_ids:
            cursor.execute("""
                SELECT user_id, account_id, broker_id, is_active, created_at
                FROM broker_accounts 
                WHERE user_id = ANY(%s)
                ORDER BY user_id, is_active DESC, created_at DESC
            """, (all_user_ids,))
            
            broker_accounts = cursor.fetchall()
            
            # Group by user
            user_accounts = {}
            for account in broker_accounts:
                user_id, account_id, broker_id, is_active, created_at = account
                if user_id not in user_accounts:
                    user_accounts[user_id] = []
                user_accounts[user_id].append(account)
            
            for user_id in sorted(all_user_ids):
                print(f"\nUser {user_id} Broker Accounts:")
                if user_id in user_accounts:
                    accounts = user_accounts[user_id]
                    active_accounts = [acc for acc in accounts if acc[3]]
                    print(f"  Total: {len(accounts)}, Active: {len(active_accounts)}")
                    
                    for account in accounts[:3]:  # Show top 3 accounts
                        _, account_id, broker_id, is_active, created_at = account
                        status = "ACTIVE" if is_active else "inactive"
                        print(f"    {account_id}: {broker_id} ({status})")
                    
                    if len(accounts) > 3:
                        print(f"    ... and {len(accounts) - 3} more")
                else:
                    print(f"  No broker accounts found")
        
        # Step 5: Summary and specific check for User 144
        print(f"\n4. SUMMARY:")
        print("-" * 50)
        
        print(f"Strategy Owner: User {owner_user_id}")
        print(f"Total Users with Activations: {len(user_activations)}")
        print(f"Users with ACTIVE subscriptions: {len(active_users)} - {active_users}")
        print(f"Users with INACTIVE subscriptions: {len(inactive_users)} - {inactive_users}")
        
        # Specific check for User 144
        print(f"\n5. USER 144 SPECIFIC CHECK:")
        print("-" * 50)
        
        if 144 in user_activations:
            user_144_acts = user_activations[144]
            active_144 = [act for act in user_144_acts if act[5]]
            
            print(f"USER 144 IS FOUND IN ACTIVATIONS!")
            print(f"  Total activations: {len(user_144_acts)}")
            print(f"  Active activations: {len(active_144)}")
            
            if active_144:
                print(f"  STATUS: ACTIVELY SUBSCRIBED")
                for act in active_144:
                    print(f"    Active ID {act[0]}: Account {act[2]}, Quantity {act[4]}")
            else:
                print(f"  STATUS: HAS INACTIVE SUBSCRIPTIONS ONLY")
        else:
            print(f"USER 144 NOT FOUND - No activations for stddev_breakout strategy")
        
        # Check if User 144 exists at all
        cursor.execute("SELECT id, username, email FROM users WHERE id = 144")
        user_144 = cursor.fetchone()
        
        if user_144:
            print(f"  User 144 exists: {user_144[1]} ({user_144[2]})")
        else:
            print(f"  User 144 does not exist in users table")
            
        print(f"\n" + "=" * 70)
        
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    main()