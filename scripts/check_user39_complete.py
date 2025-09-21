#!/usr/bin/env python
"""Complete check of User 39's strategies and accounts."""
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

database_url = os.getenv("DEV_DATABASE_URL") or os.getenv("DATABASE_PRIVATE_URL") or os.getenv("DATABASE_URL")
conn = psycopg2.connect(database_url)
cursor = conn.cursor()

USER_ID = 39

print("\n" + "=" * 80)
print("USER 39 - COMPLETE ACCOUNT AND STRATEGY ANALYSIS")
print("=" * 80)

# 1. Get all broker accounts for user 39
print("\n1. ALL BROKER ACCOUNTS FOR USER 39:")
print("-" * 60)

cursor.execute("""
    SELECT 
        account_id,
        broker_id,
        name,
        environment,
        is_active,
        status,
        created_at,
        updated_at
    FROM broker_accounts
    WHERE user_id = %s
    ORDER BY is_active DESC, updated_at DESC
""", (USER_ID,))

accounts = cursor.fetchall()

if accounts:
    print(f"Found {len(accounts)} broker account(s):")
    for acc in accounts:
        account_id, broker, name, env, is_active, status, created, updated = acc
        active_status = "ACTIVE" if is_active else "INACTIVE"
        print(f"\n  Account ID: {account_id}")
        print(f"    Broker: {broker}")
        print(f"    Name: {name}")
        print(f"    Environment: {env}")
        print(f"    Status: {status} ({active_status})")
        print(f"    Created: {created}")
        print(f"    Updated: {updated}")
else:
    print("No broker accounts found")

# 2. Get ALL activated strategies for user 39 (both webhook and engine)
print("\n\n2. ALL ACTIVATED STRATEGIES FOR USER 39:")
print("-" * 60)

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
        sc.name as strategy_code_name,
        w.name as webhook_name,
        ast.created_at,
        ast.updated_at,
        ba.name as account_name,
        ba.environment as account_env
    FROM activated_strategies ast
    LEFT JOIN strategy_codes sc ON ast.strategy_code_id = sc.id
    LEFT JOIN webhooks w ON ast.webhook_id = w.token
    LEFT JOIN broker_accounts ba ON ast.account_id = ba.account_id
    WHERE ast.user_id = %s
    ORDER BY ast.is_active DESC, ast.updated_at DESC
""", (USER_ID,))

strategies = cursor.fetchall()

if strategies:
    print(f"Found {len(strategies)} activated strategy(ies):")
    for strat in strategies:
        (strat_id, strat_type, exec_type, ticker, quantity, account_id, is_active, 
         webhook_id, code_id, code_name, webhook_name, created, updated, 
         account_name, account_env) = strat
        
        active_status = "ACTIVE" if is_active else "INACTIVE"
        
        print(f"\n  Strategy ID: {strat_id} ({active_status})")
        print(f"    Type: {strat_type} / {exec_type}")
        print(f"    Ticker: {ticker}")
        print(f"    QUANTITY: {quantity} contracts")
        print(f"    Account: {account_id} ({account_name} - {account_env})")
        
        if webhook_id:
            print(f"    Webhook: {webhook_name or 'Unnamed'} (ID: {webhook_id[:20]}...)")
        if code_id:
            print(f"    Strategy Code: {code_name} (ID: {code_id})")
        
        print(f"    Created: {created}")
        print(f"    Updated: {updated}")
else:
    print("No activated strategies found")

# 3. Check webhook details if there are webhook strategies
print("\n\n3. WEBHOOK DETAILS FOR USER 39:")
print("-" * 60)

cursor.execute("""
    SELECT DISTINCT
        w.token,
        w.name,
        w.source_type,
        w.is_active,
        w.created_at
    FROM webhooks w
    JOIN activated_strategies ast ON ast.webhook_id = w.token
    WHERE ast.user_id = %s
""", (USER_ID,))

webhooks = cursor.fetchall()

if webhooks:
    print(f"Found {len(webhooks)} webhook(s) used by strategies:")
    for webhook in webhooks:
        token, name, source, is_active, created = webhook
        active_status = "ACTIVE" if is_active else "INACTIVE"
        print(f"\n  Webhook: {name or 'Unnamed'}")
        print(f"    Token: {token[:30]}...")
        print(f"    Source: {source}")
        print(f"    Status: {active_status}")
        print(f"    Created: {created}")
else:
    print("No webhooks found for user 39's strategies")

# 4. Summary
print("\n\n4. SUMMARY:")
print("-" * 60)

active_strategies = [s for s in strategies if s[6]]  # is_active is index 6
active_accounts = [a for a in accounts if a[4]]  # is_active is index 4

print(f"Total Accounts: {len(accounts)} ({len(active_accounts)} active)")
print(f"Total Strategies: {len(strategies)} ({len(active_strategies)} active)")

if active_strategies:
    print("\nACTIVE STRATEGIES:")
    for strat in active_strategies:
        strat_id, _, _, ticker, quantity, account_id, _, _, _, _, _, _, _, account_name, _ = strat
        print(f"  - Strategy {strat_id}: {ticker} x{quantity} on account {account_id} ({account_name})")

cursor.close()
conn.close()
