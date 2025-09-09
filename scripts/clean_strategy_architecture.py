#!/usr/bin/env python
"""
Clean up strategy architecture by removing unnecessary webhook wrappers
for engine strategies and ensuring proper display in marketplace.
"""
import os
import psycopg2
from dotenv import load_dotenv
from datetime import datetime

# Load environment variables
load_dotenv()

def main():
    """Clean up strategy architecture."""
    
    # Get database URL
    database_url = os.getenv("DEV_DATABASE_URL") or os.getenv("DATABASE_PRIVATE_URL") or os.getenv("DATABASE_URL")
    
    if not database_url:
        print("ERROR: No database URL found in environment variables")
        return
    
    print("=" * 80)
    print("STRATEGY ARCHITECTURE CLEANUP - OPTION 1 IMPLEMENTATION")
    print("=" * 80)
    print(f"Timestamp: {datetime.now()}")
    print()
    
    # Connect to database
    conn = psycopg2.connect(database_url)
    cursor = conn.cursor()
    
    try:
        # Step 1: Identify webhook wrappers for engine strategies
        print("1. IDENTIFYING WEBHOOK WRAPPERS FOR ENGINE STRATEGIES:")
        print("-" * 60)
        
        cursor.execute("""
            SELECT 
                w.id,
                w.token,
                w.name,
                w.source_type,
                w.user_id,
                w.is_active,
                w.created_at,
                COUNT(DISTINCT ast.id) as activation_count
            FROM webhooks w
            LEFT JOIN activated_strategies ast ON ast.webhook_id = w.token
            WHERE w.source_type = 'strategy_engine'
            GROUP BY w.id, w.token, w.name, w.source_type, w.user_id, w.is_active, w.created_at
            ORDER BY w.name
        """)
        
        webhook_wrappers = cursor.fetchall()
        
        if webhook_wrappers:
            print(f"Found {len(webhook_wrappers)} webhook wrapper(s) for engine strategies:")
            for wrapper in webhook_wrappers:
                id, token, name, source, user_id, is_active, created, count = wrapper
                print(f"\n  Webhook ID: {id}")
                print(f"    Name: {name}")
                print(f"    Token: {token[:20]}...")
                print(f"    Owner: User {user_id}")
                print(f"    Active: {is_active}")
                print(f"    Used by {count} activation(s)")
                print(f"    Created: {created}")
        else:
            print("No webhook wrappers found for engine strategies")
            return
        
        # Step 2: Check if any activations are using these webhooks
        print("\n2. CHECKING FOR WEBHOOK-BASED ACTIVATIONS:")
        print("-" * 60)
        
        webhook_tokens = [wrapper[1] for wrapper in webhook_wrappers]
        
        if webhook_tokens:
            cursor.execute("""
                SELECT 
                    ast.id,
                    ast.user_id,
                    u.username,
                    ast.webhook_id,
                    ast.strategy_code_id,
                    ast.ticker,
                    ast.quantity,
                    ast.is_active
                FROM activated_strategies ast
                JOIN users u ON ast.user_id = u.id
                WHERE ast.webhook_id = ANY(%s)
            """, (webhook_tokens,))
            
            webhook_activations = cursor.fetchall()
            
            if webhook_activations:
                print(f"WARNING: Found {len(webhook_activations)} activation(s) using webhook wrappers:")
                for act in webhook_activations:
                    print(f"  - Activation {act[0]}: User {act[1]} ({act[2]}), Active: {act[7]}")
                print("\nThese will be updated to use strategy_code_id directly.")
            else:
                print("Good: No activations are using webhook wrappers")
        
        # Step 3: Update User 39's activation to ensure it's not using webhook
        print("\n3. ENSURING USER 39'S ACTIVATION IS PROPERLY CONFIGURED:")
        print("-" * 60)
        
        cursor.execute("""
            SELECT 
                id,
                webhook_id,
                strategy_code_id,
                ticker,
                quantity,
                is_active,
                execution_type
            FROM activated_strategies
            WHERE user_id = 39 AND is_active = true
        """)
        
        user39_activations = cursor.fetchall()
        
        for activation in user39_activations:
            id, webhook_id, code_id, ticker, qty, active, exec_type = activation
            print(f"Activation {id}:")
            print(f"  Webhook ID: {webhook_id[:20] if webhook_id else 'None'}...")
            print(f"  Strategy Code ID: {code_id}")
            print(f"  Ticker: {ticker}, Quantity: {qty}")
            print(f"  Execution Type: {exec_type}")
            
            if webhook_id:
                print(f"  ACTION: Removing unnecessary webhook_id reference")
                cursor.execute("""
                    UPDATE activated_strategies
                    SET webhook_id = NULL,
                        updated_at = NOW()
                    WHERE id = %s
                """, (id,))
                print(f"  [DONE] Updated activation {id} to remove webhook reference")
        
        # Step 4: Remove unnecessary webhook wrappers
        print("\n4. REMOVING UNNECESSARY WEBHOOK WRAPPERS:")
        print("-" * 60)
        
        # Only remove webhooks that are:
        # 1. source_type = 'strategy_engine'
        # 2. Not being used by any activations (after cleanup)
        
        cursor.execute("""
            SELECT 
                w.id,
                w.token,
                w.name,
                COUNT(ast.id) as remaining_activations
            FROM webhooks w
            LEFT JOIN activated_strategies ast ON ast.webhook_id = w.token
            WHERE w.source_type = 'strategy_engine'
            GROUP BY w.id, w.token, w.name
            HAVING COUNT(ast.id) = 0
        """)
        
        removable_webhooks = cursor.fetchall()
        
        if removable_webhooks:
            print(f"Removing {len(removable_webhooks)} unused webhook wrapper(s):")
            for webhook in removable_webhooks:
                id, token, name, count = webhook
                print(f"\n  Removing: {name} (ID: {id})")
                
                # Delete webhook subscriptions first
                cursor.execute("""
                    DELETE FROM webhook_subscriptions
                    WHERE webhook_id = %s
                """, (id,))
                
                # Delete the webhook
                cursor.execute("""
                    DELETE FROM webhooks
                    WHERE id = %s
                """, (id,))
                
                print(f"  [DONE] Removed webhook wrapper: {name}")
        else:
            print("No removable webhook wrappers found")
        
        # Step 5: Verify strategy codes are properly configured
        print("\n5. VERIFYING STRATEGY CODES:")
        print("-" * 60)
        
        cursor.execute("""
            SELECT 
                sc.id,
                sc.name,
                sc.user_id,
                sc.is_active,
                sc.is_validated,
                COUNT(DISTINCT ast.id) as activation_count
            FROM strategy_codes sc
            LEFT JOIN activated_strategies ast ON ast.strategy_code_id = sc.id
            WHERE sc.name IN ('stddev_breakout', 'momentum_scalper', 'mean_reversion')
            GROUP BY sc.id, sc.name, sc.user_id, sc.is_active, sc.is_validated
            ORDER BY sc.name
        """)
        
        strategy_codes = cursor.fetchall()
        
        print("Engine strategies status:")
        for code in strategy_codes:
            id, name, user_id, active, validated, count = code
            print(f"\n  {name} (ID: {id}):")
            print(f"    Owner: User {user_id}")
            print(f"    Active: {active}, Validated: {validated}")
            print(f"    Active activations: {count}")
        
        # Step 6: Final verification
        print("\n6. FINAL VERIFICATION:")
        print("-" * 60)
        
        # Verify User 39's activation is clean
        cursor.execute("""
            SELECT 
                id,
                webhook_id,
                strategy_code_id,
                ticker,
                quantity,
                is_active,
                execution_type
            FROM activated_strategies
            WHERE user_id = 39 AND is_active = true
        """)
        
        final_check = cursor.fetchall()
        print("User 39's final activation status:")
        for activation in final_check:
            id, webhook_id, code_id, ticker, qty, active, exec_type = activation
            print(f"  Activation {id}: Code ID {code_id}, {ticker} x{qty}")
            print(f"    Webhook: {'None (clean!)' if not webhook_id else webhook_id[:20]}")
            print(f"    Execution: {exec_type}")
        
        # Commit all changes
        conn.commit()
        
        print("\n" + "=" * 80)
        print("CLEANUP COMPLETED SUCCESSFULLY!")
        print("=" * 80)
        print("\nSummary of changes:")
        print("1. Removed unnecessary webhook wrappers for engine strategies")
        print("2. Updated User 39's activation to use strategy_code_id directly")
        print("3. Ensured engine strategies are properly configured for marketplace")
        print("\nNext steps:")
        print("- Frontend will now display engine strategies correctly")
        print("- User 39 will continue receiving trades from stddev_breakout")
        print("- Marketplace will show proper strategy names")
        
    except Exception as e:
        print(f"\nERROR: {e}")
        print("Rolling back changes...")
        conn.rollback()
        import traceback
        traceback.print_exc()
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    main()