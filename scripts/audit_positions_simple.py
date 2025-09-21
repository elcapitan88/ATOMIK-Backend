#!/usr/bin/env python3
"""
Simple script to audit positions using direct SQL queries.
"""

import os
from sqlalchemy import create_engine, text
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Get database URL - use the provided external URL
DATABASE_URL = "postgresql://postgres:K2Q71c2OIVd1ZIXm8Ad1BFk5jF03Kj33@metro.proxy.rlwy.net:47089/railway"

# Create engine
engine = create_engine(DATABASE_URL)

def main():
    print("=" * 80)
    print("POSITION AUDIT - STRATEGIES 733 & 735")
    print("=" * 80)
    print()
    
    with engine.connect() as conn:
        # Query current positions for strategies 733 and 735
        query = text("""
            SELECT 
                s.id as strategy_id,
                s.user_id,
                s.account_id,
                s.ticker,
                s.last_known_position,
                s.last_position_update,
                s.last_exit_type,
                s.partial_exits_count,
                s.is_active
            FROM activated_strategies s
            WHERE s.id IN (733, 735)
            ORDER BY s.id
        """)
        
        strategies = conn.execute(query).fetchall()
        
        for strategy in strategies:
            print(f"\n--- Strategy {strategy.strategy_id} ---")
            print(f"User ID: {strategy.user_id}")
            print(f"Account: {strategy.account_id}")
            print(f"Ticker: {strategy.ticker}")
            print(f"Current Position: {strategy.last_known_position}")
            print(f"Last Update: {strategy.last_position_update}")
            print(f"Last Exit Type: {strategy.last_exit_type}")
            print(f"Active: {strategy.is_active}")
            
            # Get recent orders for this strategy
            orders_query = text("""
                SELECT 
                    o.created_at as timestamp,
                    o.side,
                    o.quantity,
                    o.average_fill_price as price,
                    o.broker_order_id,
                    o.status,
                    o.notes
                FROM orders o
                WHERE o.strategy_id = :strategy_id
                ORDER BY o.created_at DESC
                LIMIT 15
            """)
            
            orders = conn.execute(orders_query, {"strategy_id": strategy.strategy_id}).fetchall()
            
            print(f"\nLast 15 orders:")
            print("-" * 80)
            print(f"{'Timestamp':<20} {'Side':<6} {'Qty':<6} {'Price':<10} {'Status':<10} {'Notes':<20}")
            print("-" * 80)
            
            for order in orders:
                timestamp_str = order.timestamp.strftime('%Y-%m-%d %H:%M:%S') if order.timestamp else 'N/A'
                notes = (order.notes or '')[:20]
                price = order.price if order.price else 0.0
                print(f"{timestamp_str:<20} {order.side:<6} {order.quantity:<6.0f} {price:<10.2f} {order.status:<10} {notes:<20}")
            
            # Calculate position from order history
            all_orders_query = text("""
                SELECT 
                    side,
                    filled_quantity as quantity,
                    status
                FROM orders
                WHERE strategy_id = :strategy_id
                AND status IN ('filled', 'partially_filled')
                ORDER BY created_at ASC
            """)
            
            all_orders = conn.execute(all_orders_query, {"strategy_id": strategy.strategy_id}).fetchall()
            
            calculated_position = 0
            for order in all_orders:
                if order.side == "BUY":
                    calculated_position += order.quantity if order.quantity else 0
                elif order.side == "SELL":
                    calculated_position -= order.quantity if order.quantity else 0
            
            print(f"\n📊 Position Analysis:")
            print(f"   Database Position: {strategy.last_known_position}")
            print(f"   Calculated from trades: {calculated_position}")
            
            if strategy.last_known_position != calculated_position:
                print(f"\n⚠️  MISMATCH DETECTED!")
                print(f"   Difference: {strategy.last_known_position - calculated_position}")
                
                # Suggest fix
                print(f"\n   Suggested SQL to fix:")
                print(f"   UPDATE activated_strategies")
                print(f"   SET last_known_position = {calculated_position},")
                print(f"       last_position_update = NOW()")
                print(f"   WHERE id = {strategy.strategy_id};")
            else:
                print(f"✅ Position matches trade history")
        
        print("\n" + "=" * 80)
        print("CHECKING OTHER STDDEV STRATEGIES")
        print("=" * 80)
        
        # Find all stddev strategies
        stddev_query = text("""
            SELECT 
                s.id as strategy_id,
                s.user_id,
                s.account_id,
                s.ticker,
                s.last_known_position,
                s.is_active,
                sc.name as strategy_name
            FROM activated_strategies s
            JOIN strategy_codes sc ON s.strategy_code_id = sc.id
            WHERE sc.name LIKE '%stddev%' OR sc.name LIKE '%breakout%'
            ORDER BY s.id
        """)
        
        stddev_strategies = conn.execute(stddev_query).fetchall()
        
        print(f"\nFound {len(stddev_strategies)} stddev/breakout strategies:")
        print("-" * 70)
        print(f"{'ID':<6} {'User':<6} {'Account':<12} {'Ticker':<6} {'Position':<8} {'Active':<7} {'Name':<20}")
        print("-" * 70)
        
        for s in stddev_strategies:
            active_str = "Yes" if s.is_active else "No"
            print(f"{s.strategy_id:<6} {s.user_id:<6} {s.account_id:<12} {s.ticker:<6} {s.last_known_position:<8} {active_str:<7} {s.strategy_name:<20}")

if __name__ == "__main__":
    main()