#!/usr/bin/env python3
"""
Verify Purple Reign migration status.
Checks if StrategyCode exists and shows activated strategies.
"""

import os
import sys
import psycopg2
from datetime import datetime

# Database connection (same as add_purple_reign_strategy.py)
DATABASE_URL = "postgresql://postgres:K2Q71c2OIVd1ZIXm8Ad1BFk5jF03Kj33@metro.proxy.rlwy.net:47089/railway"


def verify_migration():
    """Check migration status for Purple Reign strategy."""

    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()

    try:
        print("=" * 70)
        print("PURPLE REIGN MIGRATION VERIFICATION")
        print("=" * 70)
        print(f"Timestamp: {datetime.utcnow().isoformat()}")
        print()

        # 1. Check StrategyCode table
        print("-" * 70)
        print("1. STRATEGY_CODES TABLE CHECK")
        print("-" * 70)

        cursor.execute("""
            SELECT id, name, user_id, is_active, is_validated, symbols,
                   created_at, updated_at, version, signals_generated
            FROM strategy_codes
            WHERE name ILIKE '%purple%' OR name ILIKE '%reign%'
            ORDER BY id
        """)

        strategy_codes = cursor.fetchall()

        if strategy_codes:
            print(f"Found {len(strategy_codes)} matching strategy code(s):\n")
            for sc in strategy_codes:
                print(f"  ID: {sc[0]}")
                print(f"  Name: '{sc[1]}'")
                print(f"  User ID: {sc[2]}")
                print(f"  Active: {sc[3]}")
                print(f"  Validated: {sc[4]}")
                print(f"  Symbols: {sc[5]}")
                print(f"  Created: {sc[6]}")
                print(f"  Updated: {sc[7]}")
                print(f"  Version: {sc[8]}")
                print(f"  Signals Generated: {sc[9]}")
                print()
        else:
            print("  [X] NO STRATEGY CODE FOUND for Purple Reign!")
            print("  -> You need to run: python add_purple_reign_strategy.py")
            print()

        # 2. Check for activated engine strategies
        print("-" * 70)
        print("2. ACTIVATED STRATEGIES (Engine-based)")
        print("-" * 70)

        cursor.execute("""
            SELECT
                as2.id,
                as2.user_id,
                as2.ticker,
                as2.quantity,
                as2.execution_type,
                as2.strategy_code_id,
                as2.is_active,
                as2.account_id,
                sc.name as strategy_name
            FROM activated_strategies as2
            LEFT JOIN strategy_codes sc ON as2.strategy_code_id = sc.id
            WHERE as2.execution_type = 'engine'
            AND as2.is_active = true
            ORDER BY as2.id
        """)

        engine_strategies = cursor.fetchall()

        if engine_strategies:
            print(f"Found {len(engine_strategies)} active engine-based strategy(ies):\n")
            for es in engine_strategies:
                print(f"  Strategy ID: {es[0]}")
                print(f"  User ID: {es[1]}")
                print(f"  Ticker: {es[2]}")
                print(f"  Quantity: {es[3]}")
                print(f"  Execution Type: {es[4]}")
                print(f"  Strategy Code ID: {es[5]}")
                print(f"  Active: {es[6]}")
                print(f"  Account ID: {es[7]}")
                print(f"  Strategy Name: {es[8]}")
                print()
        else:
            print("  [!] No active engine-based strategies found")
            print("  -> Users need to subscribe and activate the Purple Reign strategy")
            print()

        # 3. Check for old webhook strategies
        print("-" * 70)
        print("3. OLD WEBHOOK STRATEGIES (IDs 6 & 14)")
        print("-" * 70)

        cursor.execute("""
            SELECT id, name, token, user_id
            FROM webhooks
            WHERE id IN (6, 14)
            ORDER BY id
        """)

        old_webhooks = cursor.fetchall()

        if old_webhooks:
            print(f"[!] Found {len(old_webhooks)} old webhook(s) still present:\n")
            for wh in old_webhooks:
                print(f"  ID: {wh[0]}")
                print(f"  Name: {wh[1]}")
                print(f"  Token: {wh[2][:20]}..." if wh[2] else "  Token: None")
                print(f"  User ID: {wh[3]}")
                print()
            print("  -> Consider running delete_webhook_strategies() after migration is verified")
        else:
            print("  [OK] Old webhooks (IDs 6 & 14) have been deleted")
            print()

        # 4. Check activated strategies linked to old webhooks
        print("-" * 70)
        print("4. ACTIVATED STRATEGIES LINKED TO OLD WEBHOOKS")
        print("-" * 70)

        cursor.execute("""
            SELECT
                as2.id,
                as2.user_id,
                as2.ticker,
                as2.execution_type,
                as2.webhook_id,
                as2.is_active
            FROM activated_strategies as2
            WHERE as2.webhook_id IN (
                'dsALfSReTUl2yEChwak3jM45sLlpmqGErbYdglmJEqc',
                'rgx_k7QJdaD99VFNkU5DXEtAA8G5dFaMx4DyJjfbmuE'
            )
            AND as2.is_active = true
            ORDER BY as2.id
        """)

        webhook_strategies = cursor.fetchall()

        if webhook_strategies:
            print(f"[!] Found {len(webhook_strategies)} active strategies still using old webhooks:\n")
            for ws in webhook_strategies:
                print(f"  Strategy ID: {ws[0]}")
                print(f"  User ID: {ws[1]}")
                print(f"  Ticker: {ws[2]}")
                print(f"  Execution Type: {ws[3]}")
                print(f"  Webhook ID: {ws[4][:20]}...")
                print(f"  Active: {ws[5]}")
                print()
            print("  -> These users need to migrate to the new engine-based strategy")
        else:
            print("  [OK] No active strategies using old Purple Reign webhooks")
            print()

        # Summary
        print("=" * 70)
        print("SUMMARY")
        print("=" * 70)

        strategy_code_exists = len(strategy_codes) > 0
        engine_strategies_exist = len(engine_strategies) > 0
        old_webhooks_deleted = len(old_webhooks) == 0
        old_webhook_strategies_migrated = len(webhook_strategies) == 0

        # Check for name mismatch
        name_correct = False
        if strategy_codes:
            for sc in strategy_codes:
                if sc[1] == 'Purple Reign':
                    name_correct = True
                    break

        print(f"  StrategyCode exists:           {'[OK]' if strategy_code_exists else '[X]'}")
        print(f"  StrategyCode name correct:     {'[OK]' if name_correct else '[X]'} (should be 'Purple Reign')")
        print(f"  Engine strategies activated:   {'[OK]' if engine_strategies_exist else '[!] (users need to activate)'}")
        print(f"  Old webhooks deleted:          {'[OK]' if old_webhooks_deleted else '[!] (optional cleanup)'}")
        print(f"  Old webhook strategies migrated: {'[OK]' if old_webhook_strategies_migrated else '[!] (users need to migrate)'}")
        print()

        if not strategy_code_exists:
            print("[X] CRITICAL: Run add_purple_reign_strategy.py to create the strategy code")
        elif not name_correct:
            print("[X] CRITICAL: Strategy name is wrong. Run this SQL to fix:")
            print("   UPDATE strategy_codes SET name = 'Purple Reign' WHERE name = 'purple_reign';")
        elif engine_strategies_exist:
            print("[OK] Migration looks complete! Purple Reign engine strategy is ready.")
        else:
            print("[!] Strategy code exists but no users have activated it yet.")

        print()

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    verify_migration()
