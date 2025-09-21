#!/usr/bin/env python3
"""
Direct SQL script to check and fix position signs for strategies 733 and 735.
"""

from sqlalchemy import create_engine, text
from datetime import datetime

# Database URL
DATABASE_URL = "postgresql://postgres:K2Q71c2OIVd1ZIXm8Ad1BFk5jF03Kj33@metro.proxy.rlwy.net:47089/railway"

# Create engine
engine = create_engine(DATABASE_URL)

def main():
    print("=" * 80)
    print("POSITION SIGN FIX FOR STRATEGIES 733 & 735")
    print("=" * 80)
    print()
    
    with engine.connect() as conn:
        # First, let's check current positions
        check_query = text("""
            SELECT 
                s.id as strategy_id,
                s.user_id,
                s.account_id,
                s.ticker,
                s.last_known_position,
                s.last_position_update,
                s.is_active
            FROM activated_strategies s
            WHERE s.id IN (733, 735)
            ORDER BY s.id
        """)
        
        strategies = conn.execute(check_query).fetchall()
        
        print("Current positions:")
        print("-" * 60)
        for strategy in strategies:
            print(f"Strategy {strategy.strategy_id}:")
            print(f"  User: {strategy.user_id}, Account: {strategy.account_id}")
            print(f"  Position: {strategy.last_known_position}")
            print(f"  Last Update: {strategy.last_position_update}")
            print()
        
        # Now let's calculate what the positions SHOULD be based on orders
        print("Calculating correct positions from order history...")
        print("-" * 60)
        
        for strategy in strategies:
            # First check what status values exist
            status_query = text("""
                SELECT DISTINCT status, COUNT(*) as count
                FROM orders
                WHERE strategy_id = :strategy_id
                GROUP BY status
            """)
            
            status_results = conn.execute(status_query, {"strategy_id": strategy.strategy_id}).fetchall()
            print(f"Order statuses for strategy {strategy.strategy_id}:")
            for status in status_results:
                print(f"  {status.status}: {status.count} orders")
            
            # Get all orders regardless of status to see the data
            calc_query = text("""
                SELECT 
                    o.side,
                    o.status,
                    COALESCE(o.filled_quantity, o.quantity) as qty
                FROM orders o
                WHERE o.strategy_id = :strategy_id
                ORDER BY o.created_at ASC
            """)
            
            orders = conn.execute(calc_query, {"strategy_id": strategy.strategy_id}).fetchall()
            
            # Calculate position (only count filled orders)
            calculated_position = 0
            buy_total = 0
            sell_total = 0
            
            print(f"Order details:")
            for order in orders:
                print(f"  {order.side} {order.qty} - Status: {order.status}")
                # Only count filled orders for position calculation
                if order.status in ['filled', 'FILLED', 'completed', 'COMPLETED']:
                    if order.side == "BUY":
                        calculated_position += order.qty
                        buy_total += order.qty
                    elif order.side == "SELL" or order.side == "SLL":  # Handle potential typo
                        calculated_position -= order.qty
                        sell_total += order.qty
            
            print(f"\nStrategy {strategy.strategy_id}:")
            print(f"  Total BUY orders: {buy_total}")
            print(f"  Total SELL orders: {sell_total}")
            print(f"  Calculated position: {calculated_position}")
            print(f"  Database position: {strategy.last_known_position}")
            
            if calculated_position != strategy.last_known_position:
                print(f"  WARNING MISMATCH! Difference: {strategy.last_known_position - calculated_position}")
                
                # Ask for confirmation
                response = input(f"\n  Fix strategy {strategy.strategy_id} position from {strategy.last_known_position} to {calculated_position}? (yes/no): ")
                
                if response.lower() == 'yes':
                    # Update the position
                    update_query = text("""
                        UPDATE activated_strategies
                        SET last_known_position = :new_position,
                            last_position_update = :update_time
                        WHERE id = :strategy_id
                    """)
                    
                    conn.execute(update_query, {
                        "new_position": calculated_position,
                        "update_time": datetime.utcnow(),
                        "strategy_id": strategy.strategy_id
                    })
                    conn.commit()
                    print(f"  SUCCESS Updated position to {calculated_position}")
                else:
                    print("  Skipped")
            else:
                print(f"  SUCCESS Position is correct")
        
        # Verify the updates
        print("\n" + "=" * 60)
        print("VERIFICATION - Final positions:")
        print("-" * 60)
        
        final_check = conn.execute(check_query).fetchall()
        for strategy in final_check:
            print(f"Strategy {strategy.strategy_id}: Position = {strategy.last_known_position}")
        
        print("\nPosition audit complete!")

if __name__ == "__main__":
    main()