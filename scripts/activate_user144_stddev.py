#!/usr/bin/env python
"""
Script to activate the stddev_breakout strategy for User 144 (newbierichie).
"""
import os
import psycopg2
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def main():
    """Activate stddev_breakout strategy for User 144."""
    
    # Get database URL
    database_url = os.getenv("DEV_DATABASE_URL") or os.getenv("DATABASE_PRIVATE_URL") or os.getenv("DATABASE_URL")
    
    if not database_url:
        print("ERROR: No database URL found in environment variables")
        return
    
    print("=" * 70)
    print("ACTIVATING STDDEV_BREAKOUT STRATEGY FOR USER 144")
    print("=" * 70)
    
    # Connect to database
    conn = psycopg2.connect(database_url)
    cursor = conn.cursor()
    
    USER_ID = 144
    
    try:
        # Step 1: Verify User 144 exists
        print("\n1. VERIFYING USER 144:")
        print("-" * 50)
        
        cursor.execute("""
            SELECT id, username, email, created_at
            FROM users 
            WHERE id = %s
        """, (USER_ID,))
        
        user = cursor.fetchone()
        
        if not user:
            print(f"ERROR: User {USER_ID} not found in database")
            return
        
        user_id, username, email, created_at = user
        print(f"User found: {username} ({email})")
        print(f"User ID: {user_id}")
        print(f"Account created: {created_at}")
        
        # Step 2: Check User 144's broker accounts
        print(f"\n2. CHECKING BROKER ACCOUNTS:")
        print("-" * 50)
        
        cursor.execute("""
            SELECT account_id, broker_id, is_active, created_at
            FROM broker_accounts 
            WHERE user_id = %s
            ORDER BY is_active DESC, created_at DESC
        """, (USER_ID,))
        
        broker_accounts = cursor.fetchall()
        
        if not broker_accounts:
            print(f"ERROR: No broker accounts found for User {USER_ID}")
            print("User needs to connect a broker account first!")
            return
        
        print(f"Found {len(broker_accounts)} broker account(s):")
        active_account = None
        
        for account in broker_accounts:
            account_id, broker_id, is_active, created = account
            status = "ACTIVE" if is_active else "inactive"
            print(f"  - Account {account_id}: {broker_id} ({status})")
            if is_active and not active_account:
                active_account = account
        
        if not active_account:
            print(f"\nERROR: No active broker account found for User {USER_ID}")
            print("Please activate a broker account first")
            return
        
        target_account_id = active_account[0]
        target_broker = active_account[1]
        
        print(f"\nWill use account: {target_account_id} ({target_broker})")
        
        # Step 3: Get the stddev_breakout strategy
        print(f"\n3. FINDING STDDEV_BREAKOUT STRATEGY:")
        print("-" * 50)
        
        cursor.execute("""
            SELECT id, name, user_id, is_active
            FROM strategy_codes 
            WHERE name = 'stddev_breakout'
        """)
        
        strategy = cursor.fetchone()
        
        if not strategy:
            print("ERROR: stddev_breakout strategy not found in database")
            print("Please run add_stddev_breakout_strategy.py first")
            return
        
        strategy_id, strategy_name, owner_id, is_active = strategy
        print(f"Strategy found: {strategy_name}")
        print(f"Strategy ID: {strategy_id}")
        print(f"Owner: User {owner_id}")
        print(f"Active: {is_active}")
        
        # Step 4: Check existing activations
        print(f"\n4. CHECKING EXISTING ACTIVATIONS:")
        print("-" * 50)
        
        cursor.execute("""
            SELECT id, is_active, ticker, quantity, account_id, created_at
            FROM activated_strategies 
            WHERE strategy_code_id = %s AND user_id = %s
        """, (strategy_id, USER_ID))
        
        existing = cursor.fetchall()
        
        if existing:
            print(f"Found {len(existing)} existing activation(s) for User {USER_ID}:")
            for activation in existing:
                act_id, is_active, ticker, quantity, account_id, created = activation
                status = "ACTIVE" if is_active else "INACTIVE"
                print(f"  - ID {act_id}: {status}, {ticker}, Qty {quantity}, Account {account_id}")
            
            # Check if there's already an active one
            active_existing = [a for a in existing if a[1]]  # is_active = True
            if active_existing:
                print(f"\nUser {USER_ID} already has {len(active_existing)} ACTIVE activation(s)")
                print("No action needed - user is already subscribed!")
                return
            
            # Reactivate an existing one
            print(f"\nReactivating existing activation...")
            latest_activation = existing[0]  # Most recent one
            cursor.execute("""
                UPDATE activated_strategies 
                SET is_active = true,
                    account_id = %s,
                    updated_at = %s
                WHERE id = %s
            """, (target_account_id, datetime.utcnow(), latest_activation[0]))
            
            conn.commit()
            print(f"+ Reactivated activation ID {latest_activation[0]} for User {USER_ID}")
            
        else:
            print(f"No existing activations found for User {USER_ID}")
            
            # Step 5: Create new activation
            print(f"\n5. CREATING NEW ACTIVATION:")
            print("-" * 50)
            
            cursor.execute("""
                INSERT INTO activated_strategies (
                    user_id,
                    strategy_type,
                    execution_type,
                    strategy_code_id,
                    ticker,
                    quantity,
                    account_id,
                    is_active,
                    created_at,
                    max_position_size,
                    stop_loss_percent,
                    take_profit_percent
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                RETURNING id
            """, (
                USER_ID,           # user_id - User 144
                'single',          # strategy_type
                'engine',          # execution_type for Strategy Engine
                strategy_id,       # strategy_code_id
                'MNQ',             # ticker
                1,                 # quantity (default - can be adjusted)
                target_account_id, # account_id
                True,              # is_active
                datetime.utcnow(),
                3,                 # max_position_size
                1.0,               # stop_loss_percent
                2.0                # take_profit_percent
            ))
            
            new_activation_id = cursor.fetchone()[0]
            conn.commit()
            
            print(f"+ Created new activation ID {new_activation_id} for User {USER_ID}")
        
        # Step 6: Verify final state
        print(f"\n6. VERIFICATION:")
        print("-" * 50)
        
        cursor.execute("""
            SELECT 
                ast.id,
                ast.user_id,
                ast.account_id,
                ast.ticker,
                ast.quantity,
                ast.is_active,
                u.username,
                ba.broker_id
            FROM activated_strategies ast
            JOIN users u ON ast.user_id = u.id
            JOIN broker_accounts ba ON ast.account_id = ba.account_id
            WHERE ast.strategy_code_id = %s 
                AND ast.user_id = %s 
                AND ast.is_active = true
        """, (strategy_id, USER_ID))
        
        verification = cursor.fetchone()
        
        if verification:
            (act_id, user_id, account_id, ticker, quantity, 
             is_active, username, broker) = verification
            
            print(f"[SUCCESS] User {USER_ID} is now subscribed to stddev_breakout!")
            print(f"  Activation ID: {act_id}")
            print(f"  User: {username} (ID {user_id})")
            print(f"  Account: {account_id} ({broker})")
            print(f"  Symbol: {ticker}")
            print(f"  Quantity: {quantity} contract(s)")
            print(f"  Status: ACTIVE")
            
            print(f"\n[NEXT STEPS]")
            print(f"  1. Restart Strategy Engine to pick up the new subscription")
            print(f"  2. User {USER_ID} will now receive stddev_breakout trade signals")
            print(f"  3. Trades will execute on account {account_id}")
        else:
            print(f"[ERROR] Verification failed - please check database manually")
        
    except Exception as e:
        print(f"ERROR: {e}")
        conn.rollback()
        import traceback
        traceback.print_exc()
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    main()