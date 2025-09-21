#!/usr/bin/env python
"""Check ALL stddev_breakout strategy configurations system-wide."""
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

database_url = os.getenv("DEV_DATABASE_URL") or os.getenv("DATABASE_PRIVATE_URL") or os.getenv("DATABASE_URL")
conn = psycopg2.connect(database_url)
cursor = conn.cursor()

print("\n" + "=" * 80)
print("STDDEV_BREAKOUT STRATEGY - SYSTEM-WIDE CONFIGURATION ANALYSIS")
print("=" * 80)

# 1. Check strategy_codes table for stddev_breakout
print("\n1. STRATEGY CODES:")
print("-" * 60)

cursor.execute("""
    SELECT id, name, user_id, is_active, created_at, updated_at
    FROM strategy_codes 
    WHERE name ILIKE '%stddev%' OR name ILIKE '%deviation%'
    ORDER BY name
""")

strategy_codes = cursor.fetchall()

if strategy_codes:
    print(f"Found {len(strategy_codes)} stddev strategy code(s):")
    for code in strategy_codes:
        id, name, user_id, is_active, created, updated = code
        print(f"\n  Strategy Code ID: {id}")
        print(f"    Name: {name}")
        print(f"    Owner: User {user_id}")
        print(f"    Active: {is_active}")
        print(f"    Created: {created}")
        print(f"    Updated: {updated}")
else:
    print("No stddev strategy codes found")

# 2. Check ALL activated_strategies for stddev_breakout
print("\n\n2. ALL STDDEV STRATEGY ACTIVATIONS:")
print("-" * 60)

cursor.execute("""
    SELECT 
        ast.id,
        ast.user_id,
        u.username,
        ast.strategy_type,
        ast.execution_type,
        ast.ticker,
        ast.quantity,
        ast.account_id,
        ba.name as account_name,
        ba.environment,
        ast.is_active,
        ast.webhook_id,
        ast.strategy_code_id,
        ast.created_at,
        ast.updated_at
    FROM activated_strategies ast
    LEFT JOIN users u ON ast.user_id = u.id
    LEFT JOIN broker_accounts ba ON ast.account_id = ba.account_id
    LEFT JOIN strategy_codes sc ON ast.strategy_code_id = sc.id
    WHERE sc.name ILIKE '%stddev%' OR sc.name ILIKE '%deviation%'
    ORDER BY ast.is_active DESC, ast.user_id
""")

activations = cursor.fetchall()

if activations:
    print(f"Found {len(activations)} stddev activation(s):")
    for act in activations:
        (id, user_id, username, strat_type, exec_type, ticker, quantity, 
         account_id, account_name, env, is_active, webhook_id, code_id, 
         created, updated) = act
        
        status = "ACTIVE" if is_active else "INACTIVE"
        
        print(f"\n  Activation ID: {id} ({status})")
        print(f"    User: {user_id} ({username})")
        print(f"    Strategy Type: {strat_type}")
        print(f"    EXECUTION TYPE: {exec_type}")  # This is key!
        print(f"    Ticker: {ticker}")
        print(f"    Quantity: {quantity}")
        print(f"    Account: {account_id} ({account_name} - {env})")
        if webhook_id:
            print(f"    Webhook ID: {webhook_id[:20]}...")
        print(f"    Strategy Code ID: {code_id}")
        print(f"    Created: {created}")
        print(f"    Updated: {updated}")
else:
    print("No stddev activations found")

# 3. Check webhooks with "stddev" in name or strategy_engine source
print("\n\n3. WEBHOOKS RELATED TO STDDEV:")
print("-" * 60)

cursor.execute("""
    SELECT 
        w.id,
        w.token,
        w.name,
        w.source_type,
        w.is_active,
        w.created_at,
        COUNT(ast.id) as activation_count
    FROM webhooks w
    LEFT JOIN activated_strategies ast ON ast.webhook_id = w.token
    WHERE w.name ILIKE '%stddev%' 
       OR w.name ILIKE '%deviation%'
       OR w.source_type = 'strategy_engine'
    GROUP BY w.id, w.token, w.name, w.source_type, w.is_active, w.created_at
    ORDER BY w.is_active DESC, activation_count DESC
""")

webhooks = cursor.fetchall()

if webhooks:
    print(f"Found {len(webhooks)} related webhook(s):")
    for webhook in webhooks:
        id, token, name, source, is_active, created, count = webhook
        status = "ACTIVE" if is_active else "INACTIVE"
        print(f"\n  Webhook ID: {id} ({status})")
        print(f"    Name: {name}")
        print(f"    Token: {token[:20]}...")
        print(f"    Source Type: {source}")
        print(f"    Used by {count} activation(s)")
        print(f"    Created: {created}")
else:
    print("No related webhooks found")

# 4. Summary and recommendations
print("\n\n4. ANALYSIS & RECOMMENDATIONS:")
print("-" * 60)

wrong_execution_types = [act for act in activations if act[4] != 'engine']  # execution_type != 'engine'

if wrong_execution_types:
    print(f"\n⚠️  ISSUE FOUND: {len(wrong_execution_types)} stddev activation(s) with WRONG execution type:")
    for act in wrong_execution_types:
        print(f"    - Activation {act[0]} (User {act[1]}): execution_type='{act[4]}' should be 'engine'")
    
    print(f"\n📋 REQUIRED ACTIONS:")
    print(f"    1. Convert ALL stddev activations to execution_type='engine'")
    print(f"    2. Remove any webhook_id references from stddev activations")
    print(f"    3. Ensure all stddev strategies use strategy engine processing")
else:
    print(f"\n✅ All stddev activations have correct execution_type='engine'")

engine_activations = [act for act in activations if act[4] == 'engine']
webhook_activations = [act for act in activations if act[4] == 'webhook']

print(f"\nCurrent Status:")
print(f"  - Engine activations: {len(engine_activations)}")
print(f"  - Webhook activations: {len(webhook_activations)}")
print(f"  - Total activations: {len(activations)}")

cursor.close()
conn.close()
