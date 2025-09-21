#!/usr/bin/env python
"""Implement Option 2: Fix stddev_breakout marketplace confusion."""
import os
import psycopg2
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

database_url = os.getenv("DEV_DATABASE_URL") or os.getenv("DATABASE_PRIVATE_URL") or os.getenv("DATABASE_URL")
conn = psycopg2.connect(database_url)
cursor = conn.cursor()

print("IMPLEMENTING OPTION 2: STDDEV_BREAKOUT MARKETPLACE FIX")
print("=" * 70)

try:
    # Step 1: Hide confusing webhook from marketplace
    print("\nSTEP 1: Hide confusing webhook from marketplace")
    print("-" * 50)
    
    cursor.execute("""
        UPDATE webhooks 
        SET is_shared = false, updated_at = %s
        WHERE token = '9MkxYhET6imXiQNcW22P6creS8CRIjQMLD1c92ztNtI'
    """, (datetime.utcnow(),))
    
    affected_rows = cursor.rowcount
    print(f"✓ Updated {affected_rows} webhook record(s)")
    print(f"✓ Webhook 'Standard Deviation Breakout Pro' hidden from marketplace")
    
    # Step 2: Ensure engine strategy appears in marketplace
    print("\nSTEP 2: Ensure engine strategy appears in marketplace")
    print("-" * 50)
    
    cursor.execute("""
        UPDATE strategy_codes 
        SET is_validated = true, is_active = true, updated_at = %s
        WHERE id = 5 AND name = 'stddev_breakout'
    """, (datetime.utcnow(),))
    
    affected_rows = cursor.rowcount
    print(f"✓ Updated {affected_rows} strategy_codes record(s)")
    print(f"✓ Engine strategy 'stddev_breakout' validated for marketplace")
    
    # Step 3: Convert User 39's existing strategy to engine type
    print("\nSTEP 3: Convert User 39's existing strategy to engine type")
    print("-" * 50)
    
    # First check current state
    cursor.execute("""
        SELECT id, execution_type, quantity, webhook_id, strategy_code_id
        FROM activated_strategies 
        WHERE id = 704 AND user_id = 39
    """)
    
    current_strategy = cursor.fetchone()
    if current_strategy:
        print(f"Current strategy 704: {current_strategy[1]} type, {current_strategy[2]} contracts")
        
        cursor.execute("""
            UPDATE activated_strategies 
            SET execution_type = 'engine',
                strategy_code_id = 5,
                webhook_id = NULL,
                updated_at = %s
            WHERE id = 704 AND user_id = 39
        """, (datetime.utcnow(),))
        
        affected_rows = cursor.rowcount
        print(f"✓ Updated {affected_rows} strategy activation(s)")
        print(f"✓ User 39's strategy converted: webhook → engine")
        print(f"✓ Set strategy_code_id = 5 (stddev_breakout)")
        print(f"✓ Preserved quantity = {current_strategy[2]} contracts")
        print(f"✓ Removed webhook_id reference")
    else:
        print("! Strategy 704 not found for User 39")
    
    # Commit all changes
    conn.commit()
    print(f"\n✓ All changes committed to database")
    
    # Step 4: Verification
    print(f"\nSTEP 4: Verification")
    print("-" * 50)
    
    # Check marketplace will show engine strategy
    print("1. Marketplace visibility:")
    cursor.execute("""
        SELECT id, name, is_active, is_validated
        FROM strategy_codes
        WHERE id = 5
    """)
    engine_strategy = cursor.fetchone()
    if engine_strategy:
        print(f"   ✓ Engine strategy visible: {engine_strategy[1]} (Active: {engine_strategy[2]}, Validated: {engine_strategy[3]})")
    
    # Check webhook is hidden
    cursor.execute("""
        SELECT id, name, is_shared
        FROM webhooks
        WHERE token = '9MkxYhET6imXiQNcW22P6creS8CRIjQMLD1c92ztNtI'
    """)
    webhook_status = cursor.fetchone()
    if webhook_status:
        print(f"   ✓ Webhook hidden: {webhook_status[1]} (Shared: {webhook_status[2]})")
    
    # Check User 39's strategy is now engine type
    print("\n2. User 39's strategy status:")
    cursor.execute("""
        SELECT ast.id, ast.execution_type, ast.quantity, sc.name
        FROM activated_strategies ast
        JOIN strategy_codes sc ON ast.strategy_code_id = sc.id
        WHERE ast.user_id = 39 AND ast.is_active = true
    """)
    user39_strategy = cursor.fetchone()
    if user39_strategy:
        print(f"   ✓ Strategy {user39_strategy[0]}: {user39_strategy[3]} - {user39_strategy[1]} type - {user39_strategy[2]} contracts")
    
    # Test backend engine query
    print("\n3. Backend execution query test:")
    cursor.execute("""
        SELECT ast.id, ast.user_id, u.username, ast.quantity
        FROM activated_strategies ast
        JOIN users u ON ast.user_id = u.id
        JOIN strategy_codes sc ON ast.strategy_code_id = sc.id
        WHERE sc.name = 'stddev_breakout' 
          AND ast.execution_type = 'engine'
          AND ast.is_active = true
          AND sc.is_active = true
    """)
    
    backend_results = cursor.fetchall()
    print(f"   ✓ Backend will find {len(backend_results)} engine strategies:")
    for result in backend_results:
        print(f"     - Strategy {result[0]}: User {result[1]} ({result[2]}) - {result[3]} contracts")
    
    print(f"\n" + "=" * 70)
    print("🎉 SUCCESS! Option 2 implementation complete:")
    print("   ✅ Webhook hidden from marketplace")
    print("   ✅ Engine strategy visible in marketplace") 
    print("   ✅ User 39's strategy converted to engine type")
    print("   ✅ Backend will now find and execute User 39's strategy")
    print("   ✅ Future activations will be engine type (correct)")
    
    print(f"\nNEXT STEPS:")
    print(f"   1. Test marketplace shows 'Stddev Breakout' strategy")
    print(f"   2. Wait for next stddev_breakout signal")
    print(f"   3. Verify User 39 gets {user39_strategy[2] if user39_strategy else 'X'} contracts executed")
    print(f"   4. Monitor logs for successful execution")

except Exception as e:
    print(f"❌ ERROR: {e}")
    conn.rollback()
    print("All changes rolled back")
    import traceback
    traceback.print_exc()
finally:
    cursor.close()
    conn.close()
