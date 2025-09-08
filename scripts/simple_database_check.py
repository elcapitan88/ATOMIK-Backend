#!/usr/bin/env python
"""
Simple script to check what's causing the API endpoint to fail.
"""
import os
import psycopg2
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def main():
    """Check database and simulate API endpoint query."""
    
    # Get database URL
    database_url = os.getenv("DEV_DATABASE_URL") or os.getenv("DATABASE_PRIVATE_URL") or os.getenv("DATABASE_URL")
    
    if not database_url:
        print("ERROR: No database URL found in environment variables")
        return
    
    print("=" * 70)
    print("SIMPLE DATABASE CHECK FOR API ENDPOINT ISSUE")
    print("=" * 70)
    
    # Connect to database
    conn = psycopg2.connect(database_url)
    cursor = conn.cursor()
    
    try:
        # Test the exact query that /api/v1/strategies/list likely uses
        print("\n1. TESTING STRATEGIES LIST QUERY:")
        print("-" * 50)
        
        cursor.execute("""
            SELECT 
                sc.id,
                sc.name,
                sc.description,
                sc.user_id,
                sc.is_active,
                sc.is_validated,
                sc.created_at,
                sc.symbols
            FROM strategy_codes sc
            WHERE sc.is_active = true
            ORDER BY sc.created_at DESC
        """)
        
        strategies = cursor.fetchall()
        print(f"Query SUCCESS: Found {len(strategies)} active strategies")
        
        for strategy in strategies:
            sc_id, name, desc, user_id, is_active, is_validated, created_at, symbols = strategy
            print(f"  - ID {sc_id}: {name} (User {user_id}, Validated: {is_validated})")
        
        # Test with JOIN to activated_strategies
        print(f"\n2. TESTING WITH ACTIVATIONS JOIN:")
        print("-" * 50)
        
        cursor.execute("""
            SELECT 
                sc.id,
                sc.name,
                sc.user_id,
                COUNT(ast.id) as activation_count
            FROM strategy_codes sc
            LEFT JOIN activated_strategies ast ON sc.id = ast.strategy_code_id 
                AND ast.is_active = true
            WHERE sc.is_active = true
            GROUP BY sc.id, sc.name, sc.user_id
            ORDER BY sc.created_at DESC
        """)
        
        strategies_with_activations = cursor.fetchall()
        print(f"JOIN Query SUCCESS: Found {len(strategies_with_activations)} strategies with activation counts")
        
        for strategy in strategies_with_activations:
            sc_id, name, user_id, activation_count = strategy
            print(f"  - {name}: {activation_count} active subscriptions")
        
        # Test basic table integrity
        print(f"\n3. BASIC TABLE COUNTS:")
        print("-" * 50)
        
        cursor.execute("SELECT COUNT(*) FROM strategy_codes")
        strategy_count = cursor.fetchone()[0]
        print(f"Total strategy_codes: {strategy_count}")
        
        cursor.execute("SELECT COUNT(*) FROM activated_strategies")
        activation_count = cursor.fetchone()[0]
        print(f"Total activated_strategies: {activation_count}")
        
        cursor.execute("SELECT COUNT(*) FROM activated_strategies WHERE is_active = true")
        active_activation_count = cursor.fetchone()[0]
        print(f"Active activated_strategies: {active_activation_count}")
        
        cursor.execute("SELECT COUNT(*) FROM users")
        user_count = cursor.fetchone()[0]
        print(f"Total users: {user_count}")
        
        # Check for the specific user (39) that we know should exist
        print(f"\n4. CHECKING USER 39 SPECIFICALLY:")
        print("-" * 50)
        
        cursor.execute("SELECT id, username, email FROM users WHERE id = 39")
        user39 = cursor.fetchone()
        
        if user39:
            user_id, username, email = user39
            print(f"User 39 exists: {username} ({email})")
            
            # Check their strategies
            cursor.execute("""
                SELECT sc.id, sc.name, ast.id as activation_id, ast.is_active
                FROM strategy_codes sc
                LEFT JOIN activated_strategies ast ON sc.id = ast.strategy_code_id AND ast.user_id = 39
                WHERE sc.user_id = 39
            """)
            
            user39_strategies = cursor.fetchall()
            print(f"User 39 has {len(user39_strategies)} strategy code(s):")
            
            for strat in user39_strategies:
                sc_id, name, act_id, is_active = strat
                activation_status = f"Activation {act_id} ({'ACTIVE' if is_active else 'inactive'})" if act_id else "No activation"
                print(f"  - {name}: {activation_status}")
        else:
            print("ERROR: User 39 not found!")
        
        print(f"\n5. CONCLUSION:")
        print("-" * 50)
        print("Database queries work fine here.")
        print("The issue is likely in the FastAPI application itself:")
        print("1. Backend server might be crashing on startup")
        print("2. Authentication middleware might be failing")
        print("3. The API route handler might have a bug")
        print("4. Environment variables might be missing")
        print("\nCheck Railway backend logs for Python errors!")
        
    except Exception as e:
        print(f"ERROR: Database query failed: {e}")
        print("This could be why the API endpoint is failing!")
        import traceback
        traceback.print_exc()
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    main()