#!/usr/bin/env python
"""
Script to fix user mapping for stddev_breakout strategy.
Corrects the strategy to execute on the correct user account (39 instead of 163).
"""
import os
import sys
from datetime import datetime
import psycopg2
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def main():
    """Fix the user mapping for stddev_breakout strategy."""
    
    # Get database URL
    database_url = os.getenv("DEV_DATABASE_URL") or os.getenv("DATABASE_PRIVATE_URL") or os.getenv("DATABASE_URL")
    
    if not database_url:
        print("ERROR: No database URL found in environment variables")
        return
    
    print("=" * 60)
    print("STDDEV BREAKOUT STRATEGY - USER MAPPING FIX")
    print("=" * 60)
    
    # Connect to database
    conn = psycopg2.connect(database_url)
    cursor = conn.cursor()
    
    try:
        # Step 1: Analyze current state
        print("\n1. ANALYZING CURRENT CONFIGURATION...")
        print("-" * 40)
        
        # Check strategy_codes
        cursor.execute("""
            SELECT id, user_id, name, is_active, created_at
            FROM strategy_codes 
            WHERE name = 'stddev_breakout'
        """)
        strategy_code = cursor.fetchone()
        
        if not strategy_code:
            print("ERROR: stddev_breakout strategy not found in database")
            return
        
        strategy_id, current_user_id, name, is_active, created_at = strategy_code
        print(f"Strategy Code ID: {strategy_id}")
        print(f"Current User ID: {current_user_id}")
        print(f"Active: {is_active}")
        
        # Check activated_strategies
        cursor.execute("""
            SELECT id, user_id, account_id, ticker, quantity, is_active
            FROM activated_strategies 
            WHERE strategy_code_id = %s
            ORDER BY user_id
        """, (strategy_id,))
        activations = cursor.fetchall()
        
        print(f"\nCurrent Activations ({len(activations)}):")
        for activation in activations:
            act_id, user_id, account_id, ticker, quantity, active = activation
            print(f"  - Activation ID {act_id}: User {user_id}, Account {account_id}, Active: {active}")
        
        # Check users
        user_ids = [39, 163] + ([current_user_id] if current_user_id not in [39, 163] else [])
        cursor.execute(f"""
            SELECT id, email, username
            FROM users 
            WHERE id = ANY(%s)
        """, (user_ids,))
        users = cursor.fetchall()
        
        print(f"\nRelevant Users:")
        for user in users:
            user_id, email, username = user
            print(f"  - User {user_id}: {username} ({email})")
        
        # Check broker accounts for target user
        cursor.execute("""
            SELECT user_id, account_id, broker_id, is_active
            FROM broker_accounts 
            WHERE user_id = %s
            ORDER BY is_active DESC
        """, (39,))
        user39_accounts = cursor.fetchall()
        
        print(f"\nUser 39 Broker Accounts:")
        if user39_accounts:
            for account in user39_accounts:
                user_id, account_id, broker_name, active = account
                print(f"  - Account {account_id}: {broker_name} (Active: {active})")
        else:
            print("  - No broker accounts found for User 39")
            print("  - ERROR: Cannot proceed without a valid broker account")
            return
        
        # Get active account for user 39
        active_account = next((acc for acc in user39_accounts if acc[3]), None)
        if not active_account:
            print("  - ERROR: No active broker account found for User 39")
            return
        
        target_account_id = active_account[1]
        target_broker = active_account[2]
        
        print(f"\nTarget Configuration:")
        print(f"  - User ID: 39")
        print(f"  - Account ID: {target_account_id}")
        print(f"  - Broker: {target_broker}")
        
        # Step 2: Confirm changes
        print(f"\n2. PROPOSED CHANGES:")
        print("-" * 40)
        print(f"+ Update strategy_codes.user_id from {current_user_id} -> 39")
        print(f"+ Deactivate wrong activations (User 163)")
        print(f"+ Create/update activation for User 39 with account {target_account_id}")
        
        # Auto-proceed (since we're running in automated context)
        print("\nProceeding with changes automatically...")
        response = 'yes'
        
        # Step 3: Apply fixes
        print(f"\n3. APPLYING FIXES...")
        print("-" * 40)
        
        # Fix 1: Update strategy_codes user_id
        if current_user_id != 39:
            cursor.execute("""
                UPDATE strategy_codes 
                SET user_id = %s, updated_at = %s
                WHERE id = %s
            """, (39, datetime.utcnow(), strategy_id))
            print(f"+ Updated strategy_codes.user_id: {current_user_id} -> 39")
        
        # Fix 2: Deactivate wrong activations
        wrong_activations = [act for act in activations if act[1] != 39 and act[5]]  # Active but wrong user
        if wrong_activations:
            for activation in wrong_activations:
                cursor.execute("""
                    UPDATE activated_strategies 
                    SET is_active = false, updated_at = %s
                    WHERE id = %s
                """, (datetime.utcnow(), activation[0]))
                print(f"+ Deactivated wrong activation ID {activation[0]} (User {activation[1]})")
        
        # Fix 3: Create/update correct activation
        user39_activation = next((act for act in activations if act[1] == 39), None)
        
        if user39_activation:
            # Update existing activation
            cursor.execute("""
                UPDATE activated_strategies 
                SET account_id = %s, 
                    is_active = true, 
                    updated_at = %s
                WHERE id = %s
            """, (target_account_id, datetime.utcnow(), user39_activation[0]))
            print(f"+ Updated existing activation ID {user39_activation[0]} for User 39")
        else:
            # Create new activation
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
                39,            # user_id - CORRECT USER
                'single',      # strategy_type
                'engine',      # execution_type for Strategy Engine
                strategy_id,   # strategy_code_id
                'MNQ',         # ticker
                1,             # quantity (default - can be adjusted later)
                target_account_id,  # account_id - CORRECT ACCOUNT
                True,          # is_active
                datetime.utcnow(),
                3,             # max_position_size
                1.0,           # stop_loss_percent
                2.0            # take_profit_percent
            ))
            new_activation_id = cursor.fetchone()[0]
            print(f"+ Created new activation ID {new_activation_id} for User 39")
        
        # Commit all changes
        conn.commit()
        
        # Step 4: Verify fixes
        print(f"\n4. VERIFICATION:")
        print("-" * 40)
        
        # Re-check configuration
        cursor.execute("""
            SELECT sc.id, sc.user_id, sc.name,
                   ast.id, ast.user_id, ast.account_id, ast.is_active
            FROM strategy_codes sc
            LEFT JOIN activated_strategies ast ON sc.id = ast.strategy_code_id
            WHERE sc.name = 'stddev_breakout' AND ast.is_active = true
        """)
        
        verification = cursor.fetchall()
        
        print("Final Configuration:")
        for row in verification:
            sc_id, sc_user, sc_name, ast_id, ast_user, ast_account, ast_active = row
            print(f"  Strategy Code ID {sc_id}: User {sc_user}")
            print(f"  Activation ID {ast_id}: User {ast_user}, Account {ast_account}, Active: {ast_active}")
        
        success = all(row[1] == 39 and row[4] == 39 for row in verification)
        
        if success:
            print(f"\n[SUCCESS] Strategy mapping fixed!")
            print(f"   - Strategy will now execute on User ID 39")
            print(f"   - Using broker account {target_account_id}")
            print(f"   - All wrong activations deactivated")
            
            print(f"\n📋 NEXT STEPS:")
            print(f"   1. Restart Strategy Engine to pick up changes")
            print(f"   2. Monitor logs for correct user execution")
            print(f"   3. Verify trades execute on the correct Tradovate account")
        else:
            print(f"\n[ERROR] VERIFICATION FAILED - Please check database manually")
        
    except Exception as e:
        print(f"ERROR: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    main()