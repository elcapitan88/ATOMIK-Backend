#!/usr/bin/env python
"""Check all stddev_breakout strategy activations and their quantities."""
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

database_url = os.getenv("DEV_DATABASE_URL") or os.getenv("DATABASE_PRIVATE_URL") or os.getenv("DATABASE_URL")
conn = psycopg2.connect(database_url)
cursor = conn.cursor()

print("\nALL STDDEV_BREAKOUT ACTIVATIONS:")
print("=" * 80)

cursor.execute("""
    SELECT 
        ast.id,
        ast.user_id,
        u.username,
        ast.account_id,
        ast.ticker,
        ast.quantity,
        ast.is_active,
        ast.created_at,
        ba.broker_id
    FROM activated_strategies ast
    JOIN users u ON ast.user_id = u.id
    LEFT JOIN broker_accounts ba ON ast.account_id = ba.account_id
    WHERE ast.strategy_code_id = (
        SELECT id FROM strategy_codes WHERE name = 'stddev_breakout'
    )
    ORDER BY ast.user_id, ast.is_active DESC
""")

activations = cursor.fetchall()

if activations:
    print(f"Found {len(activations)} activations:\n")
    for act in activations:
        id, user_id, username, account_id, ticker, quantity, is_active, created, broker = act
        status = "ACTIVE" if is_active else "INACTIVE"
        print(f"User {user_id} ({username}):")
        print(f"  Activation ID: {id}")
        print(f"  Account: {account_id} ({broker})")
        print(f"  Ticker: {ticker}")
        print(f"  QUANTITY: {quantity} contracts")
        print(f"  Status: {status}")
        print(f"  Created: {created}")
        print()
else:
    print("No stddev_breakout activations found")

# Also check if user 39 has ANY strategies
print("\n" + "=" * 80)
print("USER 39 STRATEGIES (ALL TYPES):")
print("=" * 80)

cursor.execute("""
    SELECT 
        ast.id,
        ast.strategy_type,
        ast.ticker,
        ast.quantity,
        ast.account_id,
        ast.is_active,
        ast.webhook_id,
        ast.strategy_code_id,
        sc.name as strategy_code_name
    FROM activated_strategies ast
    LEFT JOIN strategy_codes sc ON ast.strategy_code_id = sc.id
    WHERE ast.user_id = 39
""")

user39_strats = cursor.fetchall()

if user39_strats:
    print(f"Found {len(user39_strats)} strategies for User 39:")
    for strat in user39_strats:
        print(f"\nStrategy ID: {strat[0]}")
        print(f"  Type: {strat[1]}")
        print(f"  Ticker: {strat[2]}")
        print(f"  QUANTITY: {strat[3]}")
        print(f"  Account: {strat[4]}")
        print(f"  Active: {strat[5]}")
        print(f"  Webhook ID: {strat[6]}")
        print(f"  Strategy Code: {strat[8]} (ID: {strat[7]})")
else:
    print("User 39 has NO strategies configured")

cursor.close()
conn.close()
