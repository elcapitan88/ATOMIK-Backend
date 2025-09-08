#!/usr/bin/env python
"""
Script to activate the stddev_breakout strategy for execution.
This creates an ActivatedStrategy record so the Strategy Engine can execute trades.
"""
import os
from datetime import datetime
import psycopg2
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def main():
    """Activate the stddev_breakout strategy for trading."""
    
    # Get database URL
    database_url = os.getenv("DEV_DATABASE_URL")
    
    if not database_url:
        print("ERROR: DEV_DATABASE_URL not found in .env")
        return
    
    print(f"Connecting to database...")
    
    # Connect to database
    conn = psycopg2.connect(database_url)
    cursor = conn.cursor()
    
    try:
        # Get the strategy code ID
        cursor.execute(
            "SELECT id, name, user_id FROM strategy_codes WHERE name = %s",
            ('stddev_breakout',)
        )
        strategy_code = cursor.fetchone()
        
        if not strategy_code:
            print("ERROR: stddev_breakout strategy not found in database")
            print("Please run add_stddev_strategy_simple.py first")
            return
        
        strategy_code_id = strategy_code[0]
        strategy_name = strategy_code[1]
        user_id = strategy_code[2]
        
        print(f"Found strategy: {strategy_name} (ID: {strategy_code_id}, User: {user_id})")
        
        # Check if already activated
        cursor.execute("""
            SELECT id, is_active, ticker, quantity 
            FROM activated_strategies 
            WHERE strategy_code_id = %s AND is_active = true
        """, (strategy_code_id,))
        
        existing = cursor.fetchone()
        
        if existing:
            print(f"\nStrategy already activated (ID: {existing[0]})")
            print(f"  Ticker: {existing[2]}")
            print(f"  Quantity: {existing[3]}")
            print(f"  Active: {existing[1]}")
        else:
            # Get user's broker account
            cursor.execute("""
                SELECT account_id, broker_name 
                FROM broker_accounts 
                WHERE user_id = %s AND is_active = true 
                LIMIT 1
            """, (user_id,))
            
            account = cursor.fetchone()
            
            if not account:
                print(f"\nWARNING: No active broker account found for user {user_id}")
                print("Creating strategy activation without broker account (for testing)")
                account_id = None
            else:
                account_id = account[0]
                print(f"Using broker account: {account_id} ({account[1]})")
            
            # Create ActivatedStrategy record
            cursor.execute("""
                INSERT INTO activated_strategies (
                    user_id,
                    strategy_type,
                    execution_type,
                    strategy_code_id,
                    ticker,
                    quantity,
                    account_id,
                    is_active,
                    created_at,
                    max_position_size,
                    stop_loss_percent,
                    take_profit_percent
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                RETURNING id
            """, (
                user_id,
                'single',  # strategy_type
                'engine',  # execution_type for Strategy Engine
                strategy_code_id,
                'MNQ',     # Default to MNQ for testing
                1,         # Default quantity
                account_id,
                True,      # is_active
                datetime.utcnow(),
                3,         # max_position_size
                1.0,       # stop_loss_percent (1%)
                2.0        # take_profit_percent (2%)
            ))
            
            new_id = cursor.fetchone()[0]
            conn.commit()
            
            print(f"\nSuccessfully activated stddev_breakout strategy!")
            print(f"  Activation ID: {new_id}")
            print(f"  Symbol: MNQ")
            print(f"  Quantity: 1 contract")
            print(f"  Max Position: 3 contracts")
            print(f"  Stop Loss: 1.0%")
            print(f"  Take Profit: 2.0%")
        
        print("\n==============================================")
        print("NEXT STEPS:")
        print("1. The strategy is now activated and ready")
        print("2. The Strategy Engine will execute trades automatically")
        print("3. Check the Strategy Engine logs for execution status")
        print("==============================================")
        
    except Exception as e:
        print(f"Error: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    main()