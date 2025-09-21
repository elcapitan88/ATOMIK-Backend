#!/usr/bin/env python3
"""
Check database schema to understand table structure.
"""

from sqlalchemy import create_engine, text, inspect

# Database URL
DATABASE_URL = "postgresql://postgres:K2Q71c2OIVd1ZIXm8Ad1BFk5jF03Kj33@metro.proxy.rlwy.net:47089/railway"

# Create engine
engine = create_engine(DATABASE_URL)

def main():
    print("Checking database schema...")
    
    with engine.connect() as conn:
        # Get all tables
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        
        print(f"\nFound {len(tables)} tables")
        print("-" * 40)
        
        # Look for trade-related tables
        trade_tables = [t for t in tables if 'trade' in t.lower() or 'order' in t.lower()]
        print(f"\nTrade-related tables: {trade_tables}")
        
        # Check columns in trades table if it exists
        if 'trades' in tables:
            print("\n\nColumns in 'trades' table:")
            print("-" * 40)
            columns = inspector.get_columns('trades')
            for col in columns:
                print(f"  {col['name']:<20} {col['type']}")
        
        # Check columns in orders table if it exists  
        if 'orders' in tables:
            print("\n\nColumns in 'orders' table:")
            print("-" * 40)
            columns = inspector.get_columns('orders')
            for col in columns:
                print(f"  {col['name']:<20} {col['type']}")
                
        # Check activated_strategies columns
        if 'activated_strategies' in tables:
            print("\n\nColumns in 'activated_strategies' table:")
            print("-" * 40)
            columns = inspector.get_columns('activated_strategies')
            for col in columns:
                if 'position' in col['name'].lower() or 'exit' in col['name'].lower():
                    print(f"  {col['name']:<30} {col['type']}")

if __name__ == "__main__":
    main()