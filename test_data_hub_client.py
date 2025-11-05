#!/usr/bin/env python3
"""
Test script for Data Hub Client
Run this to verify your Data Hub connection is working
"""

import asyncio
import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.data_hub_client import DataHubClient, DataHubQueries
from app.core.config import settings


async def test_data_hub_client():
    """Test all Data Hub client methods"""

    print("🚀 Testing Data Hub Client Connection")
    print("=" * 50)

    # Initialize client
    client = DataHubClient()
    print(f"✅ Client initialized with URL: {client.base_url}")
    print()

    # Test 1: Market Data
    print("1️⃣ Testing Market Data Fetch...")
    try:
        aapl_data = await client.get_market_data("AAPL")
        if aapl_data.get("success"):
            print("✅ Market data fetch successful!")
            formatted = DataHubQueries.format_price_response(aapl_data)
            print(f"   {formatted}")
        else:
            print(f"❌ Market data fetch failed: {aapl_data.get('error')}")
    except Exception as e:
        print(f"❌ Market data error: {e}")
    print()

    # Test 2: Sentiment Analysis
    print("2️⃣ Testing Sentiment Analysis...")
    try:
        sentiment = await client.get_sentiment("AAPL")
        if sentiment.get("success"):
            print("✅ Sentiment fetch successful!")
            formatted = DataHubQueries.format_sentiment_response(sentiment)
            print(f"   {formatted}")
        else:
            print(f"❌ Sentiment fetch failed: {sentiment.get('error')}")
    except Exception as e:
        print(f"❌ Sentiment error: {e}")
    print()

    # Test 3: Economic Data
    print("3️⃣ Testing Economic Data...")
    try:
        gdp_data = await client.get_economic_data("GDP")
        if gdp_data.get("success"):
            print("✅ Economic data fetch successful!")
            if gdp_data.get("data"):
                latest = gdp_data["data"].get("data_points", [])
                if latest:
                    print(f"   Latest GDP data point: {latest[0]}")
        else:
            print(f"❌ Economic data fetch failed: {gdp_data.get('error')}")
    except Exception as e:
        print(f"❌ Economic data error: {e}")
    print()

    # Test 4: Batch Fetch
    print("4️⃣ Testing Batch Market Data...")
    try:
        symbols = ["AAPL", "TSLA", "GOOGL"]
        batch_data = await client.batch_fetch_market_data(symbols)
        success_count = sum(1 for d in batch_data.values() if d.get("success"))
        print(f"✅ Batch fetch completed: {success_count}/{len(symbols)} successful")
        for symbol, data in batch_data.items():
            if data.get("success"):
                print(f"   {symbol}: ✓")
            else:
                print(f"   {symbol}: ✗ ({data.get('error', 'Unknown error')})")
    except Exception as e:
        print(f"❌ Batch fetch error: {e}")
    print()

    # Test 5: Comprehensive Analysis
    print("5️⃣ Testing Comprehensive Analysis...")
    try:
        analysis = await client.get_comprehensive_analysis("TSLA")
        if analysis.get("success"):
            print("✅ Comprehensive analysis successful!")
            data_types = analysis.get("data", {})
            for dtype, content in data_types.items():
                if content and not isinstance(content, Exception):
                    print(f"   {dtype}: ✓")
                else:
                    print(f"   {dtype}: ✗")
        else:
            print(f"❌ Comprehensive analysis failed: {analysis.get('error')}")
    except Exception as e:
        print(f"❌ Comprehensive analysis error: {e}")
    print()

    # Test 6: Query Detection
    print("6️⃣ Testing Query Detection...")
    test_queries = [
        "What's the price of AAPL?",
        "How is market sentiment today?",
        "Tell me about the latest news",
        "What's the Fed doing with rates?"
    ]

    for query in test_queries:
        needs = DataHubQueries.should_fetch_data(query)
        print(f"   Query: '{query[:30]}...'")
        print(f"   Needs: {', '.join([k for k, v in needs.items() if v])}")
    print()

    # Close the client
    await client.close()

    print("=" * 50)
    print("✅ All tests completed!")
    print()
    print("Next steps:")
    print("1. Ensure your Data Hub is running")
    print("2. Check the ATOMIK_DATA_HUB_URL in your .env")
    print("3. Verify API keys are set if needed")


async def quick_test():
    """Quick connectivity test"""
    print("🔍 Quick Data Hub Connection Test")
    print("-" * 30)

    client = DataHubClient()
    print(f"Connecting to: {client.base_url}")

    try:
        # Just try to get AAPL price
        result = await client.get_market_data("AAPL")
        if result.get("success"):
            print("✅ Connection successful!")
            print(f"   AAPL data retrieved: {result.get('data', {}).get('price', 'N/A')}")
        else:
            print(f"❌ Connection failed: {result.get('error', 'Unknown error')}")
            print("\nTroubleshooting:")
            print("1. Is your Data Hub running?")
            print("2. Check ATOMIK_DATA_HUB_URL in .env")
            print(f"3. Current URL: {client.base_url}")
    except Exception as e:
        print(f"❌ Connection error: {e}")
        print("\nMake sure:")
        print("1. Data Hub is running")
        print("2. URL is correct in .env")
        print("3. Network is accessible")
    finally:
        await client.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Test Data Hub Client")
    parser.add_argument("--quick", action="store_true", help="Run quick connectivity test only")
    args = parser.parse_args()

    if args.quick:
        asyncio.run(quick_test())
    else:
        asyncio.run(test_data_hub_client())