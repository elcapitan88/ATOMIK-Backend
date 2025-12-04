#!/usr/bin/env python3
"""
Test Purple Reign Strategy Engine Signal.
Simulates what the strategy engine sends when it triggers a trade.

This tests the FULL flow:
1. Signal sent to /api/v1/trades/execute
2. Backend finds StrategyCode by name
3. Backend finds ActivatedStrategies linked to it
4. Trade executed on broker

USAGE:
  python test_purple_reign_signal.py              # Dry run (no actual trade)
  python test_purple_reign_signal.py --execute    # Actually execute the trade
"""

import argparse
import requests
from datetime import datetime, timezone

# Backend URL (Railway production)
BACKEND_URL = "https://api.atomiktrading.io"

# Strategy Engine API Key (get from Railway env vars if needed)
# If not set in backend, requests are allowed through
STRATEGY_ENGINE_API_KEY = "K7mN2pQ5vXsomeothervalueK7pL0sD3gF"


def test_signal(action: str = "BUY", symbol: str = "NQ", dry_run: bool = True):
    """
    Send a test signal that mimics the strategy engine.

    Args:
        action: "BUY" or "SELL"
        symbol: "NQ", "MNQ", "ES", or "MES"
        dry_run: If True, just print what would happen without sending
    """

    # This is EXACTLY what the strategy engine sends
    payload = {
        "strategy_name": "Purple Reign",
        "symbol": symbol,
        "action": action,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "comment": "TEST_SIGNAL"  # Could be EXIT_50, EXIT_100, etc.
    }

    headers = {
        "Content-Type": "application/json"
    }

    if STRATEGY_ENGINE_API_KEY:
        headers["X-API-Key"] = STRATEGY_ENGINE_API_KEY

    url = f"{BACKEND_URL}/api/v1/trades/execute"

    print("=" * 70)
    print("PURPLE REIGN TEST SIGNAL")
    print("=" * 70)
    print(f"URL: {url}")
    print(f"Action: {action}")
    print(f"Symbol: {symbol}")
    print(f"Timestamp: {payload['timestamp']}")
    print(f"Comment: {payload['comment']}")
    print(f"API Key: {'Set' if STRATEGY_ENGINE_API_KEY else 'Not set (relying on backend allowing all)'}")
    print()

    if dry_run:
        print("[DRY RUN] Would send payload:")
        print(f"  {payload}")
        print()
        print("To actually send, run with --execute flag:")
        print(f"  python test_purple_reign_signal.py --execute --action {action} --symbol {symbol}")
        return

    print("Sending signal to backend...")
    print()

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)

        print(f"Response Status: {response.status_code}")
        print(f"Response Body:")

        try:
            result = response.json()
            import json
            print(json.dumps(result, indent=2))
        except:
            print(response.text)

        if response.status_code == 200:
            print()
            print("[OK] Signal processed successfully!")
        else:
            print()
            print(f"[ERROR] Signal failed with status {response.status_code}")

    except requests.exceptions.Timeout:
        print("[ERROR] Request timed out after 30 seconds")
    except requests.exceptions.ConnectionError as e:
        print(f"[ERROR] Connection failed: {e}")
    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}")


def main():
    parser = argparse.ArgumentParser(description="Test Purple Reign Strategy Signal")
    parser.add_argument("--execute", action="store_true",
                        help="Actually send the signal (default is dry run)")
    parser.add_argument("--action", choices=["BUY", "SELL"], default="BUY",
                        help="Trade action (default: BUY)")
    parser.add_argument("--symbol", choices=["NQ", "MNQ", "ES", "MES"], default="NQ",
                        help="Symbol to trade (default: NQ)")

    args = parser.parse_args()

    test_signal(
        action=args.action,
        symbol=args.symbol,
        dry_run=not args.execute
    )


if __name__ == "__main__":
    main()
