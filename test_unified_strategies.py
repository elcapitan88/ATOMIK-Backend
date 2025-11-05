#!/usr/bin/env python3
"""
Test script for unified strategy endpoints.
Tests creation, listing, updating, and deletion of strategies.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import requests
import json
import time
from typing import Dict, Any, Optional
from datetime import datetime

# Configuration
BASE_URL = "http://localhost:8000"  # Adjust if your FastAPI runs on different port
API_URL = f"{BASE_URL}/api/v1"

# Test user credentials - You'll need to update these
TEST_EMAIL = "cruzh5150@gmail.com"
TEST_PASSWORD = "your_password_here"  # Update this

# Known test data
TEST_WEBHOOK_ID = "dsALfSReTUl2yEChwak3jM45sLlpmqGErbYdglmJEqc"  # Purple Reign
TEST_ACCOUNT_ID = "21610093"  # From your logs
TEST_STRATEGY_CODE_ID = 1  # Adjust based on your database

# Colors for output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'


class UnifiedStrategyTester:
    def __init__(self):
        self.token = None
        self.created_strategy_ids = []
        self.test_results = []

    def log(self, message: str, level: str = "INFO"):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if level == "SUCCESS":
            print(f"{GREEN}✓ [{timestamp}] {message}{RESET}")
        elif level == "ERROR":
            print(f"{RED}✗ [{timestamp}] {message}{RESET}")
        elif level == "WARNING":
            print(f"{YELLOW}⚠ [{timestamp}] {message}{RESET}")
        elif level == "INFO":
            print(f"{BLUE}ℹ [{timestamp}] {message}{RESET}")
        else:
            print(f"  [{timestamp}] {message}")

    def authenticate(self) -> bool:
        """Authenticate and get access token"""
        self.log("Authenticating...", "INFO")

        # Try to login
        response = requests.post(
            f"{API_URL}/auth/login",
            json={
                "email": TEST_EMAIL,
                "password": TEST_PASSWORD
            }
        )

        if response.status_code == 200:
            data = response.json()
            self.token = data.get("access_token")
            self.log(f"Authentication successful for {TEST_EMAIL}", "SUCCESS")
            return True
        else:
            self.log(f"Authentication failed: {response.status_code} - {response.text}", "ERROR")
            return False

    def get_headers(self) -> Dict[str, str]:
        """Get headers with authentication token"""
        if not self.token:
            raise Exception("Not authenticated")
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

    def test_create_webhook_strategy(self) -> Optional[int]:
        """Test creating a webhook-based strategy"""
        self.log("\n=== Testing Webhook Strategy Creation ===", "INFO")

        data = {
            "strategy_type": "single",
            "execution_type": "webhook",
            "webhook_id": TEST_WEBHOOK_ID,
            "ticker": "MNQ",
            "account_id": TEST_ACCOUNT_ID,
            "quantity": 1,
            "is_active": True,
            "description": "Test webhook strategy from unified API"
        }

        self.log(f"Creating webhook strategy: {json.dumps(data, indent=2)}")

        response = requests.post(
            f"{API_URL}/strategies",
            headers=self.get_headers(),
            json=data
        )

        if response.status_code == 200:
            strategy = response.json()
            strategy_id = strategy.get("id")
            self.created_strategy_ids.append(strategy_id)
            self.log(f"Webhook strategy created successfully with ID: {strategy_id}", "SUCCESS")
            self.log(f"Response: {json.dumps(strategy, indent=2, default=str)}")
            return strategy_id
        else:
            self.log(f"Failed to create webhook strategy: {response.status_code}", "ERROR")
            self.log(f"Response: {response.text}")
            return None

    def test_create_engine_strategy(self) -> Optional[int]:
        """Test creating an engine-based strategy"""
        self.log("\n=== Testing Engine Strategy Creation ===", "INFO")

        data = {
            "strategy_type": "single",
            "execution_type": "engine",
            "strategy_code_id": TEST_STRATEGY_CODE_ID,
            "ticker": "MES",
            "account_id": TEST_ACCOUNT_ID,
            "quantity": 2,
            "is_active": False,
            "description": "Test engine strategy from unified API"
        }

        self.log(f"Creating engine strategy: {json.dumps(data, indent=2)}")

        response = requests.post(
            f"{API_URL}/strategies",
            headers=self.get_headers(),
            json=data
        )

        if response.status_code == 200:
            strategy = response.json()
            strategy_id = strategy.get("id")
            self.created_strategy_ids.append(strategy_id)
            self.log(f"Engine strategy created successfully with ID: {strategy_id}", "SUCCESS")
            self.log(f"Response: {json.dumps(strategy, indent=2, default=str)}")
            return strategy_id
        else:
            self.log(f"Failed to create engine strategy: {response.status_code}", "ERROR")
            self.log(f"Response: {response.text}")
            return None

    def test_list_strategies(self):
        """Test listing strategies with filters"""
        self.log("\n=== Testing Strategy Listing ===", "INFO")

        # Test 1: List all strategies
        response = requests.get(
            f"{API_URL}/strategies",
            headers=self.get_headers()
        )

        if response.status_code == 200:
            strategies = response.json()
            self.log(f"Found {len(strategies)} total strategies", "SUCCESS")
        else:
            self.log(f"Failed to list strategies: {response.status_code}", "ERROR")
            return

        # Test 2: Filter by execution_type
        response = requests.get(
            f"{API_URL}/strategies?execution_type=webhook",
            headers=self.get_headers()
        )

        if response.status_code == 200:
            webhook_strategies = response.json()
            self.log(f"Found {len(webhook_strategies)} webhook strategies", "SUCCESS")

        response = requests.get(
            f"{API_URL}/strategies?execution_type=engine",
            headers=self.get_headers()
        )

        if response.status_code == 200:
            engine_strategies = response.json()
            self.log(f"Found {len(engine_strategies)} engine strategies", "SUCCESS")

        # Test 3: Filter by active status
        response = requests.get(
            f"{API_URL}/strategies?is_active=true",
            headers=self.get_headers()
        )

        if response.status_code == 200:
            active_strategies = response.json()
            self.log(f"Found {len(active_strategies)} active strategies", "SUCCESS")

    def test_update_strategy(self, strategy_id: int):
        """Test updating a strategy (quantity only - no recreate!)"""
        self.log(f"\n=== Testing Strategy Update (ID: {strategy_id}) ===", "INFO")

        # First, get the current strategy
        response = requests.get(
            f"{API_URL}/strategies/{strategy_id}",
            headers=self.get_headers()
        )

        if response.status_code != 200:
            self.log(f"Failed to get strategy: {response.status_code}", "ERROR")
            return False

        original_strategy = response.json()
        original_quantity = original_strategy.get("quantity", 1)

        # Update only the quantity
        update_data = {
            "quantity": original_quantity + 1,
            "description": "Updated via unified API test"
        }

        self.log(f"Updating strategy with: {json.dumps(update_data, indent=2)}")

        response = requests.put(
            f"{API_URL}/strategies/{strategy_id}",
            headers=self.get_headers(),
            json=update_data
        )

        if response.status_code == 200:
            updated_strategy = response.json()

            # Verify the ID hasn't changed (no recreate!)
            if updated_strategy.get("id") == strategy_id:
                self.log(f"Strategy updated successfully - same ID maintained!", "SUCCESS")
                self.log(f"Quantity changed from {original_quantity} to {updated_strategy.get('quantity')}", "SUCCESS")
                return True
            else:
                self.log(f"ERROR: Strategy ID changed! Was {strategy_id}, now {updated_strategy.get('id')}", "ERROR")
                return False
        else:
            self.log(f"Failed to update strategy: {response.status_code}", "ERROR")
            self.log(f"Response: {response.text}")
            return False

    def test_validate_strategy(self):
        """Test strategy validation endpoint"""
        self.log("\n=== Testing Strategy Validation ===", "INFO")

        # Test valid strategy
        valid_data = {
            "strategy_data": {
                "strategy_type": "single",
                "execution_type": "webhook",
                "webhook_id": TEST_WEBHOOK_ID,
                "ticker": "ES",
                "account_id": TEST_ACCOUNT_ID,
                "quantity": 1
            }
        }

        response = requests.post(
            f"{API_URL}/strategies/validate",
            headers=self.get_headers(),
            json=valid_data
        )

        if response.status_code == 200:
            result = response.json()
            if result.get("valid"):
                self.log("Valid strategy validation passed", "SUCCESS")
            else:
                self.log(f"Validation failed: {result.get('errors')}", "WARNING")

        # Test invalid strategy (missing required field)
        invalid_data = {
            "strategy_data": {
                "strategy_type": "single",
                "execution_type": "webhook",
                "ticker": "ES"
                # Missing webhook_id and account_id
            }
        }

        response = requests.post(
            f"{API_URL}/strategies/validate",
            headers=self.get_headers(),
            json=invalid_data
        )

        if response.status_code == 200:
            result = response.json()
            if not result.get("valid"):
                self.log(f"Invalid strategy correctly rejected: {result.get('errors')}", "SUCCESS")

    def test_toggle_strategy(self, strategy_id: int):
        """Test toggling strategy active state"""
        self.log(f"\n=== Testing Strategy Toggle (ID: {strategy_id}) ===", "INFO")

        response = requests.post(
            f"{API_URL}/strategies/{strategy_id}/toggle",
            headers=self.get_headers()
        )

        if response.status_code == 200:
            result = response.json()
            self.log(f"Strategy toggled - is_active: {result.get('is_active')}", "SUCCESS")
            return True
        else:
            self.log(f"Failed to toggle strategy: {response.status_code}", "ERROR")
            return False

    def test_delete_strategy(self, strategy_id: int):
        """Test deleting a strategy"""
        self.log(f"\n=== Testing Strategy Deletion (ID: {strategy_id}) ===", "INFO")

        response = requests.delete(
            f"{API_URL}/strategies/{strategy_id}",
            headers=self.get_headers()
        )

        if response.status_code == 200:
            self.log(f"Strategy {strategy_id} deleted successfully", "SUCCESS")
            if strategy_id in self.created_strategy_ids:
                self.created_strategy_ids.remove(strategy_id)
            return True
        else:
            self.log(f"Failed to delete strategy: {response.status_code}", "ERROR")
            return False

    def test_purple_reign_update(self):
        """Specific test for Purple Reign strategy update issue"""
        self.log("\n=== Testing Purple Reign Strategy Update ===", "INFO")

        # Find a Purple Reign strategy
        response = requests.get(
            f"{API_URL}/strategies",
            headers=self.get_headers()
        )

        if response.status_code != 200:
            self.log("Failed to list strategies", "ERROR")
            return

        strategies = response.json()
        purple_reign = None

        for strategy in strategies:
            if strategy.get("webhook_id") == TEST_WEBHOOK_ID:
                purple_reign = strategy
                break

        if not purple_reign:
            self.log("No Purple Reign strategy found to test", "WARNING")
            return

        strategy_id = purple_reign.get("id")
        original_quantity = purple_reign.get("quantity", 1)

        self.log(f"Found Purple Reign strategy ID: {strategy_id}, current quantity: {original_quantity}")

        # Update only the quantity
        update_data = {
            "quantity": original_quantity + 1
        }

        self.log(f"Updating Purple Reign quantity to: {update_data['quantity']}")

        response = requests.put(
            f"{API_URL}/strategies/{strategy_id}",
            headers=self.get_headers(),
            json=update_data
        )

        if response.status_code == 200:
            updated = response.json()
            if updated.get("id") == strategy_id and updated.get("quantity") == original_quantity + 1:
                self.log("Purple Reign update successful! No recreate occurred!", "SUCCESS")

                # Restore original quantity
                requests.put(
                    f"{API_URL}/strategies/{strategy_id}",
                    headers=self.get_headers(),
                    json={"quantity": original_quantity}
                )
            else:
                self.log("Purple Reign update issue detected", "ERROR")
        else:
            self.log(f"Purple Reign update failed: {response.status_code} - {response.text}", "ERROR")

    def cleanup(self):
        """Clean up any test strategies created"""
        self.log("\n=== Cleanup ===", "INFO")

        for strategy_id in self.created_strategy_ids[:]:
            if self.test_delete_strategy(strategy_id):
                self.log(f"Cleaned up test strategy {strategy_id}", "SUCCESS")

    def run_all_tests(self):
        """Run all tests in sequence"""
        self.log("\n" + "="*60, "INFO")
        self.log("UNIFIED STRATEGY API TEST SUITE", "INFO")
        self.log("="*60 + "\n", "INFO")

        # Authenticate
        if not self.authenticate():
            self.log("Cannot proceed without authentication", "ERROR")
            return

        try:
            # Test validation endpoint
            self.test_validate_strategy()

            # Create test strategies
            webhook_id = self.test_create_webhook_strategy()
            engine_id = self.test_create_engine_strategy()

            # List strategies
            self.test_list_strategies()

            # Test updates (no recreate!)
            if webhook_id:
                self.test_update_strategy(webhook_id)
                self.test_toggle_strategy(webhook_id)

            if engine_id:
                self.test_update_strategy(engine_id)
                self.test_toggle_strategy(engine_id)

            # Test Purple Reign specific issue
            self.test_purple_reign_update()

        except Exception as e:
            self.log(f"Test error: {str(e)}", "ERROR")
            import traceback
            traceback.print_exc()

        finally:
            # Cleanup
            self.cleanup()

        self.log("\n" + "="*60, "INFO")
        self.log("TEST SUITE COMPLETE", "INFO")
        self.log("="*60 + "\n", "INFO")


if __name__ == "__main__":
    print("\nStarting Unified Strategy API Tests...")
    print("Make sure your FastAPI server is running on localhost:8000\n")

    # Check if server is running
    try:
        response = requests.get(f"{BASE_URL}/docs")
        if response.status_code != 200:
            print(f"{RED}FastAPI server not responding at {BASE_URL}{RESET}")
            print("Please start the server with: cd fastapi_backend && uvicorn app.main:app --reload")
            sys.exit(1)
    except requests.exceptions.ConnectionError:
        print(f"{RED}Cannot connect to FastAPI server at {BASE_URL}{RESET}")
        print("Please start the server with: cd fastapi_backend && uvicorn app.main:app --reload")
        sys.exit(1)

    # Run tests
    tester = UnifiedStrategyTester()

    # Get password if not set
    if TEST_PASSWORD == "your_password_here":
        import getpass
        TEST_PASSWORD = getpass.getpass(f"Enter password for {TEST_EMAIL}: ")

    tester.run_all_tests()