#!/usr/bin/env python3
"""
Add Purple Reign engine strategy to strategy_codes table.
This will replace the webhook-based Purple Reign strategies.
"""

import os
import sys
import psycopg2
from datetime import datetime
import json

# Database connection (use provided connection string or environment variable)
DATABASE_URL = "postgresql://postgres:K2Q71c2OIVd1ZIXm8Ad1BFk5jF03Kj33@metro.proxy.rlwy.net:47089/railway"

# If you want to use environment variable instead, uncomment:
# DATABASE_URL = os.environ.get('DATABASE_PRIVATE_URL', DATABASE_URL)

# Strategy details
STRATEGY_NAME = 'Purple Reign'
CREATOR_USER_ID = 39  # User who created the original webhook strategies

# Webhook IDs to be replaced
OLD_NQ_WEBHOOK_ID = 6  # PurpleReign NQ/MNQ
OLD_ES_WEBHOOK_ID = 14  # PurpleReign MES/ES
OLD_NQ_TOKEN = 'dsALfSReTUl2yEChwak3jM45sLlpmqGErbYdglmJEqc'
OLD_ES_TOKEN = 'rgx_k7QJdaD99VFNkU5DXEtAA8G5dFaMx4DyJjfbmuE'


def add_purple_reign_strategy():
    """Add Purple Reign engine strategy to strategy_codes table."""

    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()

    try:
        print("=" * 60)
        print("ADDING PURPLE REIGN ENGINE STRATEGY")
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

            # Ask if we should update it
            response = input("\nDo you want to update the existing strategy? (y/n): ")
            if response.lower() != 'y':
                print("Skipping update")
                return existing[0]

            # Update existing strategy
            cursor.execute("""
                UPDATE strategy_codes
                SET
                    description = %s,
                    symbols = %s,
                    is_active = %s,
                    is_validated = %s,
                    updated_at = %s,
                    version = version + 1
                WHERE id = %s
                RETURNING id, version
            """, (
                'Purple Reign - TTM Squeeze & MACD momentum strategy with PSAR trailing stops',
                json.dumps(['NQ', 'MNQ', 'ES', 'MES']),
                True,
                True,
                datetime.utcnow(),
                existing[0]
            ))

            updated = cursor.fetchone()
            print(f"\nStrategy Updated:")
            print(f"  - ID: {updated[0]}")
            print(f"  - New Version: {updated[1]}")

            conn.commit()
            return updated[0]

        # 2. Check current webhook status
        print("\nChecking existing webhook strategies...")

        cursor.execute("""
            SELECT
                w.id,
                w.name,
                w.token,
                COUNT(DISTINCT ws.user_id) as subscribers,
                COUNT(DISTINCT as2.user_id) as active_users
            FROM webhooks w
            LEFT JOIN webhook_subscriptions ws ON w.id = ws.webhook_id
            LEFT JOIN activated_strategies as2 ON w.token::text = as2.webhook_id
                AND as2.is_active = true
            WHERE w.id IN (%s, %s)
            GROUP BY w.id, w.name, w.token
            ORDER BY w.id
        """, (OLD_NQ_WEBHOOK_ID, OLD_ES_WEBHOOK_ID))

        webhooks = cursor.fetchall()

        total_subscribers = 0
        total_active = 0

        print("\nExisting Webhook Strategies:")
        for webhook in webhooks:
            print(f"  - {webhook[1]}")
            print(f"    ID: {webhook[0]}, Token: {webhook[2]}")
            print(f"    Subscribers: {webhook[3]}, Active: {webhook[4]}")
            total_subscribers += webhook[3]
            total_active += webhook[4]

        print(f"\nTotal Impact: {total_subscribers} subscribers, {total_active} active users")

        # 3. Create the Purple Reign strategy code entry
        print("\nCreating Purple Reign engine strategy...")

        # Read the actual strategy code
        strategy_file_path = os.path.join(
            os.path.dirname(__file__),
            '..', '..', 'strategy-engine', 'strategies', 'purple_reign.py'
        )

        if os.path.exists(strategy_file_path):
            with open(strategy_file_path, 'r') as f:
                strategy_code_content = f.read()
            print(f"  - Loaded strategy code from {strategy_file_path}")
        else:
            # Fallback reference if file not found
            strategy_code_content = """
# Purple Reign Strategy (Engine Implementation)
# This is a reference entry - actual code is in strategy-engine repository
# File: strategy-engine/strategies/purple_reign.py
# TTM Squeeze + MACD momentum strategy with PSAR trailing stops
"""
            print("  - Using reference code (actual file not found)")

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
                updated_at,
                version
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            ) RETURNING id
        """, (
            CREATOR_USER_ID,
            STRATEGY_NAME,
            'Purple Reign - TTM Squeeze & MACD momentum strategy with PSAR trailing stops',
            strategy_code_content,
            json.dumps(['NQ', 'MNQ', 'ES', 'MES']),  # All symbols in one strategy
            True,  # Active
            True,  # Validated
            datetime.utcnow(),
            datetime.utcnow(),  # updated_at
            1
        ))

        new_strategy_id = cursor.fetchone()[0]

        print(f"\nStrategy Code Created:")
        print(f"  - ID: {new_strategy_id}")
        print(f"  - Name: {STRATEGY_NAME}")
        print(f"  - Symbols: NQ, MNQ, ES, MES")
        print(f"  - Status: Active and Validated")

        # 4. Prepare migration plan
        print("\n" + "=" * 60)
        print("MIGRATION PLAN")
        print("=" * 60)

        print("\nStep 1: This Weekend (Market Closed)")
        print("  1. Run this script to create engine strategy [DONE]")
        print("  2. Delete webhook strategies (IDs 6 and 14)")
        print("  3. Notify users via Discord to resubscribe")

        print("\nStep 2: User Actions Required")
        print("  - Subscribe to new 'Purple Reign' engine strategy")
        print("  - Activate with their preferred accounts")
        print("  - Choose their symbols (NQ/MNQ and/or ES/MES)")

        print("\nStep 3: Monday Market Open")
        print("  - Monitor for any issues")
        print("  - Support users with activation")

        # 5. Generate deletion SQL (don't execute yet)
        print("\n" + "=" * 60)
        print("WEBHOOK DELETION COMMANDS (DO NOT RUN YET)")
        print("=" * 60)
        print("\nWhen ready to delete webhooks, run these SQL commands:")
        print("```sql")
        print("-- Delete webhook subscriptions")
        print(f"DELETE FROM webhook_subscriptions WHERE webhook_id IN ({OLD_NQ_WEBHOOK_ID}, {OLD_ES_WEBHOOK_ID});")
        print("\n-- Delete activated strategies")
        print(f"DELETE FROM activated_strategies WHERE webhook_id IN ('{OLD_NQ_TOKEN}', '{OLD_ES_TOKEN}');")
        print("\n-- Delete the webhooks themselves")
        print(f"DELETE FROM webhooks WHERE id IN ({OLD_NQ_WEBHOOK_ID}, {OLD_ES_WEBHOOK_ID});")
        print("```")

        # Commit the changes
        conn.commit()

        print("\n" + "=" * 60)
        print("SUCCESS! Purple Reign engine strategy created")
        print("=" * 60)

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


def delete_webhook_strategies():
    """Delete the old webhook strategies - RUN THIS SEPARATELY WHEN READY."""

    print("\n" + "=" * 60)
    print("WARNING: DELETING WEBHOOK STRATEGIES")
    print("=" * 60)

    response = input("\nAre you SURE you want to delete the webhook strategies? (type 'yes' to confirm): ")
    if response.lower() != 'yes':
        print("Cancelled")
        return

    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()

    try:
        # Delete in correct order to avoid foreign key issues

        # 1. Delete webhook subscriptions
        cursor.execute("""
            DELETE FROM webhook_subscriptions
            WHERE webhook_id IN (%s, %s)
            RETURNING webhook_id
        """, (OLD_NQ_WEBHOOK_ID, OLD_ES_WEBHOOK_ID))

        deleted_subs = cursor.fetchall()
        print(f"Deleted {len(deleted_subs)} webhook subscriptions")

        # 2. Delete activated strategies
        cursor.execute("""
            DELETE FROM activated_strategies
            WHERE webhook_id IN (%s, %s)
            RETURNING id
        """, (OLD_NQ_TOKEN, OLD_ES_TOKEN))

        deleted_activations = cursor.fetchall()
        print(f"Deleted {len(deleted_activations)} activated strategies")

        # 3. Delete the webhooks
        cursor.execute("""
            DELETE FROM webhooks
            WHERE id IN (%s, %s)
            RETURNING id, name
        """, (OLD_NQ_WEBHOOK_ID, OLD_ES_WEBHOOK_ID))

        deleted_webhooks = cursor.fetchall()
        for webhook in deleted_webhooks:
            print(f"Deleted webhook: {webhook[1]} (ID: {webhook[0]})")

        conn.commit()
        print("\nWebhook strategies successfully deleted!")

    except Exception as e:
        conn.rollback()
        print(f"\nERROR: Failed to delete webhooks: {e}")

    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    print("Purple Reign Strategy Migration Tool")
    print("=" * 60)
    print("\nOptions:")
    print("1. Add Purple Reign engine strategy")
    print("2. Delete old webhook strategies (DANGER!)")
    print("3. Both (add engine, then delete webhooks)")

    choice = input("\nEnter your choice (1/2/3): ")

    if choice == '1':
        strategy_id = add_purple_reign_strategy()
        if strategy_id:
            print(f"\n[SUCCESS] Strategy Code ID: {strategy_id}")
            print("[SUCCESS] Purple Reign engine strategy is ready!")
            print("\nNext: Run option 2 when ready to delete webhooks")

    elif choice == '2':
        delete_webhook_strategies()

    elif choice == '3':
        strategy_id = add_purple_reign_strategy()
        if strategy_id:
            print("\n[SUCCESS] Engine strategy created")
            print("\nNow preparing to delete webhooks...")
            delete_webhook_strategies()

    else:
        print("Invalid choice")