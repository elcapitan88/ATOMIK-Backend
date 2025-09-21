#!/usr/bin/env python
"""
Script to check backend health and diagnose multiple issues:
1. Dashboard loading problems
2. Webhook strategies not showing in marketplace/webhook views
"""
import os
import psycopg2
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def main():
    """Check backend health and strategy visibility issues."""
    
    # Get database URL
    database_url = os.getenv("DEV_DATABASE_URL") or os.getenv("DATABASE_PRIVATE_URL") or os.getenv("DATABASE_URL")
    
    if not database_url:
        print("ERROR: No database URL found in environment variables")
        return
    
    print("=" * 80)
    print("BACKEND HEALTH & STRATEGY VISIBILITY DIAGNOSIS")
    print("=" * 80)
    
    # Connect to database
    conn = psycopg2.connect(database_url)
    cursor = conn.cursor()
    
    try:
        # 1. Check all strategy_codes
        print("\n1. ALL STRATEGY CODES (INCLUDING WEBHOOK STRATEGIES):")
        print("-" * 60)
        
        cursor.execute("""
            SELECT id, user_id, name, is_active, is_validated, validation_error, 
                   created_at, symbols
            FROM strategy_codes
            ORDER BY id DESC
        """)
        
        strategy_codes = cursor.fetchall()
        
        if strategy_codes:
            print(f"Found {len(strategy_codes)} total strategy code(s):")
            
            webhook_strategies = []
            regular_strategies = []
            
            for strategy in strategy_codes:
                (sc_id, user_id, name, is_active, is_validated, 
                 validation_error, created_at, symbols) = strategy
                
                status = "ACTIVE" if is_active else "inactive"
                validated = "VALIDATED" if is_validated else "not_validated"
                
                print(f"\n  Strategy ID {sc_id}: {name}")
                print(f"    User: {user_id}")
                print(f"    Status: {status}")
                print(f"    Validation: {validated}")
                print(f"    Created: {created_at}")
                print(f"    Symbols: {symbols}")
                
                if validation_error:
                    print(f"    ERROR: {validation_error}")
                
                # Categorize strategies
                if 'webhook' in name.lower():
                    webhook_strategies.append(strategy)
                else:
                    regular_strategies.append(strategy)
            
            print(f"\n  Summary:")
            print(f"    Regular strategies: {len(regular_strategies)}")
            print(f"    Webhook strategies: {len(webhook_strategies)}")
            
        else:
            print("No strategy codes found!")
        
        # 2. Check activated_strategies
        print("\n2. ACTIVATED STRATEGIES:")
        print("-" * 60)
        
        cursor.execute("""
            SELECT ast.id, ast.user_id, sc.name, ast.is_active, ast.ticker, 
                   ast.quantity, ast.account_id
            FROM activated_strategies ast
            JOIN strategy_codes sc ON ast.strategy_code_id = sc.id
            WHERE ast.is_active = true
            ORDER BY ast.id DESC
        """)
        
        active_activations = cursor.fetchall()
        
        if active_activations:
            print(f"Found {len(active_activations)} active activation(s):")
            for activation in active_activations:
                (act_id, user_id, strategy_name, is_active, ticker, 
                 quantity, account_id) = activation
                print(f"  - ID {act_id}: User {user_id} -> {strategy_name} ({ticker} x{quantity} on {account_id})")
        else:
            print("No active activations found")
        
        # 3. Check for webhook-specific issues
        print("\n3. WEBHOOK STRATEGY VISIBILITY CHECK:")
        print("-" * 60)
        
        # Check if there are any webhook-related strategies
        cursor.execute("""
            SELECT COUNT(*) 
            FROM strategy_codes 
            WHERE LOWER(name) LIKE '%webhook%' AND is_active = true
        """)
        
        webhook_count = cursor.fetchone()[0]
        print(f"Active webhook strategies: {webhook_count}")
        
        if webhook_count == 0:
            print("ISSUE: No active webhook strategies found!")
            print("This explains why webhook strategies don't show in marketplace/webhook views")
        
        # 4. Check marketplace/webhook view requirements
        print("\n4. MARKETPLACE VISIBILITY REQUIREMENTS:")
        print("-" * 60)
        
        cursor.execute("""
            SELECT sc.id, sc.name, sc.is_active, sc.is_validated, 
                   COUNT(ast.id) as activation_count
            FROM strategy_codes sc
            LEFT JOIN activated_strategies ast ON sc.id = ast.strategy_code_id 
                AND ast.is_active = true
            WHERE sc.is_active = true
            GROUP BY sc.id, sc.name, sc.is_active, sc.is_validated
            ORDER BY sc.id DESC
        """)
        
        marketplace_data = cursor.fetchall()
        
        if marketplace_data:
            print("Strategies available for marketplace:")
            for strategy in marketplace_data:
                sc_id, name, is_active, is_validated, activation_count = strategy
                validation_status = "VALIDATED" if is_validated else "NOT VALIDATED"
                print(f"  - {name}: {validation_status}, {activation_count} active subscription(s)")
                
                if not is_validated:
                    print(f"    WARNING: Strategy not validated - may not show in marketplace")
        
        # 5. Database integrity final check
        print("\n5. FINAL DATABASE INTEGRITY CHECK:")
        print("-" * 60)
        
        # Check for any remaining orphaned records
        cursor.execute("""
            SELECT COUNT(*) 
            FROM activated_strategies ast
            LEFT JOIN strategy_codes sc ON ast.strategy_code_id = sc.id
            WHERE sc.id IS NULL
        """)
        
        orphaned_count = cursor.fetchone()[0]
        
        if orphaned_count > 0:
            print(f"WARNING: {orphaned_count} orphaned activated_strategies records still exist")
        else:
            print("OK: No orphaned records found")
        
        # Check for NULL strategy_code_id
        cursor.execute("""
            SELECT COUNT(*) 
            FROM activated_strategies 
            WHERE strategy_code_id IS NULL
        """)
        
        null_count = cursor.fetchone()[0]
        
        if null_count > 0:
            print(f"WARNING: {null_count} activated_strategies with NULL strategy_code_id")
        else:
            print("OK: No NULL strategy_code_id records found")
        
        print("\n6. RECOMMENDATIONS:")
        print("-" * 60)
        
        if webhook_count == 0:
            print("1. CREATE WEBHOOK STRATEGIES:")
            print("   - Add webhook-based strategies to strategy_codes table")
            print("   - Ensure they are active and validated")
        
        print("2. BACKEND API STATUS:")
        print("   - Test /api/v1/strategies/list endpoint manually")
        print("   - Check Railway logs for backend errors")
        print("   - Verify CORS configuration")
        
        print("3. FRONTEND CONNECTION:")
        print("   - Clear browser cache and cookies")
        print("   - Check network connectivity")
        print("   - Verify authentication tokens")
        
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    main()