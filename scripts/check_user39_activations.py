#!/usr/bin/env python
"""
Script to check User 39's activated strategies, specifically looking for 
stddev_breakout with quantity 4 on MNQ.
"""
import os
import psycopg2
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def main():
    """Check User 39's strategy activations."""
    
    # Get database URL
    database_url = os.getenv("DEV_DATABASE_URL") or os.getenv("DATABASE_PRIVATE_URL") or os.getenv("DATABASE_URL")
    
    if not database_url:
        print("ERROR: No database URL found in environment variables")
        return
    
    print("=" * 80)
    print("USER 39 - STRATEGY ACTIVATION ANALYSIS")
    print("=" * 80)
    
    # Connect to database
    conn = psycopg2.connect(database_url)
    cursor = conn.cursor()
    
    USER_ID = 39
    
    try:
        # Step 1: Get User 39 info
        print("\n1. USER 39 INFORMATION:")
        print("-" * 60)
        
        cursor.execute("""
            SELECT id, username, email, created_at
            FROM users 
            WHERE id = %s
        """, (USER_ID,))
        
        user = cursor.fetchone()
        if not user:
            print(f"ERROR: User {USER_ID} not found")
            return
        
        user_id, username, email, created_at = user
        print(f"User: {username} ({email})")
        print(f"User ID: {user_id}")
        print(f"Member since: {created_at}")
        
        # Step 2: Get ALL activated strategies for User 39
        print(f"\n2. ALL ACTIVATED STRATEGIES FOR USER 39:")
        print("-" * 60)
        
        cursor.execute("""
            SELECT 
                ast.id as activation_id,
                sc.id as strategy_code_id,
                sc.name as strategy_name,
                ast.ticker,
                ast.quantity,
                ast.account_id,
                ast.is_active,
                ast.strategy_type,
                ast.execution_type,
                ast.created_at,
                ast.updated_at,
                ba.broker_id
            FROM activated_strategies ast
            JOIN strategy_codes sc ON ast.strategy_code_id = sc.id
            LEFT JOIN broker_accounts ba ON ast.account_id = ba.account_id
            WHERE ast.user_id = %s
            ORDER BY ast.is_active DESC, ast.created_at DESC
        """, (USER_ID,))
        
        activations = cursor.fetchall()
        
        if not activations:
            print("No activated strategies found for User 39")
            return
        
        print(f"Found {len(activations)} total activation(s):")
        print()
        
        # Step 3: Analyze each activation
        stddev_activations = []
        other_activations = []
        
        for activation in activations:
            (act_id, strategy_id, strategy_name, ticker, quantity, account_id, 
             is_active, strategy_type, execution_type, created, updated, broker) = activation
            
            status = "ACTIVE" if is_active else "INACTIVE"
            
            print(f"Activation ID: {act_id} ({status})")
            print(f"  Strategy: {strategy_name} (Code ID: {strategy_id})")
            print(f"  Ticker: {ticker}")
            print(f"  Quantity: {quantity}")
            print(f"  Account: {account_id} ({broker})")
            print(f"  Type: {strategy_type}/{execution_type}")
            print(f"  Created: {created}")
            print(f"  Updated: {updated}")
            print()
            
            if 'stddev' in strategy_name.lower():
                stddev_activations.append(activation)
            else:
                other_activations.append(activation)
        
        # Step 4: Focus on stddev_breakout strategies
        print(f"\n3. STDDEV_BREAKOUT SPECIFIC ANALYSIS:")
        print("-" * 60)
        
        if stddev_activations:
            print(f"Found {len(stddev_activations)} stddev-related activation(s):")
            
            for activation in stddev_activations:
                (act_id, strategy_id, strategy_name, ticker, quantity, account_id, 
                 is_active, strategy_type, execution_type, created, updated, broker) = activation
                
                status = "ACTIVE" if is_active else "INACTIVE"
                
                print(f"\n  {strategy_name} - ID {act_id} ({status})")
                print(f"    Ticker: {ticker}")
                print(f"    Quantity: {quantity}")
                print(f"    Account: {account_id} ({broker})")
                
                # Check if this matches the query
                if (ticker == 'MNQ' and quantity == 4 and 
                    'stddev' in strategy_name.lower() and is_active):
                    print(f"    *** MATCHES QUERY: stddev_breakout with qty 4 on MNQ ***")
        else:
            print("No stddev-related strategies found")
        
        # Step 5: Search for quantity 4 specifically
        print(f"\n4. QUANTITY 4 ACTIVATIONS:")
        print("-" * 60)
        
        qty_4_activations = [act for act in activations if act[4] == 4]  # quantity is index 4
        
        if qty_4_activations:
            print(f"Found {len(qty_4_activations)} activation(s) with quantity 4:")
            for activation in qty_4_activations:
                (act_id, strategy_id, strategy_name, ticker, quantity, account_id, 
                 is_active, strategy_type, execution_type, created, updated, broker) = activation
                
                status = "ACTIVE" if is_active else "INACTIVE"
                print(f"  - {strategy_name}: {ticker} x{quantity} on {account_id} ({status})")
        else:
            print("No activations found with quantity 4")
        
        # Step 6: Search for "pro" in strategy names
        print(f"\n5. SEARCHING FOR 'PRO' STRATEGIES:")
        print("-" * 60)
        
        pro_strategies = [act for act in activations if 'pro' in act[2].lower()]  # strategy_name is index 2
        
        if pro_strategies:
            print(f"Found {len(pro_strategies)} 'pro' strategy activation(s):")
            for activation in pro_strategies:
                (act_id, strategy_id, strategy_name, ticker, quantity, account_id, 
                 is_active, strategy_type, execution_type, created, updated, broker) = activation
                
                status = "ACTIVE" if is_active else "INACTIVE"
                print(f"  - {strategy_name}: {ticker} x{quantity} on {account_id} ({status})")
        else:
            print("No 'pro' strategies found")
        
        # Step 7: Final answer to the specific question
        print(f"\n6. ANSWER TO SPECIFIC QUERY:")
        print("-" * 60)
        print("Question: Does User 39 have an activated strategy for")
        print("'standard deviation breakout pro' with qty 4 on MNQ?")
        print()
        
        # Look for exact match
        found_match = False
        for activation in activations:
            (act_id, strategy_id, strategy_name, ticker, quantity, account_id, 
             is_active, strategy_type, execution_type, created, updated, broker) = activation
            
            # Check for variations of "standard deviation breakout pro"
            name_variants = [
                'stddev_breakout_pro',
                'standard deviation breakout pro',
                'stddev breakout pro',
                'standard_deviation_breakout_pro'
            ]
            
            name_lower = strategy_name.lower()
            is_pro_variant = any(variant in name_lower for variant in name_variants)
            
            if (is_pro_variant and ticker == 'MNQ' and quantity == 4 and is_active):
                found_match = True
                print(f"[YES] Found matching activation:")
                print(f"  Strategy: {strategy_name}")
                print(f"  Activation ID: {act_id}")
                print(f"  Ticker: {ticker}")
                print(f"  Quantity: {quantity}")
                print(f"  Account: {account_id} ({broker})")
                print(f"  Status: ACTIVE")
                break
        
        if not found_match:
            print(f"[NO] No matching activation found for:")
            print(f"  - Strategy name containing 'pro' or 'stddev_breakout_pro'")
            print(f"  - Ticker: MNQ")
            print(f"  - Quantity: 4")
            print(f"  - Status: ACTIVE")
        
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    main()