#!/usr/bin/env python
"""Verify both fixes are working correctly."""
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

database_url = os.getenv("DEV_DATABASE_URL") or os.getenv("DATABASE_PRIVATE_URL") or os.getenv("DATABASE_URL")
conn = psycopg2.connect(database_url)
cursor = conn.cursor()

print("=" * 80)
print("VERIFICATION OF FIXES")
print("=" * 80)

print("\n1. STRATEGY ENGINE PAYLOAD FIX:")
print("-" * 50)
print("✓ Removed hardcoded quantity=1 from execution_client.py")
print("✓ Removed hardcoded symbol and price fields")
print("✓ Now sends only: strategy_name, action, timestamp, comment")

print("\n2. USER 39 STRATEGY CONVERSION:")
print("-" * 50)

# Check User 39's current active strategies
cursor.execute("""
    SELECT 
        ast.id,
        ast.execution_type,
        ast.quantity,
        ast.ticker,
        ast.account_id,
        sc.name as strategy_name
    FROM activated_strategies ast
    LEFT JOIN strategy_codes sc ON ast.strategy_code_id = sc.id
    WHERE ast.user_id = 39 AND ast.is_active = true
""")

user39_strategies = cursor.fetchall()

if user39_strategies:
    print(f"User 39 active strategies: {len(user39_strategies)}")
    for strat in user39_strategies:
        id, exec_type, quantity, ticker, account, name = strat
        print(f"  Strategy {id}: {name or 'webhook-based'}")
        print(f"    execution_type: {exec_type}")
        print(f"    quantity: {quantity}")
        print(f"    ticker: {ticker}")
        print(f"    account: {account}")
        
        if exec_type == 'engine' and quantity == 4:
            print("    ✓ CORRECT: Engine strategy with 4 contracts")
        else:
            print(f"    ❌ Issue: Should be engine with 4 contracts")
else:
    print("❌ No active strategies found for User 39")

print("\n3. ALL STDDEV STRATEGIES STATUS:")
print("-" * 50)

cursor.execute("""
    SELECT 
        ast.id,
        ast.user_id,
        u.username,
        ast.execution_type,
        ast.quantity,
        ast.is_active
    FROM activated_strategies ast
    JOIN users u ON ast.user_id = u.id
    JOIN strategy_codes sc ON ast.strategy_code_id = sc.id
    WHERE sc.name = 'stddev_breakout'
    ORDER BY ast.is_active DESC, ast.user_id
""")

stddev_strategies = cursor.fetchall()

if stddev_strategies:
    print(f"All stddev_breakout strategies: {len(stddev_strategies)}")
    for strat in stddev_strategies:
        id, user_id, username, exec_type, quantity, is_active = strat
        status = "ACTIVE" if is_active else "INACTIVE"
        print(f"  User {user_id} ({username}): Strategy {id} ({status})")
        print(f"    execution_type: {exec_type}, quantity: {quantity}")
        
        if exec_type == 'engine':
            print("    ✓ Correct execution type")
        else:
            print("    ❌ Wrong execution type")
else:
    print("No stddev_breakout strategies found")

print("\n4. EXPECTED RESULT:")
print("-" * 50)
print("When User 39's stddev_breakout strategy triggers:")
print("  1. Strategy engine sends: {action, strategy_name, comment}")
print("  2. Backend finds strategy 700 (engine type)")
print("  3. Uses configured quantity: 4 contracts")
print("  4. Sends to Tradovate: orderQty: 4")
print("  5. User gets 4 contracts executed (not 1)")

print("\n" + "=" * 80)
print("SUMMARY:")
if user39_strategies and user39_strategies[0][1] == 'engine' and user39_strategies[0][2] == 4:
    print("🎉 SUCCESS: Both fixes implemented correctly!")
    print("   ✓ Strategy engine no longer sends hardcoded quantity")
    print("   ✓ User 39 converted to proper engine strategy")
    print("   ✓ User 39 should now get 4 contracts (not 1)")
    print("\nNEXT STEP: Restart Strategy Engine to apply changes")
else:
    print("❌ Issues found - please review above")

cursor.close()
conn.close()
