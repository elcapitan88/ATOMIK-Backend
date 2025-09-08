#!/usr/bin/env python
"""Check account details for user 39."""
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

database_url = os.getenv("DEV_DATABASE_URL") or os.getenv("DATABASE_PRIVATE_URL") or os.getenv("DATABASE_URL")
conn = psycopg2.connect(database_url)
cursor = conn.cursor()

print("\nUSER 39 ACCOUNT DETAILS:")
print("=" * 80)

# Check account 21610093 (user 39's account)
cursor.execute("""
    SELECT 
        ba.account_id,
        ba.broker_id,
        ba.name,
        ba.environment,
        ba.is_active,
        ba.status,
        ba.error_message,
        ba.created_at,
        ba.updated_at
    FROM broker_accounts ba
    WHERE ba.account_id = '21610093'
""")

account = cursor.fetchone()

if account:
    print(f"Account ID: {account[0]}")
    print(f"Broker: {account[1]}")
    print(f"Name: {account[2]}")
    print(f"Environment: {account[3]}")
    print(f"Active: {account[4]}")
    print(f"Status: {account[5]}")
    print(f"Error: {account[6]}")
    print(f"Created: {account[7]}")
    print(f"Updated: {account[8]}")
else:
    print("Account 21610093 not found")

# Check if there are any trade records
print("\n" + "=" * 80)
print("RECENT TRADES FOR USER 39:")
print("=" * 80)

cursor.execute("""
    SELECT 
        t.id,
        t.order_id,
        t.symbol,
        t.quantity,
        t.side,
        t.status,
        t.filled_quantity,
        t.remaining_quantity,
        t.created_at
    FROM trades t
    WHERE t.user_id = 39
    ORDER BY t.created_at DESC
    LIMIT 10
""")

trades = cursor.fetchall()

if trades:
    print(f"Found {len(trades)} recent trades:")
    for trade in trades:
        print(f"\nTrade ID: {trade[0]}")
        print(f"  Order ID: {trade[1]}")
        print(f"  Symbol: {trade[2]}")
        print(f"  Requested Qty: {trade[3]}")
        print(f"  Filled Qty: {trade[6]}")
        print(f"  Remaining: {trade[7]}")
        print(f"  Side: {trade[4]}")
        print(f"  Status: {trade[5]}")
        print(f"  Created: {trade[8]}")
else:
    print("No trades found for user 39")

cursor.close()
conn.close()
