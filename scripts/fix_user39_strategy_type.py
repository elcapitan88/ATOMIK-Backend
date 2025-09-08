#!/usr/bin/env python
"""
Convert User 39's webhook strategy to proper engine strategy.
"""
import os
import psycopg2
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

def main():
    """Convert User 39's webhook strategy to proper engine strategy."""
    
    database_url = os.getenv("DEV_DATABASE_URL") or os.getenv("DATABASE_PRIVATE_URL") or os.getenv("DATABASE_URL")
    
    if not database_url:
        print("ERROR: No database URL found in environment variables")
        return
    
    print("=" * 80)
    print("CONVERTING USER 39 WEBHOOK STRATEGY TO ENGINE STRATEGY")
    print("=" * 80)
    
    conn = psycopg2.connect(database_url)
    cursor = conn.cursor()
    
    try:
        USER_ID = 39
        
        # Step 1: Verify current state
        print("\n1. CURRENT STATE ANALYSIS:")
        print("-" * 60)
        
        # Check User 39's current strategies
        cursor.execute("""
            SELECT 
                ast.id,
                ast.strategy_type,
                ast.execution_type,
                ast.ticker,
                ast.quantity,
                ast.account_id,
                ast.is_active,
                ast.webhook_id,
                ast.strategy_code_id,
                ba.name as account_name,
                ba.environment,
                w.name as webhook_name
            FROM activated_strategies ast
            LEFT JOIN broker_accounts ba ON ast.account_id = ba.account_id
            LEFT JOIN webhooks w ON ast.webhook_id = w.token
            WHERE ast.user_id = %s
        """, (USER_ID,))
        
        current_strategies = cursor.fetchall()
        
        print(f"Found {len(current_strategies)} strategy(ies) for User {USER_ID}:")
        
        webhook_strategy = None
        for strat in current_strategies:
            (id, strat_type, exec_type, ticker, quantity, account_id, 
             is_active, webhook_id, code_id, account_name, env, webhook_name) = strat
            
            status = "ACTIVE" if is_active else "INACTIVE"
            print(f"\n  Strategy ID: {id} ({status})")
            print(f"    Type: {strat_type} / {exec_type}")
            print(f"    Ticker: {ticker}, Quantity: {quantity}")
            print(f"    Account: {account_id} ({account_name} - {env})")
            if webhook_id:
                print(f"    Webhook: {webhook_name}")
                if exec_type == 'webhook' and is_active:
                    webhook_strategy = strat
        
        if not webhook_strategy:
            print("\nNo active webhook strategy found for User 39 - nothing to convert")
            return
        
        print(f"\n⚠️  FOUND WEBHOOK STRATEGY TO CONVERT:")
        print(f"    Strategy ID: {webhook_strategy[0]}")
        print(f"    Should be: execution_type='engine' instead of 'webhook'")
        
        # Step 2: Get stddev_breakout strategy code
        cursor.execute("""
            SELECT id, name, user_id, is_active
            FROM strategy_codes 
            WHERE name = 'stddev_breakout'
        """)
        
        stddev_code = cursor.fetchone()
        
        if not stddev_code:
            print("\nERROR: stddev_breakout strategy code not found")
            return
        
        code_id, code_name, code_owner, code_active = stddev_code
        print(f"\n📋 STDDEV_BREAKOUT STRATEGY CODE:")
        print(f"    ID: {code_id}")
        print(f"    Name: {code_name}")
        print(f"    Owner: User {code_owner}")
        print(f"    Active: {code_active}")
        
        # Step 3: Apply the fix
        print(f"\n2. APPLYING CONVERSION:")
        print("-" * 60)
        
        old_id, old_type, old_exec, old_ticker, old_quantity, old_account, old_active, old_webhook, old_code = webhook_strategy[:9]
        
        # Deactivate the old webhook strategy
        cursor.execute("""
            UPDATE activated_strategies 
            SET is_active = false, 
                updated_at = %s
            WHERE id = %s
        """, (datetime.utcnow(), old_id))
        
        print(f"✓ Deactivated old webhook strategy (ID: {old_id})")
        
        # Create new engine strategy
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
            'engine',          # execution_type - THIS IS THE KEY FIX
            code_id,           # strategy_code_id - Use stddev_breakout code
            old_ticker,        # ticker (keep same)
            old_quantity,      # quantity (keep same - should be 4)
            old_account,       # account_id (keep same)
            True,              # is_active
            datetime.utcnow(),
            3,                 # max_position_size
            1.0,               # stop_loss_percent
            2.0                # take_profit_percent
        ))
        
        new_strategy_id = cursor.fetchone()[0]
        print(f"✓ Created new engine strategy (ID: {new_strategy_id})")
        print(f"  - execution_type: 'engine' (was 'webhook')")
        print(f"  - strategy_code_id: {code_id} (stddev_breakout)")
        print(f"  - quantity: {old_quantity} (preserved)")
        print(f"  - account: {old_account} (preserved)")
        
        # Commit changes
        conn.commit()
        
        # Step 4: Verification
        print(f"\n3. VERIFICATION:")
        print("-" * 60)
        
        cursor.execute("""
            SELECT 
                ast.id,
                ast.execution_type,
                ast.quantity,
                ast.is_active,
                sc.name as strategy_name
            FROM activated_strategies ast
            JOIN strategy_codes sc ON ast.strategy_code_id = sc.id
            WHERE ast.user_id = %s AND ast.is_active = true
        """, (USER_ID,))
        
        active_strategies = cursor.fetchall()
        
        print(f"User {USER_ID} active strategies after conversion:")
        for strat in active_strategies:
            id, exec_type, quantity, is_active, strategy_name = strat
            print(f"  - Strategy ID {id}: {strategy_name}")
            print(f"    execution_type: {exec_type}")
            print(f"    quantity: {quantity}")
            print(f"    active: {is_active}")
        
        success = any(s[1] == 'engine' and s[4] == 'stddev_breakout' for s in active_strategies)
        
        if success:
            print(f"\n🎉 SUCCESS! User 39's strategy converted:")
            print(f"   ✓ Old webhook strategy deactivated")
            print(f"   ✓ New engine strategy created")
            print(f"   ✓ Will now use proper strategy engine processing")
            print(f"   ✓ Quantity {old_quantity} preserved")
            print(f"\n📋 NEXT STEPS:")
            print(f"   1. Restart Strategy Engine to pick up the new configuration")
            print(f"   2. User 39 will now get {old_quantity} contracts (not 1)")
            print(f"   3. No more webhook processing overhead")
        else:
            print(f"\n❌ VERIFICATION FAILED - Please check manually")
        
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
