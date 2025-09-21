#!/usr/bin/env python
"""
Script to check for database inconsistencies caused by deleting activated strategy.
This could include foreign key violations, cascade issues, or related table corruption.
"""
import os
import psycopg2
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def main():
    """Check for database issues caused by strategy deletion."""
    
    # Get database URL
    database_url = os.getenv("DEV_DATABASE_URL") or os.getenv("DATABASE_PRIVATE_URL") or os.getenv("DATABASE_URL")
    
    if not database_url:
        print("ERROR: No database URL found in environment variables")
        return
    
    print("=" * 70)
    print("CHECKING FOR DATABASE DAMAGE FROM STRATEGY DELETION")
    print("=" * 70)
    
    # Connect to database
    conn = psycopg2.connect(database_url)
    cursor = conn.cursor()
    
    try:
        # 1. Check for foreign key violations in related tables
        print("\n1. CHECKING FOREIGN KEY REFERENCES:")
        print("-" * 50)
        
        # Check trades table for orphaned references
        cursor.execute("""
            SELECT COUNT(*) 
            FROM trades t
            LEFT JOIN activated_strategies ast ON t.strategy_id = ast.id
            WHERE ast.id IS NULL AND t.strategy_id IS NOT NULL
        """)
        
        orphaned_trades = cursor.fetchone()[0]
        if orphaned_trades > 0:
            print(f"ISSUE: {orphaned_trades} trades reference non-existent activated_strategies")
        else:
            print("OK: No orphaned trades found")
        
        # Check for other tables that might reference activated_strategies
        tables_to_check = [
            ('orders', 'strategy_id'),
            ('positions', 'strategy_id'), 
            ('performance_metrics', 'strategy_id'),
            ('strategy_executions', 'strategy_id'),
            ('notifications', 'strategy_id')
        ]
        
        for table_name, column_name in tables_to_check:
            try:
                cursor.execute(f"""
                    SELECT COUNT(*) 
                    FROM {table_name} t
                    LEFT JOIN activated_strategies ast ON t.{column_name} = ast.id
                    WHERE ast.id IS NULL AND t.{column_name} IS NOT NULL
                """)
                
                count = cursor.fetchone()[0]
                if count > 0:
                    print(f"ISSUE: {count} {table_name} records reference non-existent activated_strategies")
                else:
                    print(f"OK: No orphaned {table_name} records")
                    
            except Exception as e:
                print(f"Note: {table_name} table check failed (table might not exist): {e}")
        
        # 2. Check for NULL values where they shouldn't be
        print("\n2. CHECKING FOR NULL VALUE ISSUES:")
        print("-" * 50)
        
        # Check strategy_codes for NULL critical fields
        cursor.execute("""
            SELECT id, name, user_id, is_active, is_validated
            FROM strategy_codes
            WHERE name IS NULL OR user_id IS NULL
        """)
        
        null_strategy_codes = cursor.fetchall()
        if null_strategy_codes:
            print("ISSUE: strategy_codes with NULL critical fields:")
            for record in null_strategy_codes:
                print(f"  - ID {record[0]}: name={record[1]}, user_id={record[2]}")
        else:
            print("OK: No NULL critical fields in strategy_codes")
        
        # 3. Check for data type issues or corruption
        print("\n3. CHECKING FOR DATA CORRUPTION:")
        print("-" * 50)
        
        # Check for malformed JSON in strategy_codes
        cursor.execute("""
            SELECT id, name, symbols 
            FROM strategy_codes
            WHERE symbols IS NOT NULL
        """)
        
        json_records = cursor.fetchall()
        corrupt_json = 0
        
        for record in json_records:
            sc_id, name, symbols = record
            try:
                if symbols and symbols.strip():
                    import json
                    json.loads(symbols)
            except (json.JSONDecodeError, AttributeError) as e:
                print(f"ISSUE: Strategy {sc_id} ({name}) has malformed symbols JSON: {symbols}")
                corrupt_json += 1
        
        if corrupt_json == 0:
            print("OK: No JSON corruption found")
        
        # 4. Check for user reference issues
        print("\n4. CHECKING USER REFERENCES:")
        print("-" * 50)
        
        # Check if strategy_codes reference non-existent users
        cursor.execute("""
            SELECT sc.id, sc.name, sc.user_id
            FROM strategy_codes sc
            LEFT JOIN users u ON sc.user_id = u.id
            WHERE u.id IS NULL
        """)
        
        orphaned_strategy_codes = cursor.fetchall()
        if orphaned_strategy_codes:
            print("ISSUE: strategy_codes reference non-existent users:")
            for record in orphaned_strategy_codes:
                sc_id, name, user_id = record
                print(f"  - Strategy {sc_id} ({name}) references non-existent user {user_id}")
        else:
            print("OK: All strategy_codes reference valid users")
        
        # 5. Check the specific /api/v1/strategies/list query
        print("\n5. TESTING STRATEGIES LIST QUERY:")
        print("-" * 50)
        
        # Simulate the actual query that the API endpoint uses
        try:
            cursor.execute("""
                SELECT 
                    sc.id,
                    sc.name,
                    sc.description,
                    sc.symbols,
                    sc.is_active,
                    sc.is_validated,
                    sc.user_id,
                    sc.created_at,
                    COUNT(ast.id) as activation_count
                FROM strategy_codes sc
                LEFT JOIN activated_strategies ast ON sc.id = ast.strategy_code_id 
                    AND ast.is_active = true
                WHERE sc.is_active = true
                GROUP BY sc.id, sc.name, sc.description, sc.symbols, 
                         sc.is_active, sc.is_validated, sc.user_id, sc.created_at
                ORDER BY sc.created_at DESC
            """)
            
            results = cursor.fetchall()
            print(f"OK: Strategies list query executed successfully - {len(results)} results")
            
            for result in results:
                sc_id, name, desc, symbols, is_active, is_validated, user_id, created_at, activation_count = result
                print(f"  - {name}: {activation_count} activations, user {user_id}")
                
        except Exception as e:
            print(f"CRITICAL: Strategies list query failed: {e}")
            print("This is likely why the API endpoint is failing!")
        
        # 6. Check for sequence/ID issues
        print("\n6. CHECKING SEQUENCE ISSUES:")
        print("-" * 50)
        
        # Check if sequences are corrupted
        cursor.execute("SELECT MAX(id) FROM strategy_codes")
        max_strategy_id = cursor.fetchone()[0]
        
        cursor.execute("SELECT MAX(id) FROM activated_strategies") 
        max_activation_id = cursor.fetchone()[0]
        
        print(f"Max strategy_codes ID: {max_strategy_id}")
        print(f"Max activated_strategies ID: {max_activation_id}")
        
        # Check for gaps that might indicate corruption
        cursor.execute("SELECT COUNT(*) FROM strategy_codes")
        strategy_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM activated_strategies")
        activation_count = cursor.fetchone()[0]
        
        print(f"Total strategy_codes: {strategy_count}")
        print(f"Total activated_strategies: {activation_count}")
        
        print(f"\n7. SUMMARY & NEXT STEPS:")
        print("-" * 50)
        print("If the strategies list query works here but not in the API,")
        print("the issue is likely in the FastAPI application code, not the database.")
        print("\nTry:")
        print("1. Check Railway backend logs for Python errors")
        print("2. Restart the backend service")
        print("3. Test the API endpoint directly with authentication")
        
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    main()