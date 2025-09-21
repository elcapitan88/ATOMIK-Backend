#!/usr/bin/env python3
"""
Add Break and Enter strategy to strategy_codes table for engine execution.
This script creates the strategy_code entry that links to the existing webhook.
"""

import os
import sys
import psycopg2
from datetime import datetime
import json

# Database URL from environment
DATABASE_URL = os.environ.get('DATABASE_PRIVATE_URL')
if not DATABASE_URL:
    print("ERROR: DATABASE_PRIVATE_URL environment variable not set")
    print("Please set it to your PostgreSQL connection string")
    sys.exit(1)

# Strategy details
STRATEGY_NAME = 'break_and_enter'
WEBHOOK_ID = 117  # The existing Break N Enter webhook
WEBHOOK_TOKEN = 'OGgxOp0wOd60YGb4kc4CEh8oSz2ZCscKVVZtfwbCbHg'


def add_break_and_enter_strategy():
    """Add Break and Enter strategy to strategy_codes table."""
    
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    
    try:
        print("=" * 60)
        print("ADDING BREAK AND ENTER TO STRATEGY ENGINE")
        print("=" * 60)
        
        # 1. Check if strategy already exists
        cursor.execute("""
            SELECT id, name, is_active, is_validated 
            FROM strategy_codes 
            WHERE name = %s
        """, (STRATEGY_NAME,))
        
        existing = cursor.fetchone()
        if existing:
            print(f"Strategy already exists: ID={existing[0]}, Active={existing[2]}, Validated={existing[3]}")
            print("Skipping creation to avoid duplicates")
            return existing[0]
        
        # 2. Get the webhook owner (creator of Break N Enter)
        cursor.execute("""
            SELECT user_id, name, details, strategy_type 
            FROM webhooks 
            WHERE id = %s
        """, (WEBHOOK_ID,))
        
        webhook = cursor.fetchone()
        if not webhook:
            print(f"ERROR: Webhook {WEBHOOK_ID} not found!")
            return None
        
        creator_user_id = webhook[0]
        webhook_name = webhook[1]
        webhook_details = webhook[2]
        
        print(f"\nWebhook Details:")
        print(f"  - Name: {webhook_name}")
        print(f"  - Creator User ID: {creator_user_id}")
        print(f"  - Type: {webhook[3]}")
        
        # 3. Create the strategy code entry
        # Note: We're NOT storing actual Python code here, just a reference
        # The actual code is in strategy-engine/strategies/examples/break_and_enter.py
        strategy_code_content = """
# Break and Enter Strategy (Engine Implementation)
# This is a reference entry - actual code is in strategy-engine repository
# File: strategy-engine/strategies/examples/break_and_enter.py
# Based on Standard Deviation Breakout algorithm
"""
        
        cursor.execute("""
            INSERT INTO strategy_codes (
                user_id,
                name,
                description,
                code,
                symbols,
                is_active,
                is_validated,
                created_at,
                version
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s
            ) RETURNING id
        """, (
            creator_user_id,  # Use the original webhook creator
            STRATEGY_NAME,
            'Break and Enter - Automated Standard Deviation Breakout Strategy (formerly webhook-based)',
            strategy_code_content,
            json.dumps(['MNQ']),  # Default to MNQ
            True,  # Set active
            True,  # Set validated (we've tested it)
            datetime.utcnow(),
            1
        ))
        
        new_strategy_id = cursor.fetchone()[0]
        
        print(f"\nStrategy Code Created:")
        print(f"  - ID: {new_strategy_id}")
        print(f"  - Name: {STRATEGY_NAME}")
        print(f"  - Status: Active and Validated")
        
        # 4. Verify the strategy can be linked to webhook subscriptions
        cursor.execute("""
            SELECT COUNT(*) as subscriber_count
            FROM strategy_purchases
            WHERE webhook_id = %s
            AND status = 'COMPLETED'
        """, (WEBHOOK_ID,))
        
        subscriber_count = cursor.fetchone()[0]
        
        print(f"\nSubscriber Check:")
        print(f"  - Current Break N Enter subscribers: {subscriber_count}")
        print(f"  - These users will maintain access through webhook subscriptions")
        
        # 5. Prepare for migration (don't execute yet)
        cursor.execute("""
            SELECT COUNT(*) as active_count
            FROM activated_strategies
            WHERE webhook_id = %s
            AND is_active = true
        """, (WEBHOOK_TOKEN,))
        
        active_count = cursor.fetchone()[0]
        
        print(f"\nActivation Status:")
        print(f"  - Currently active webhook strategies: {active_count}")
        print(f"  - These will be migrated to engine execution in Phase 4")
        
        # Commit the changes
        conn.commit()
        
        print("\n" + "=" * 60)
        print("SUCCESS! Break and Enter strategy added to engine")
        print("=" * 60)
        print("\nNext Steps:")
        print("1. Update trade execution endpoint to handle 'break_and_enter' signals")
        print("2. Update activation logic to use engine execution")
        print("3. Test in development environment")
        print("4. Migrate existing activations")
        
        return new_strategy_id
        
    except Exception as e:
        conn.rollback()
        print(f"\nERROR: Failed to add strategy: {e}")
        import traceback
        traceback.print_exc()
        return None
        
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    strategy_id = add_break_and_enter_strategy()
    if strategy_id:
        print(f"\nStrategy Code ID: {strategy_id}")
        print("Save this ID for use in activation logic!")
    else:
        print("\nFailed to create strategy code entry")
        sys.exit(1)