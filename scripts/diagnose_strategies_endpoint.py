#!/usr/bin/env python
"""
Script to diagnose the /api/v1/strategies/list endpoint failure
and check for database inconsistencies after strategy deletion.
"""
import os
import psycopg2
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def main():
    """Diagnose strategies endpoint issues."""
    
    # Get database URL
    database_url = os.getenv("DEV_DATABASE_URL") or os.getenv("DATABASE_PRIVATE_URL") or os.getenv("DATABASE_URL")
    
    if not database_url:
        print("ERROR: No database URL found in environment variables")
        return
    
    print("=" * 70)
    print("DIAGNOSING STRATEGIES ENDPOINT FAILURE")
    print("=" * 70)
    
    # Connect to database
    conn = psycopg2.connect(database_url)
    cursor = conn.cursor()
    
    try:
        # Step 1: Check strategy_codes table
        print("\n1. CHECKING STRATEGY_CODES TABLE:")
        print("-" * 50)
        
        cursor.execute("""
            SELECT id, user_id, name, is_active, validation_error
            FROM strategy_codes
            ORDER BY id
        """)
        
        strategy_codes = cursor.fetchall()
        
        if strategy_codes:
            print(f"Found {len(strategy_codes)} strategy code(s):")
            for strategy in strategy_codes:
                sc_id, user_id, name, is_active, validation_error = strategy
                status = "ACTIVE" if is_active else "inactive"
                error_text = f" (ERROR: {validation_error})" if validation_error else ""
                print(f"  - ID {sc_id}: {name} (User {user_id}) - {status}{error_text}")
        else:
            print("No strategy codes found - this could be the problem!")
        
        # Step 2: Check activated_strategies table
        print("\n2. CHECKING ACTIVATED_STRATEGIES TABLE:")
        print("-" * 50)
        
        cursor.execute("""
            SELECT ast.id, ast.user_id, ast.strategy_code_id, ast.is_active,
                   sc.name as strategy_name
            FROM activated_strategies ast
            LEFT JOIN strategy_codes sc ON ast.strategy_code_id = sc.id
            ORDER BY ast.id
        """)
        
        activations = cursor.fetchall()
        
        if activations:
            print(f"Found {len(activations)} activation(s):")
            orphaned_count = 0
            for activation in activations:
                act_id, user_id, sc_id, is_active, strategy_name = activation
                status = "ACTIVE" if is_active else "inactive"
                
                if strategy_name is None:
                    print(f"  - ID {act_id}: User {user_id} -> ORPHANED (strategy_code_id {sc_id} not found) - {status}")
                    orphaned_count += 1
                else:
                    print(f"  - ID {act_id}: User {user_id} -> {strategy_name} - {status}")
            
            if orphaned_count > 0:
                print(f"\n*** FOUND {orphaned_count} ORPHANED ACTIVATION(S) - THIS IS LIKELY CAUSING THE ERROR ***")
        else:
            print("No activated strategies found")
        
        # Step 3: Check for specific User 39 issues
        print("\n3. CHECKING USER 39 SPECIFICALLY:")
        print("-" * 50)
        
        cursor.execute("""
            SELECT ast.id, ast.strategy_code_id, sc.name, ast.is_active
            FROM activated_strategies ast
            LEFT JOIN strategy_codes sc ON ast.strategy_code_id = sc.id
            WHERE ast.user_id = 39
        """)
        
        user39_activations = cursor.fetchall()
        
        if user39_activations:
            print(f"User 39 has {len(user39_activations)} activation(s):")
            for activation in user39_activations:
                act_id, sc_id, strategy_name, is_active = activation
                status = "ACTIVE" if is_active else "inactive"
                if strategy_name is None:
                    print(f"  - ID {act_id}: ORPHANED (references deleted strategy_code {sc_id}) - {status}")
                else:
                    print(f"  - ID {act_id}: {strategy_name} - {status}")
        else:
            print("User 39 has no activations")
        
        # Step 4: Check for NULL/invalid references
        print("\n4. CHECKING FOR DATABASE INTEGRITY ISSUES:")
        print("-" * 50)
        
        cursor.execute("""
            SELECT COUNT(*) 
            FROM activated_strategies ast
            LEFT JOIN strategy_codes sc ON ast.strategy_code_id = sc.id
            WHERE sc.id IS NULL
        """)
        
        orphaned_count = cursor.fetchone()[0]
        
        if orphaned_count > 0:
            print(f"CRITICAL: {orphaned_count} activated_strategies reference non-existent strategy_codes")
            print("This is definitely causing the API endpoint to fail!")
            
            # Show the problematic records
            cursor.execute("""
                SELECT ast.id, ast.user_id, ast.strategy_code_id, ast.is_active
                FROM activated_strategies ast
                LEFT JOIN strategy_codes sc ON ast.strategy_code_id = sc.id
                WHERE sc.id IS NULL
            """)
            
            orphaned_records = cursor.fetchall()
            print(f"\nOrphaned activated_strategies records:")
            for record in orphaned_records:
                act_id, user_id, sc_id, is_active = record
                status = "ACTIVE" if is_active else "inactive"
                print(f"  - Activation ID {act_id}: User {user_id} references missing strategy_code {sc_id} ({status})")
            
            # Step 5: Offer to fix
            print(f"\n5. FIXING ORPHANED RECORDS:")
            print("-" * 50)
            print("Deleting orphaned activated_strategies records...")
            
            cursor.execute("""
                DELETE FROM activated_strategies
                WHERE strategy_code_id NOT IN (
                    SELECT id FROM strategy_codes
                )
                RETURNING id, user_id, strategy_code_id
            """)
            
            deleted_records = cursor.fetchall()
            
            if deleted_records:
                print(f"Deleted {len(deleted_records)} orphaned record(s):")
                for record in deleted_records:
                    act_id, user_id, sc_id = record
                    print(f"  - Removed activation ID {act_id} (User {user_id}, invalid strategy_code {sc_id})")
                
                conn.commit()
                print("\nOrphaned records cleaned up successfully!")
            else:
                print("No orphaned records to delete")
        else:
            print("No database integrity issues found")
        
        # Step 6: Verify fix
        print(f"\n6. VERIFICATION:")
        print("-" * 50)
        
        cursor.execute("""
            SELECT COUNT(*) as total_strategies FROM strategy_codes WHERE is_active = true
        """)
        active_strategies = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT COUNT(*) as total_activations FROM activated_strategies WHERE is_active = true
        """)
        active_activations = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT COUNT(*) 
            FROM activated_strategies ast
            JOIN strategy_codes sc ON ast.strategy_code_id = sc.id
            WHERE ast.is_active = true
        """)
        valid_activations = cursor.fetchone()[0]
        
        print(f"Active strategy codes: {active_strategies}")
        print(f"Active activations: {active_activations}")
        print(f"Valid activations (with existing strategy codes): {valid_activations}")
        
        if active_activations == valid_activations:
            print("\n[SUCCESS] Database is now consistent!")
            print("The /api/v1/strategies/list endpoint should work now")
            print("Try refreshing the dashboard")
        else:
            print(f"\n[WARNING] Still have {active_activations - valid_activations} invalid activation(s)")
        
    except Exception as e:
        print(f"ERROR: {e}")
        conn.rollback()
        import traceback
        traceback.print_exc()
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    main()