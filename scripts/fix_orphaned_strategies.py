#!/usr/bin/env python
"""
Script to fix orphaned activated_strategies records with NULL strategy_code_id.
This will clean up the database and restore the /api/v1/strategies/list endpoint.
"""
import os
import psycopg2
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def main():
    """Fix orphaned activated_strategies records."""
    
    # Get database URL
    database_url = os.getenv("DEV_DATABASE_URL") or os.getenv("DATABASE_PRIVATE_URL") or os.getenv("DATABASE_URL")
    
    if not database_url:
        print("ERROR: No database URL found in environment variables")
        return
    
    print("=" * 70)
    print("FIXING ORPHANED ACTIVATED_STRATEGIES RECORDS")
    print("=" * 70)
    
    # Connect to database
    conn = psycopg2.connect(database_url)
    cursor = conn.cursor()
    
    try:
        # Step 1: Find all records with NULL strategy_code_id
        print("\n1. FINDING ORPHANED RECORDS:")
        print("-" * 50)
        
        cursor.execute("""
            SELECT id, user_id, strategy_code_id, is_active, ticker, account_id
            FROM activated_strategies
            WHERE strategy_code_id IS NULL
            ORDER BY id
        """)
        
        orphaned_records = cursor.fetchall()
        
        if not orphaned_records:
            print("No orphaned records found!")
            return
        
        print(f"Found {len(orphaned_records)} orphaned record(s) with NULL strategy_code_id:")
        
        active_orphaned = 0
        for record in orphaned_records:
            act_id, user_id, sc_id, is_active, ticker, account_id = record
            status = "ACTIVE" if is_active else "inactive"
            if is_active:
                active_orphaned += 1
            print(f"  - ID {act_id}: User {user_id}, {ticker}, Account {account_id} ({status})")
        
        print(f"\nOf these, {active_orphaned} are ACTIVE (causing API failures)")
        
        # Step 2: Delete all orphaned records
        print(f"\n2. DELETING ORPHANED RECORDS:")
        print("-" * 50)
        print("Removing all activated_strategies with NULL strategy_code_id...")
        
        cursor.execute("""
            DELETE FROM activated_strategies
            WHERE strategy_code_id IS NULL
            RETURNING id, user_id, is_active
        """)
        
        deleted_records = cursor.fetchall()
        
        if deleted_records:
            print(f"Successfully deleted {len(deleted_records)} orphaned record(s):")
            
            active_deleted = 0
            for record in deleted_records:
                act_id, user_id, is_active = record
                status = "ACTIVE" if is_active else "inactive"
                if is_active:
                    active_deleted += 1
                print(f"  - Removed ID {act_id}: User {user_id} ({status})")
            
            print(f"\nDeleted {active_deleted} ACTIVE orphaned records")
            
            # Commit the changes
            conn.commit()
            print("Changes committed to database")
        else:
            print("No records were deleted")
        
        # Step 3: Verify the fix
        print(f"\n3. VERIFICATION:")
        print("-" * 50)
        
        # Check for remaining NULL strategy_code_id records
        cursor.execute("""
            SELECT COUNT(*) 
            FROM activated_strategies
            WHERE strategy_code_id IS NULL
        """)
        
        remaining_orphaned = cursor.fetchone()[0]
        
        # Check total valid activations
        cursor.execute("""
            SELECT COUNT(*) 
            FROM activated_strategies ast
            JOIN strategy_codes sc ON ast.strategy_code_id = sc.id
            WHERE ast.is_active = true
        """)
        
        valid_active = cursor.fetchone()[0]
        
        # Check total activations
        cursor.execute("""
            SELECT COUNT(*) 
            FROM activated_strategies
            WHERE is_active = true
        """)
        
        total_active = cursor.fetchone()[0]
        
        print(f"Remaining orphaned records: {remaining_orphaned}")
        print(f"Valid active activations: {valid_active}")
        print(f"Total active activations: {total_active}")
        
        if remaining_orphaned == 0 and valid_active == total_active:
            print(f"\n[SUCCESS] Database cleanup complete!")
            print("✓ All orphaned records removed")
            print("✓ All active activations are now valid")
            print("✓ /api/v1/strategies/list endpoint should work now")
            print("✓ Dashboard should load properly")
        elif remaining_orphaned == 0:
            print(f"\n[PARTIAL SUCCESS] Orphaned records cleaned up")
            print(f"Note: {total_active - valid_active} active activations still reference missing strategy codes")
        else:
            print(f"\n[WARNING] {remaining_orphaned} orphaned records still remain")
        
        # Step 4: Show remaining valid activations
        print(f"\n4. REMAINING VALID ACTIVATIONS:")
        print("-" * 50)
        
        cursor.execute("""
            SELECT ast.id, ast.user_id, sc.name, ast.ticker, ast.quantity, ast.account_id
            FROM activated_strategies ast
            JOIN strategy_codes sc ON ast.strategy_code_id = sc.id
            WHERE ast.is_active = true
            ORDER BY ast.user_id, ast.id
        """)
        
        valid_activations = cursor.fetchall()
        
        if valid_activations:
            print(f"Found {len(valid_activations)} valid active activation(s):")
            for activation in valid_activations:
                act_id, user_id, strategy_name, ticker, quantity, account_id = activation
                print(f"  - ID {act_id}: User {user_id} -> {strategy_name} ({ticker} x{quantity} on {account_id})")
        else:
            print("No valid active activations found")
        
        print(f"\n[COMPLETE] Database cleanup finished")
        print("Try refreshing the dashboard now!")
        
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