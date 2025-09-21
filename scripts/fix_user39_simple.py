#!/usr/bin/env python
"""Convert User 39's webhook strategy to proper engine strategy - simple version."""
import os
import psycopg2
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

database_url = os.getenv("DEV_DATABASE_URL") or os.getenv("DATABASE_PRIVATE_URL") or os.getenv("DATABASE_URL")
conn = psycopg2.connect(database_url)
cursor = conn.cursor()

USER_ID = 39

print("Converting User 39 webhook strategy to engine strategy...")

try:
    # Get current webhook strategy (ID 694)
    cursor.execute("""
        SELECT id, quantity, account_id, ticker
        FROM activated_strategies 
        WHERE user_id = %s AND execution_type = 'webhook' AND is_active = true
    """, (USER_ID,))
    
    webhook_strat = cursor.fetchone()
    if not webhook_strat:
        print("No webhook strategy found for User 39")
    else:
        old_id, quantity, account_id, ticker = webhook_strat
        print(f"Found webhook strategy {old_id}: {ticker} x{quantity} on account {account_id}")
        
        # Get stddev_breakout strategy code
        cursor.execute("SELECT id FROM strategy_codes WHERE name = 'stddev_breakout'")
        code_id = cursor.fetchone()[0]
        print(f"Using strategy_code_id: {code_id}")
        
        # Deactivate old webhook strategy
        cursor.execute("""
            UPDATE activated_strategies 
            SET is_active = false, updated_at = %s 
            WHERE id = %s
        """, (datetime.utcnow(), old_id))
        print(f"Deactivated old webhook strategy {old_id}")
        
        # Create new engine strategy
        cursor.execute("""
            INSERT INTO activated_strategies (
                user_id, strategy_type, execution_type, strategy_code_id,
                ticker, quantity, account_id, is_active, created_at,
                max_position_size, stop_loss_percent, take_profit_percent
            ) VALUES (
                %s, 'single', 'engine', %s, %s, %s, %s, true, %s, 3, 1.0, 2.0
            ) RETURNING id
        """, (USER_ID, code_id, ticker, quantity, account_id, datetime.utcnow()))
        
        new_id = cursor.fetchone()[0]
        print(f"Created new engine strategy {new_id}")
        
        conn.commit()
        print(f"SUCCESS: User 39 converted from webhook to engine strategy")
        print(f"  Old: Strategy {old_id} (webhook) - DEACTIVATED")
        print(f"  New: Strategy {new_id} (engine) - ACTIVE")
        print(f"  Quantity: {quantity} contracts preserved")

except Exception as e:
    print(f"ERROR: {e}")
    conn.rollback()
finally:
    cursor.close()
    conn.close()
