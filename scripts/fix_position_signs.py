#!/usr/bin/env python3
"""
Script to audit and fix position sign issues for std deviation breakout strategies.
Ensures short positions are stored as negative values.
"""

import sys
import os
from datetime import datetime, timedelta

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import SessionLocal
from app.models.strategy import ActivatedStrategy
from app.models.trade import Trade
from sqlalchemy import desc, and_

def analyze_position_history(strategy_id: int, db):
    """Analyze trade history to determine correct current position."""
    
    # Get all trades for this strategy in chronological order
    trades = db.query(Trade).filter(
        Trade.strategy_id == strategy_id
    ).order_by(Trade.timestamp.asc()).all()
    
    calculated_position = 0
    trade_log = []
    
    for trade in trades:
        # Determine position change based on action
        if trade.action == "BUY":
            position_change = trade.quantity
        elif trade.action == "SELL":
            position_change = -trade.quantity
        else:
            continue
            
        old_position = calculated_position
        calculated_position += position_change
        
        trade_log.append({
            'timestamp': trade.timestamp,
            'action': trade.action,
            'quantity': trade.quantity,
            'position_change': position_change,
            'old_position': old_position,
            'new_position': calculated_position,
            'order_id': trade.order_id
        })
    
    return calculated_position, trade_log

def main():
    """Main function to audit and fix position signs."""
    
    db = SessionLocal()
    
    try:
        print("=" * 80)
        print("POSITION SIGN AUDIT AND FIX SCRIPT")
        print("=" * 80)
        print()
        
        # Focus on the problematic strategies
        strategy_ids = [733, 735]
        
        for strategy_id in strategy_ids:
            print(f"\n--- Analyzing Strategy {strategy_id} ---")
            
            # Get the strategy
            strategy = db.query(ActivatedStrategy).filter(
                ActivatedStrategy.id == strategy_id
            ).first()
            
            if not strategy:
                print(f"Strategy {strategy_id} not found")
                continue
            
            print(f"Account: {strategy.account_id}")
            print(f"User ID: {strategy.user_id}")
            print(f"Ticker: {strategy.ticker}")
            print(f"Current DB Position: {strategy.last_known_position}")
            print(f"Last Update: {strategy.last_position_update}")
            
            # Calculate what the position should be based on trade history
            calculated_position, trade_log = analyze_position_history(strategy_id, db)
            
            print(f"\nTrade History Analysis:")
            print("-" * 60)
            
            # Show last 10 trades
            for trade in trade_log[-10:]:
                print(f"{trade['timestamp'].strftime('%Y-%m-%d %H:%M:%S')} | "
                      f"{trade['action']:4} {trade['quantity']:3} | "
                      f"Pos: {trade['old_position']:3} -> {trade['new_position']:3}")
            
            print(f"\nCalculated Position from trades: {calculated_position}")
            print(f"Database Position: {strategy.last_known_position}")
            
            # Check if there's a mismatch
            if strategy.last_known_position != calculated_position:
                print(f"\n⚠️  POSITION MISMATCH DETECTED!")
                print(f"   Database has: {strategy.last_known_position}")
                print(f"   Should be: {calculated_position}")
                
                # Ask for confirmation to fix
                response = input(f"\nFix position for strategy {strategy_id}? (yes/no): ")
                if response.lower() == 'yes':
                    old_position = strategy.last_known_position
                    strategy.last_known_position = calculated_position
                    strategy.last_position_update = datetime.utcnow()
                    db.commit()
                    print(f"✅ Fixed position: {old_position} -> {calculated_position}")
                else:
                    print("Skipped fixing this strategy")
            else:
                print("✅ Position is correct")
        
        # Now check for any strategies with suspicious positive positions
        print("\n" + "=" * 80)
        print("CHECKING FOR OTHER SUSPICIOUS POSITIONS")
        print("=" * 80)
        
        # Find strategies with positive positions that might be shorts
        suspicious_strategies = db.query(ActivatedStrategy).filter(
            ActivatedStrategy.last_known_position > 0,
            ActivatedStrategy.is_active == True
        ).all()
        
        for strategy in suspicious_strategies:
            if strategy.id in strategy_ids:
                continue  # Already handled
                
            # Check last few trades to see if this should be a short
            recent_trades = db.query(Trade).filter(
                Trade.strategy_id == strategy.id
            ).order_by(desc(Trade.timestamp)).limit(5).all()
            
            if recent_trades:
                last_entry = None
                for trade in recent_trades:
                    if trade.action in ["BUY", "SELL"] and "EXIT" not in (trade.comment or "").upper():
                        last_entry = trade
                        break
                
                if last_entry and last_entry.action == "SELL":
                    # Last entry was a SELL, so positive position might be wrong
                    print(f"\n⚠️  Strategy {strategy.id} has positive position {strategy.last_known_position} "
                          f"but last entry was SELL")
                    print(f"   Account: {strategy.account_id}, Ticker: {strategy.ticker}")
                    
                    # Calculate correct position
                    calc_pos, _ = analyze_position_history(strategy.id, db)
                    if calc_pos != strategy.last_known_position:
                        print(f"   Calculated position: {calc_pos}")
                        response = input(f"   Fix this position? (yes/no): ")
                        if response.lower() == 'yes':
                            old_pos = strategy.last_known_position
                            strategy.last_known_position = calc_pos
                            strategy.last_position_update = datetime.utcnow()
                            db.commit()
                            print(f"   ✅ Fixed: {old_pos} -> {calc_pos}")
        
        print("\n" + "=" * 80)
        print("AUDIT COMPLETE")
        print("=" * 80)
        
    except Exception as e:
        print(f"Error: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    main()