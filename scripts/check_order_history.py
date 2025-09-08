#!/usr/bin/env python
"""Check order history for user 39."""
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

database_url = os.getenv("DEV_DATABASE_URL") or os.getenv("DATABASE_PRIVATE_URL") or os.getenv("DATABASE_URL")
conn = psycopg2.connect(database_url)
cursor = conn.cursor()

print("\nORDER HISTORY FOR ACCOUNT 21610093:")
print("=" * 80)

# Check orders table
cursor.execute("""
    SELECT 
        o.id,
        o.broker_order_id,
        o.symbol,
        o.quantity,
        o.filled_quantity,
        o.status,
        o.order_type,
        o.created_at
    FROM orders o
    WHERE o.account_id = '21610093'
    ORDER BY o.created_at DESC
    LIMIT 20
""")

orders = cursor.fetchall()

if orders:
    print(f"Found {len(orders)} recent orders:")
    for order in orders:
        print(f"\nOrder ID: {order[1]}")
        print(f"  Symbol: {order[2]}")
        print(f"  Requested: {order[3]} contracts")
        print(f"  Filled: {order[4]} contracts")
        print(f"  Status: {order[5]}")
        print(f"  Type: {order[6]}")
        print(f"  Created: {order[7]}")
else:
    print("No orders found for account 21610093")

# Check if demo accounts have any special limits
print("\n" + "=" * 80)
print("ALL DEMO ACCOUNTS WITH STDDEV STRATEGIES:")
print("=" * 80)

cursor.execute("""
    SELECT DISTINCT
        ba.account_id,
        ba.name,
        ast.quantity,
        ast.user_id,
        u.username
    FROM broker_accounts ba
    JOIN activated_strategies ast ON ba.account_id = ast.account_id
    JOIN users u ON ast.user_id = u.id
    WHERE ba.environment = 'demo'
      AND ast.is_active = true
    ORDER BY ast.quantity DESC
""")

demo_accounts = cursor.fetchall()

if demo_accounts:
    print(f"Found {len(demo_accounts)} demo accounts with active strategies:")
    for acc in demo_accounts:
        print(f"  Account {acc[0]} ({acc[1]}): {acc[2]} contracts - User {acc[3]} ({acc[4]})")
else:
    print("No demo accounts with active strategies")

cursor.close()
conn.close()
