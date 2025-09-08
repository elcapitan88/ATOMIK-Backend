#!/usr/bin/env python
"""
Script to revert User 144 to original state - remove ALL stddev_breakout activations.
This will completely remove User 144 from the stddev_breakout strategy.
"""
import os
import psycopg2
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def main():
    """Revert User 144 to original state before any stddev_breakout activations."""
    
    # Get database URL
    database_url = os.getenv("DEV_DATABASE_URL") or os.getenv("DATABASE_PRIVATE_URL") or os.getenv("DATABASE_URL")
    
    if not database_url:
        print("ERROR: No database URL found in environment variables")
        return
    
    print("=" * 70)
    print("REVERTING USER 144 TO ORIGINAL STATE")
    print("Removing ALL stddev_breakout strategy activations")
    print("=" * 70)
    
    # Connect to database
    conn = psycopg2.connect(database_url)
    cursor = conn.cursor()
    
    USER_ID = 144
    
    try:
        # Step 1: Find all activations for User 144
        print("\n1. FINDING ALL ACTIVATIONS FOR USER 144:")
        print("-" * 50)
        
        cursor.execute("""
            SELECT 
                ast.id,
                ast.account_id,
                ast.is_active,
                ast.ticker,
                sc.name as strategy_name
            FROM activated_strategies ast
            JOIN strategy_codes sc ON ast.strategy_code_id = sc.id
            WHERE ast.user_id = %s AND sc.name = 'stddev_breakout'
            ORDER BY ast.id
        """, (USER_ID,))
        
        activations = cursor.fetchall()
        
        if not activations:
            print("No stddev_breakout activations found for User 144")
            print("User is already in original state!")
            return
        
        print(f"Found {len(activations)} stddev_breakout activation(s) to remove:")
        for activation in activations:
            act_id, account_id, is_active, ticker, strategy = activation
            status = "ACTIVE" if is_active else "inactive"
            print(f"  - ID {act_id}: Account {account_id}, {ticker} ({status})")
        
        # Step 2: Delete ALL activations
        print(f"\n2. REMOVING ACTIVATIONS:")
        print("-" * 50)
        
        activation_ids = [act[0] for act in activations]
        
        # Delete all activations for User 144 on stddev_breakout
        cursor.execute("""
            DELETE FROM activated_strategies 
            WHERE id = ANY(%s)
            RETURNING id
        """, (activation_ids,))
        
        deleted = cursor.fetchall()
        print(f"Deleted {len(deleted)} activation(s):")
        for del_id in deleted:
            print(f"  - Removed activation ID {del_id[0]}")
        
        # Commit the deletions
        conn.commit()
        
        # Step 3: Verify User 144 has no stddev_breakout activations
        print(f"\n3. VERIFICATION:")
        print("-" * 50)
        
        cursor.execute("""
            SELECT COUNT(*) 
            FROM activated_strategies ast
            JOIN strategy_codes sc ON ast.strategy_code_id = sc.id
            WHERE ast.user_id = %s AND sc.name = 'stddev_breakout'
        """, (USER_ID,))
        
        count = cursor.fetchone()[0]
        
        if count == 0:
            print("[SUCCESS] User 144 has been completely removed from stddev_breakout")
            print("  - All activations deleted")
            print("  - User 144 will NOT receive any stddev_breakout trades")
            print("  - Dashboard should work normally now")
        else:
            print(f"[WARNING] {count} activation(s) still remain - manual cleanup may be needed")
        
        # Step 4: Show User 144's remaining strategies (if any)
        print(f"\n4. USER 144'S REMAINING STRATEGIES:")
        print("-" * 50)
        
        cursor.execute("""
            SELECT 
                ast.id,
                sc.name,
                ast.account_id,
                ast.ticker,
                ast.is_active
            FROM activated_strategies ast
            JOIN strategy_codes sc ON ast.strategy_code_id = sc.id
            WHERE ast.user_id = %s
            ORDER BY ast.is_active DESC, ast.created_at DESC
        """, (USER_ID,))
        
        remaining = cursor.fetchall()
        
        if remaining:
            print(f"User 144 still has {len(remaining)} other strategy activation(s):")
            for strategy in remaining:
                act_id, name, account_id, ticker, is_active = strategy
                status = "ACTIVE" if is_active else "inactive"
                print(f"  - {name}: Account {account_id}, {ticker} ({status})")
        else:
            print("User 144 has no active strategies")
        
        print(f"\n[COMPLETE]")
        print(f"User 144 has been reverted to original state")
        print(f"Dashboard should load normally now")
        print(f"Restart Strategy Engine if needed")
        
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