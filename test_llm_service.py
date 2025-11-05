#!/usr/bin/env python3
"""
Test script for LLM Service (Claude 3 Sonnet)
Tests different query complexities and configurations
"""

import asyncio
import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.llm_service import LLMService, QueryComplexity, ResponseFormatter
from app.core.config import settings


async def test_llm_service():
    """Test LLM service with various query types"""

    print("🤖 Testing LLM Service (Claude 3 Sonnet)")
    print("=" * 50)

    # Check for API key
    if not hasattr(settings, 'ANTHROPIC_API_KEY') or not settings.ANTHROPIC_API_KEY:
        print("❌ No ANTHROPIC_API_KEY found in environment")
        print("   Please add to your .env file:")
        print("   ANTHROPIC_API_KEY=sk-ant-api03-...")
        return

    # Initialize service
    llm = LLMService()
    print(f"✅ LLM Service initialized with model: {llm.model}")
    print()

    # Test 1: Query Complexity Classification
    print("1️⃣ Testing Query Complexity Classification...")
    test_queries = [
        ("What's the price of AAPL?", QueryComplexity.SIMPLE),
        ("Why is Tesla stock up today?", QueryComplexity.MODERATE),
        ("Should I rebalance my portfolio given the Fed meeting?", QueryComplexity.COMPLEX),
    ]

    for query, expected in test_queries:
        detected = llm.classify_query_complexity(query)
        status = "✅" if detected == expected else "❌"
        print(f"   {status} '{query[:30]}...' → {detected.value}")
    print()

    # Test 2: Simple Query
    print("2️⃣ Testing Simple Query (minimal tokens)...")
    try:
        response = await llm.analyze_market_data(
            query="What is AAPL price?",
            market_data={
                "price_data": {
                    "data": {
                        "symbol": "AAPL",
                        "price": 185.50,
                        "change": 2.30,
                        "change_percent": 1.25,
                        "volume": 52000000
                    }
                }
            },
            complexity=QueryComplexity.SIMPLE
        )

        if response["success"]:
            print("✅ Simple query successful!")
            print(f"   Response: {response['text'][:100]}...")
            print(f"   Tokens: {response.get('tokens_used', {})}")
            print(f"   Cost: ${response.get('estimated_cost', 0):.4f}")
        else:
            print(f"❌ Simple query failed: {response.get('error')}")
    except Exception as e:
        print(f"❌ Error: {e}")
    print()

    # Test 3: Moderate Query
    print("3️⃣ Testing Moderate Query (balanced)...")
    try:
        response = await llm.analyze_market_data(
            query="Why is TSLA up 5% today?",
            market_data={
                "price_data": {
                    "data": {
                        "symbol": "TSLA",
                        "price": 250.00,
                        "change": 12.00,
                        "change_percent": 5.0
                    }
                },
                "sentiment": {
                    "data": {
                        "overall_sentiment": {
                            "label": "bullish",
                            "score": 0.75
                        }
                    }
                }
            },
            complexity=QueryComplexity.MODERATE
        )

        if response["success"]:
            print("✅ Moderate query successful!")
            print(f"   Response length: {len(response['text'])} chars")
            print(f"   Complexity: {response.get('complexity')}")
            print(f"   Cost: ${response.get('estimated_cost', 0):.4f}")
        else:
            print(f"❌ Moderate query failed: {response.get('error')}")
    except Exception as e:
        print(f"❌ Error: {e}")
    print()

    # Test 4: Complex Query
    print("4️⃣ Testing Complex Query (comprehensive)...")
    try:
        response = await llm.analyze_market_data(
            query="Should I buy NVDA given the AI boom and current valuations?",
            market_data={
                "price_data": {
                    "data": {"symbol": "NVDA", "price": 880.00, "change_percent": 2.5}
                },
                "sentiment": {
                    "data": {"overall_sentiment": {"label": "very bullish", "score": 0.85}}
                }
            },
            user_context={
                "risk_tolerance": "moderate",
                "positions": {"AAPL": {"quantity": 100}, "GOOGL": {"quantity": 50}},
                "account_value": 50000
            },
            complexity=QueryComplexity.COMPLEX
        )

        if response["success"]:
            print("✅ Complex query successful!")
            print(f"   Response preview: {response['text'][:150]}...")
            print(f"   Tokens used: {response.get('tokens_used', {})}")
            print(f"   Cost: ${response.get('estimated_cost', 0):.4f}")
        else:
            print(f"❌ Complex query failed: {response.get('error')}")
    except Exception as e:
        print(f"❌ Error: {e}")
    print()

    # Test 5: Response Formatting
    print("5️⃣ Testing Response Formatting...")
    sample_response = "**NVDA Analysis**\n\n• Current price: $880\n• Sentiment: 🟢 Bullish\n\nRecommendation: Buy"

    voice_formatted = ResponseFormatter.format_for_voice(sample_response)
    chat_formatted = ResponseFormatter.format_for_chat(sample_response)

    print("   Original:", sample_response.replace('\n', ' ')[:50] + "...")
    print("   Voice:", voice_formatted[:50] + "...")
    print("   Chat:", chat_formatted.replace('\n', ' ')[:50] + "...")
    print()

    # Test 6: Fallback Response
    print("6️⃣ Testing Fallback Response (no API)...")
    llm_no_api = LLMService()
    llm_no_api.client = None  # Simulate no API

    response = await llm_no_api.analyze_market_data(
        query="What's AAPL price?",
        market_data={"price_data": {"data": {"symbol": "AAPL", "price": 185.50}}}
    )
    print(f"   Fallback response: {response['text'][:100]}...")
    print()

    # Usage Report
    print("7️⃣ Usage Report")
    print("-" * 30)
    usage = llm.get_usage_report()
    print(f"   Total Requests: {usage['total_requests']}")
    print(f"   Total Tokens: {usage['total_tokens']}")
    print(f"   Estimated Cost: ${usage['estimated_cost_usd']:.4f}")
    print(f"   Avg Cost/Request: ${usage['average_cost_per_request']:.4f}")
    print()

    print("=" * 50)
    print("✅ LLM Service tests completed!")
    print()
    print("Next steps:")
    print("1. Verify Claude responses are appropriate")
    print("2. Check token usage is within limits")
    print("3. Confirm costs are acceptable")


async def quick_test():
    """Quick API connectivity test"""
    print("🔍 Quick Claude API Test")
    print("-" * 30)

    if not hasattr(settings, 'ANTHROPIC_API_KEY') or not settings.ANTHROPIC_API_KEY:
        print("❌ No ANTHROPIC_API_KEY found")
        print("\nAdd to your .env file:")
        print("ANTHROPIC_API_KEY=sk-ant-api03-...")
        return

    llm = LLMService()
    print(f"Testing model: {llm.model}")

    try:
        response = await llm.analyze_market_data(
            query="Say 'Claude is connected' if you can read this",
            complexity=QueryComplexity.SIMPLE
        )

        if response["success"]:
            print("✅ Claude API connected!")
            print(f"   Response: {response['text']}")
            print(f"   Model: {response.get('model')}")
        else:
            print(f"❌ Connection failed: {response.get('error')}")
    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Test LLM Service")
    parser.add_argument("--quick", action="store_true", help="Run quick API test only")
    args = parser.parse_args()

    if args.quick:
        asyncio.run(quick_test())
    else:
        asyncio.run(test_llm_service())