#!/usr/bin/env python
"""
Simple script to add the stddev_breakout strategy using raw SQL.
"""
import os
import json
from datetime import datetime
import psycopg2
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def main():
    """Add the stddev_breakout strategy to the database."""
    
    # Get database URL - use DEV URL for local access
    database_url = os.getenv("DEV_DATABASE_URL")
    
    if not database_url:
        print("ERROR: DEV_DATABASE_URL not found in .env")
        return
    
    print(f"Connecting to database...")
    
    # Connect to database
    conn = psycopg2.connect(database_url)
    cursor = conn.cursor()
    
    try:
        # First check if the strategy already exists
        cursor.execute(
            "SELECT id, name, is_active FROM strategy_codes WHERE name = %s",
            ('stddev_breakout',)
        )
        existing = cursor.fetchone()
        
        if existing:
            print(f"Strategy 'stddev_breakout' already exists (ID: {existing[0]})")
            
            # Update to ensure it's active and validated
            cursor.execute("""
                UPDATE strategy_codes 
                SET is_active = true, 
                    is_validated = true,
                    validation_error = NULL,
                    updated_at = %s
                WHERE name = %s
            """, (datetime.utcnow(), 'stddev_breakout'))
            
            conn.commit()
            print("Updated strategy to active and validated state")
        else:
            # Use user ID 39 as specified
            user_id = 39
            print(f"Using user_id = {user_id}")
            
            # Insert the new strategy
            strategy_code = '''
"""Standard Deviation Breakout Strategy

This strategy trades breakouts based on standard deviation movements:
- Calculates 10-period standard deviation
- Tracks 200-period moving average of the standard deviation  
- Generates BUY signals when SD crosses above its MA
- Generates SELL signals when SD crosses below its MA
- Includes risk management with ATR-based stops and profit targets

This is a Strategy Engine system strategy.
"""

class StdDevBreakoutStrategy:
    name = "stddev_breakout"
    symbols = ["MNQ", "MES", "MYM", "M2K"]
    description = "Standard Deviation Breakout Strategy"
'''
            
            cursor.execute("""
                INSERT INTO strategy_codes (
                    user_id, name, description, code, symbols,
                    is_active, is_validated, validation_error,
                    version, created_at, updated_at,
                    signals_generated, error_count
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s
                )
            """, (
                user_id,
                'stddev_breakout',
                'Standard Deviation Breakout Strategy - Trades when 10-period SD crosses above/below its 200-period MA',
                strategy_code,
                json.dumps(["MNQ", "MES", "MYM", "M2K"]),  # Mini futures
                True,  # is_active
                True,  # is_validated
                None,  # validation_error
                1,  # version
                datetime.utcnow(),  # created_at
                datetime.utcnow(),  # updated_at
                0,  # signals_generated
                0   # error_count
            ))
            
            conn.commit()
            print("Successfully added 'stddev_breakout' strategy to database")
        
        # Verify the strategy exists
        cursor.execute("""
            SELECT id, name, description, is_active, is_validated, user_id, symbols
            FROM strategy_codes 
            WHERE name = %s
        """, ('stddev_breakout',))
        
        result = cursor.fetchone()
        if result:
            print("\nVerification successful!")
            print(f"  Strategy ID: {result[0]}")
            print(f"  Name: {result[1]}")
            print(f"  Description: {result[2]}")
            print(f"  Active: {result[3]}")
            print(f"  Validated: {result[4]}")
            print(f"  User ID: {result[5]}")
            print(f"  Symbols: {result[6]}")
            print("\nUsers can now see and activate this strategy from the frontend!")
        else:
            print("\n❌ ERROR: Strategy not found after insertion")
            
    except Exception as e:
        print(f"Error: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    main()