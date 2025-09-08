#!/usr/bin/env python
"""
Test the /api/v1/strategies/list endpoint that's failing for the frontend
"""
import os
import psycopg2
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def main():
    """Test the strategies list query that the API endpoint uses."""
    
    # Get database URL
    database_url = os.getenv("DEV_DATABASE_URL") or os.getenv("DATABASE_PRIVATE_URL") or os.getenv("DATABASE_URL")
    
    if not database_url:
        print("ERROR: No database URL found in environment variables")
        return
    
    print("=" * 70)
    print("TESTING /api/v1/strategies/list ENDPOINT QUERY")
    print("=" * 70)
    
    # Connect to database
    conn = psycopg2.connect(database_url)
    cursor = conn.cursor()
    
    try:
        # Test the exact query that the endpoint uses for User 39
        print("\n1. TESTING STRATEGIES LIST QUERY FOR USER 39:")
        print("-" * 50)
        
        # This simulates the exact SQLAlchemy query from strategy.py line 425-434
        cursor.execute("""
            SELECT 
                ast.id,
                ast.user_id,
                ast.strategy_type,
                ast.webhook_id,
                ast.strategy_code_id,
                ast.ticker,
                ast.is_active,
                ast.created_at,
                ast.last_triggered,
                ba.account_id as broker_account_id,
                ba.name as broker_name,
                lba.account_id as leader_account_id,
                lba.name as leader_name,
                w.name as webhook_name,
                w.source_type as webhook_source_type
            FROM activated_strategies ast
            LEFT JOIN broker_accounts ba ON ba.account_id = ast.account_id
            LEFT JOIN broker_accounts lba ON lba.account_id = ast.leader_account_id  
            LEFT JOIN webhooks w ON w.id = CAST(ast.webhook_id AS INTEGER)
            WHERE ast.user_id = 39
        """)
        
        strategies = cursor.fetchall()
        print(f"Query SUCCESS: Found {len(strategies)} strategies for User 39")
        
        for strategy in strategies:
            print(f"  - Strategy ID {strategy[0]}: {strategy[5]} ({strategy[6]})")
            if strategy[13]:  # webhook_name
                print(f"    Webhook: {strategy[13]} (Type: {strategy[14]})")
            if strategy[4]:  # strategy_code_id
                print(f"    Strategy Code ID: {strategy[4]}")
        
        # Test for User 163 as well 
        print(f"\n2. TESTING FOR USER 163:")
        print("-" * 50)
        
        cursor.execute("""
            SELECT ast.id, ast.user_id, ast.ticker, ast.is_active, ast.webhook_id, ast.strategy_code_id
            FROM activated_strategies ast
            WHERE ast.user_id = 163
        """)
        
        user163_strategies = cursor.fetchall()
        print(f"Found {len(user163_strategies)} strategies for User 163")
        for strategy in user163_strategies:
            print(f"  - Strategy ID {strategy[0]}: {strategy[2]} (Active: {strategy[3]})")
        
        # Check for any NULL webhook_id that should be INTEGER but stored as STRING
        print(f"\n3. CHECKING FOR WEBHOOK_ID CONVERSION ISSUES:")
        print("-" * 50)
        
        cursor.execute("""
            SELECT ast.id, ast.webhook_id, w.id as webhook_int_id, w.name
            FROM activated_strategies ast
            LEFT JOIN webhooks w ON w.id = CAST(ast.webhook_id AS INTEGER)
            WHERE ast.webhook_id IS NOT NULL
        """)
        
        webhook_conversions = cursor.fetchall()
        print(f"Found {len(webhook_conversions)} strategies with webhook_id")
        for conv in webhook_conversions:
            ast_id, webhook_id_str, webhook_int_id, webhook_name = conv
            if webhook_int_id is None:
                print(f"  - ERROR: Strategy {ast_id} has webhook_id '{webhook_id_str}' but no matching webhook found")
            else:
                print(f"  - OK: Strategy {ast_id} -> webhook_id {webhook_id_str} -> webhook {webhook_name}")
        
        print(f"\n4. CONCLUSION:")
        print("-" * 50)
        
        if len(strategies) == 0:
            print("No strategies found for User 39 - this could explain the issue")
        else:
            print("Database query works fine.")
            print("The issue is likely in:")
            print("1. Authentication token validation")
            print("2. CORS preflight request handling") 
            print("3. SQLAlchemy relationship loading in the FastAPI endpoint")
        
    except Exception as e:
        print(f"ERROR: Database query failed: {e}")
        print("This could explain why the API endpoint is failing!")
        import traceback
        traceback.print_exc()
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    main()