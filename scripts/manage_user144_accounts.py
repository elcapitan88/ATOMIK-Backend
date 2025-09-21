#!/usr/bin/env python
"""
Script to manage User 144's multiple account subscriptions for stddev_breakout strategy.
Allows viewing all accounts and activating strategy on multiple accounts.
"""
import os
import psycopg2
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def main():
    """Manage User 144's multiple account subscriptions."""
    
    # Get database URL
    database_url = os.getenv("DEV_DATABASE_URL") or os.getenv("DATABASE_PRIVATE_URL") or os.getenv("DATABASE_URL")
    
    if not database_url:
        print("ERROR: No database URL found in environment variables")
        return
    
    print("=" * 80)
    print("USER 144 - MULTIPLE ACCOUNT MANAGEMENT FOR STDDEV_BREAKOUT")
    print("=" * 80)
    
    # Connect to database
    conn = psycopg2.connect(database_url)
    cursor = conn.cursor()
    
    USER_ID = 144
    
    try:
        # Step 1: Get User 144 info
        print("\n1. USER INFORMATION:")
        print("-" * 60)
        
        cursor.execute("""
            SELECT id, username, email, created_at
            FROM users 
            WHERE id = %s
        """, (USER_ID,))
        
        user = cursor.fetchone()
        if not user:
            print(f"ERROR: User {USER_ID} not found")
            return
        
        user_id, username, email, created_at = user
        print(f"User: {username} ({email})")
        print(f"User ID: {user_id}")
        print(f"Member since: {created_at}")
        
        # Step 2: Get ALL broker accounts with details
        print(f"\n2. ALL BROKER ACCOUNTS FOR USER {USER_ID}:")
        print("-" * 60)
        
        cursor.execute("""
            SELECT 
                ba.account_id,
                ba.broker_id,
                ba.is_active,
                ba.created_at
            FROM broker_accounts ba
            WHERE ba.user_id = %s
            ORDER BY ba.is_active DESC, ba.created_at DESC
        """, (USER_ID,))
        
        all_accounts = cursor.fetchall()
        
        if not all_accounts:
            print("No broker accounts found")
            return
        
        print(f"Total accounts: {len(all_accounts)}")
        
        active_accounts = []
        inactive_accounts = []
        
        print("\nACTIVE ACCOUNTS:")
        print("-" * 40)
        for account in all_accounts:
            account_id, broker_id, is_active, created = account
            if is_active:
                active_accounts.append(account)
                print(f"  [{len(active_accounts)}] Account: {account_id}")
                print(f"      Broker: {broker_id}")
                print(f"      Created: {created}")
                print()
            else:
                inactive_accounts.append(account)
        
        if not active_accounts:
            print("  No active accounts found")
        
        print(f"\nINACTIVE ACCOUNTS: {len(inactive_accounts)} accounts")
        if inactive_accounts and len(inactive_accounts) <= 5:
            for account in inactive_accounts[:5]:
                account_id, broker_id, _, created = account
                print(f"  - {account_id} ({broker_id}) - created {created}")
        
        # Step 3: Get strategy info
        print(f"\n3. STDDEV_BREAKOUT STRATEGY:")
        print("-" * 60)
        
        cursor.execute("""
            SELECT id, name, user_id, is_active
            FROM strategy_codes 
            WHERE name = 'stddev_breakout'
        """)
        
        strategy = cursor.fetchone()
        if not strategy:
            print("ERROR: stddev_breakout strategy not found")
            return
        
        strategy_id, strategy_name, owner_id, is_active = strategy
        print(f"Strategy: {strategy_name}")
        print(f"Strategy ID: {strategy_id}")
        print(f"Owner: User {owner_id}")
        print(f"Active: {is_active}")
        
        # Step 4: Check current activations
        print(f"\n4. CURRENT STRATEGY ACTIVATIONS FOR USER {USER_ID}:")
        print("-" * 60)
        
        cursor.execute("""
            SELECT 
                ast.id,
                ast.account_id,
                ast.is_active,
                ast.ticker,
                ast.quantity,
                ast.created_at,
                ast.updated_at,
                ba.broker_id
            FROM activated_strategies ast
            LEFT JOIN broker_accounts ba ON ast.account_id = ba.account_id
            WHERE ast.strategy_code_id = %s AND ast.user_id = %s
            ORDER BY ast.is_active DESC, ast.created_at DESC
        """, (strategy_id, USER_ID))
        
        existing_activations = cursor.fetchall()
        
        if existing_activations:
            print(f"Found {len(existing_activations)} existing activation(s):")
            
            active_activations = []
            for activation in existing_activations:
                (act_id, account_id, is_active, ticker, quantity, 
                 created, updated, broker) = activation
                status = "ACTIVE" if is_active else "INACTIVE"
                
                if is_active:
                    active_activations.append(activation)
                    
                print(f"\n  Activation ID: {act_id} ({status})")
                print(f"    Account: {account_id} ({broker})")
                print(f"    Symbol: {ticker}, Quantity: {quantity}")
                print(f"    Created: {created}")
                print(f"    Updated: {updated}")
            
            # Check which accounts have activations
            activated_account_ids = [act[1] for act in existing_activations]
            
        else:
            print("No existing activations found")
            activated_account_ids = []
            active_activations = []
        
        # Step 5: Identify accounts without activations
        print(f"\n5. ACTIVATION OPPORTUNITIES:")
        print("-" * 60)
        
        unactivated_accounts = []
        for account in active_accounts:
            account_id = account[0]
            if account_id not in activated_account_ids:
                unactivated_accounts.append(account)
        
        if unactivated_accounts:
            print(f"Active accounts WITHOUT stddev_breakout activation:")
            for i, account in enumerate(unactivated_accounts, 1):
                account_id, broker_id, _, _ = account
                print(f"  [{i}] {account_id} ({broker_id})")
        else:
            print("All active accounts already have activations")
        
        # Step 6: Recommendations
        print(f"\n6. RECOMMENDATIONS:")
        print("-" * 60)
        
        if len(active_activations) > 0:
            print(f"+ User 144 has {len(active_activations)} ACTIVE subscription(s)")
            for act in active_activations:
                print(f"  - Account {act[1]} is receiving signals")
        
        if unactivated_accounts:
            print(f"\n+ {len(unactivated_accounts)} active account(s) could be activated:")
            for account in unactivated_accounts:
                print(f"  - Account {account[0]} ({account[1]})")
            
            print(f"\n7. CREATE ADDITIONAL ACTIVATIONS:")
            print("-" * 60)
            print("Creating activations for ALL unactivated accounts...")
            
            for account in unactivated_accounts:
                account_id = account[0]
                broker_id = account[1]
                
                try:
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
                        USER_ID,           # user_id
                        'single',          # strategy_type
                        'engine',          # execution_type
                        strategy_id,       # strategy_code_id
                        'MNQ',             # ticker
                        1,                 # quantity
                        account_id,        # account_id
                        True,              # is_active
                        datetime.utcnow(),
                        3,                 # max_position_size
                        1.0,               # stop_loss_percent
                        2.0                # take_profit_percent
                    ))
                    
                    new_id = cursor.fetchone()[0]
                    print(f"  + Created activation ID {new_id} for account {account_id}")
                    
                except Exception as e:
                    print(f"  ERROR creating activation for {account_id}: {e}")
            
            conn.commit()
            print("\nAll activations created successfully!")
        
        # Step 7: Final summary
        print(f"\n8. FINAL SUMMARY:")
        print("-" * 60)
        
        cursor.execute("""
            SELECT 
                ast.id,
                ast.account_id,
                ba.broker_id,
                ast.ticker,
                ast.quantity,
                ast.is_active
            FROM activated_strategies ast
            JOIN broker_accounts ba ON ast.account_id = ba.account_id
            WHERE ast.strategy_code_id = %s 
                AND ast.user_id = %s 
                AND ast.is_active = true
            ORDER BY ast.created_at DESC
        """, (strategy_id, USER_ID))
        
        final_active = cursor.fetchall()
        
        print(f"User 144 now has {len(final_active)} ACTIVE subscription(s):")
        for activation in final_active:
            act_id, account_id, broker, ticker, qty, _ = activation
            print(f"  - ID {act_id}: Account {account_id} ({broker}), {ticker} x{qty}")
        
        print(f"\n[COMPLETE]")
        print(f"User 144 is set up with stddev_breakout on {len(final_active)} account(s)")
        print(f"Restart Strategy Engine to activate all subscriptions")
        
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