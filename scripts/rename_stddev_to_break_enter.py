#!/usr/bin/env python3
"""
Rename existing stddev_breakout strategy to break_and_enter.
This is the simpler approach that avoids creating a new database entry.
"""

import os
import psycopg2
from datetime import datetime
import json

# Database URL from environment
DATABASE_URL = os.environ.get('DATABASE_PRIVATE_URL')
if not DATABASE_URL:
    print("ERROR: DATABASE_PRIVATE_URL environment variable not set")
    print("Please set it to your PostgreSQL connection string")
    exit(1)

# Strategy details
OLD_NAME = 'stddev_breakout'
NEW_NAME = 'break_and_enter'
WEBHOOK_ID = 117  # The existing Break N Enter webhook


def rename_strategy():
    """Rename stddev_breakout strategy to break_and_enter."""
    
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    
    try:
        print("=" * 60)
        print("RENAMING STRATEGY: stddev_breakout -> break_and_enter")
        print("=" * 60)
        
        # 1. Check if stddev_breakout exists
        cursor.execute("""
            SELECT id, name, description, is_active, is_validated, user_id 
            FROM strategy_codes 
            WHERE name = %s
        """, (OLD_NAME,))
        
        existing = cursor.fetchone()
        if not existing:
            print(f"ERROR: Strategy '{OLD_NAME}' not found in database!")
            print("Please run add_stddev_strategy_simple.py first")
            return False
        
        strategy_id = existing[0]
        print(f"Found existing strategy:")
        print(f"  - ID: {strategy_id}")
        print(f"  - Name: {existing[1]}")
        print(f"  - Description: {existing[2]}")
        print(f"  - Active: {existing[3]}")
        print(f"  - Validated: {existing[4]}")
        print(f"  - User ID: {existing[5]}")
        
        # 2. Check if break_and_enter already exists
        cursor.execute("""
            SELECT id FROM strategy_codes WHERE name = %s
        """, (NEW_NAME,))
        
        if cursor.fetchone():
            print(f"ERROR: Strategy '{NEW_NAME}' already exists!")
            print("Cannot rename - target name is already taken")
            return False
        
        # 3. Get webhook details for context
        cursor.execute("""
            SELECT user_id, name, details, subscriber_count 
            FROM webhooks 
            WHERE id = %s
        """, (WEBHOOK_ID,))
        
        webhook = cursor.fetchone()
        if webhook:
            print(f"\nBreak N Enter Webhook (will be linked):")
            print(f"  - Creator User ID: {webhook[0]}")
            print(f"  - Name: {webhook[1]}")
            print(f"  - Subscriber Count: {webhook[3] or 0}")
        
        # 4. Update the strategy name and description
        new_description = 'Break N Enter - Standard Deviation Breakout Strategy (Engine-powered)'
        
        cursor.execute("""
            UPDATE strategy_codes
            SET 
                name = %s,
                description = %s,
                updated_at = %s
            WHERE id = %s
            RETURNING id, name, description
        """, (NEW_NAME, new_description, datetime.utcnow(), strategy_id))
        
        updated = cursor.fetchone()
        
        print(f"\n[SUCCESS] Strategy renamed successfully!")
        print(f"  - New ID: {updated[0]}")
        print(f"  - New Name: {updated[1]}")
        print(f"  - New Description: {updated[2]}")
        
        # 5. Check for existing activations that will be affected
        cursor.execute("""
            SELECT COUNT(*) as activation_count
            FROM activated_strategies
            WHERE strategy_code_id = %s
        """, (strategy_id,))
        
        activation_count = cursor.fetchone()[0]
        
        if activation_count > 0:
            print(f"\n[WARNING] {activation_count} existing activations found")
            print(f"These activations will now use the renamed strategy")
        else:
            print(f"\n[OK] No existing activations found")
        
        # 6. Show current subscriber count for Break N Enter
        cursor.execute("""
            SELECT COUNT(*) as subscriber_count
            FROM strategy_purchases
            WHERE webhook_id = %s
            AND status = 'COMPLETED'
        """, (WEBHOOK_ID,))
        
        subscriber_count = cursor.fetchone()[0]
        
        print(f"\nBreak N Enter Subscribers:")
        print(f"  - Active webhook subscribers: {subscriber_count}")
        print(f"  - These users can now activate the engine strategy")
        
        # Commit the changes
        conn.commit()
        
        print("\n" + "=" * 60)
        print("SUCCESS! Strategy renamed to break_and_enter")
        print("=" * 60)
        print("\nNext Steps:")
        print("1. Deploy strategy-engine with break_and_enter strategy")
        print("2. Test activation using BreakEnterActivationService")
        print("3. Verify signals route to correct users")
        print("4. Migrate existing Break N Enter activations")
        
        return True
        
    except Exception as e:
        conn.rollback()
        print(f"\nERROR: Failed to rename strategy: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        cursor.close()
        conn.close()


def verify_rename():
    """Verify the rename was successful."""
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    
    try:
        print("\n" + "=" * 40)
        print("VERIFICATION")
        print("=" * 40)
        
        # Check new name exists
        cursor.execute("""
            SELECT id, name, description, is_active, is_validated 
            FROM strategy_codes 
            WHERE name = %s
        """, (NEW_NAME,))
        
        new_strategy = cursor.fetchone()
        if new_strategy:
            print(f"[OK] '{NEW_NAME}' found:")
            print(f"   ID: {new_strategy[0]}")
            print(f"   Active: {new_strategy[3]}")
            print(f"   Validated: {new_strategy[4]}")
        else:
            print(f"[ERROR] '{NEW_NAME}' not found!")
            return False
        
        # Check old name is gone
        cursor.execute("""
            SELECT id FROM strategy_codes WHERE name = %s
        """, (OLD_NAME,))
        
        if cursor.fetchone():
            print(f"[ERROR] '{OLD_NAME}' still exists!")
            return False
        else:
            print(f"[OK] '{OLD_NAME}' successfully removed")
        
        return True
        
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    success = rename_strategy()
    if success:
        verify_success = verify_rename()
        if verify_success:
            print("\n[SUCCESS] Rename completed successfully!")
            print("Ready for Break N Enter engine deployment!")
        else:
            print("\n[WARNING] Rename completed but verification failed")
    else:
        print("\n[ERROR] Rename failed")
        exit(1)