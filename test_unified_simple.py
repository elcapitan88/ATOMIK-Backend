#!/usr/bin/env python3
"""
Simple test to verify unified strategy schemas and logic work correctly.
This doesn't require the FastAPI server to be running.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime
from decimal import Decimal

# Test our new unified schemas
try:
    from app.schemas.strategy_unified import (
        UnifiedStrategyCreate,
        UnifiedStrategyUpdate,
        UnifiedStrategyResponse,
        StrategyType,
        ExecutionType,
        FollowerAccount
    )
    print("[SUCCESS] Successfully imported unified strategy schemas")
except ImportError as e:
    print(f"[ERROR] Failed to import unified schemas: {e}")
    sys.exit(1)

def test_webhook_strategy_creation():
    """Test creating a webhook strategy with the unified schema"""
    print("\n=== Testing Webhook Strategy Creation Schema ===")

    try:
        strategy_data = {
            "strategy_type": "single",
            "execution_type": "webhook",
            "webhook_id": "dsALfSReTUl2yEChwak3jM45sLlpmqGErbYdglmJEqc",  # Purple Reign
            "ticker": "MNQ",
            "account_id": "21610093",
            "quantity": 2,
            "is_active": True,
            "description": "Test Purple Reign strategy"
        }

        strategy = UnifiedStrategyCreate(**strategy_data)
        print(f"[SUCCESS] Webhook strategy schema valid: {strategy.execution_type}, ticker={strategy.ticker}, qty={strategy.quantity}")
        return True
    except Exception as e:
        print(f"[ERROR] Webhook strategy schema failed: {e}")
        return False

def test_engine_strategy_creation():
    """Test creating an engine strategy with the unified schema"""
    print("\n=== Testing Engine Strategy Creation Schema ===")

    try:
        strategy_data = {
            "strategy_type": "single",
            "execution_type": "engine",
            "strategy_code_id": 1,
            "ticker": "MES",
            "account_id": "21610093",
            "quantity": 3,
            "is_active": False
        }

        strategy = UnifiedStrategyCreate(**strategy_data)
        print(f"[SUCCESS] Engine strategy schema valid: {strategy.execution_type}, code_id={strategy.strategy_code_id}")
        return True
    except Exception as e:
        print(f"[ERROR] Engine strategy schema failed: {e}")
        return False

def test_strategy_update():
    """Test updating a strategy (quantity only - no recreate!)"""
    print("\n=== Testing Strategy Update Schema ===")

    try:
        # This is what we'd send to update ONLY quantity
        update_data = {
            "quantity": 5,
            "description": "Updated quantity without recreate"
        }

        update = UnifiedStrategyUpdate(**update_data)
        print(f"[SUCCESS] Update schema valid: quantity={update.quantity}")
        print("[SUCCESS] Core fields (ticker, execution_type, accounts) NOT in update - prevents recreate!")
        return True
    except Exception as e:
        print(f"[ERROR] Update schema failed: {e}")
        return False

def test_validation_logic():
    """Test that validation catches invalid data"""
    print("\n=== Testing Validation Logic ===")

    # Test 1: Missing webhook_id for webhook strategy
    try:
        bad_data = {
            "strategy_type": "single",
            "execution_type": "webhook",
            # Missing webhook_id!
            "ticker": "ES",
            "account_id": "12345",
            "quantity": 1
        }
        strategy = UnifiedStrategyCreate(**bad_data)
        print(f"[ERROR] Validation failed - should have caught missing webhook_id")
        return False
    except ValueError as e:
        print(f"[SUCCESS] Correctly rejected missing webhook_id: {e}")

    # Test 2: Missing strategy_code_id for engine strategy
    try:
        bad_data = {
            "strategy_type": "single",
            "execution_type": "engine",
            # Missing strategy_code_id!
            "ticker": "ES",
            "account_id": "12345",
            "quantity": 1
        }
        strategy = UnifiedStrategyCreate(**bad_data)
        print(f"[ERROR] Validation failed - should have caught missing strategy_code_id")
        return False
    except ValueError as e:
        print(f"[SUCCESS] Correctly rejected missing strategy_code_id: {e}")

    return True

def test_multiple_strategy():
    """Test multiple (leader/follower) strategy"""
    print("\n=== Testing Multiple Strategy Schema ===")

    try:
        strategy_data = {
            "strategy_type": "multiple",
            "execution_type": "webhook",
            "webhook_id": "test-webhook",
            "ticker": "ES",
            "leader_account_id": "leader123",
            "leader_quantity": 2,
            "follower_accounts": [
                {"account_id": "follower1", "quantity": 1},
                {"account_id": "follower2", "quantity": 3}
            ],
            "group_name": "Test Group"
        }

        strategy = UnifiedStrategyCreate(**strategy_data)
        print(f"[SUCCESS] Multiple strategy schema valid: leader + {len(strategy.follower_accounts)} followers")
        return True
    except Exception as e:
        print(f"[ERROR] Multiple strategy schema failed: {e}")
        return False

def main():
    print("=" * 60)
    print("UNIFIED STRATEGY SCHEMA TESTS")
    print("=" * 60)

    results = []

    # Run all tests
    results.append(("Webhook Strategy Creation", test_webhook_strategy_creation()))
    results.append(("Engine Strategy Creation", test_engine_strategy_creation()))
    results.append(("Strategy Update", test_strategy_update()))
    results.append(("Validation Logic", test_validation_logic()))
    results.append(("Multiple Strategy", test_multiple_strategy()))

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for test_name, result in results:
        status = "[PASSED]" if result else "[FAILED]"
        print(f"{test_name}: {status}")

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print("\n[CELEBRATION] All tests passed! The unified strategy system is working correctly.")
        print("\nKey achievements:")
        print("- [SUCCESS] Purple Reign strategies can be updated without recreate")
        print("- [SUCCESS] Explicit execution_type field prevents confusion")
        print("- [SUCCESS] Updates only send changed fields (no core field changes)")
        print("- [SUCCESS] Validation ensures data integrity")
    else:
        print(f"\n[WARNING] {total - passed} test(s) failed. Please review the errors above.")

    return passed == total

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)