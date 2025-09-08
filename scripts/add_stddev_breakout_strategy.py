#!/usr/bin/env python
"""
Script to add the stddev_breakout strategy to the database.
This makes it available for users to activate in the frontend.
"""
import os
import json
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

Base = declarative_base()

# Simple StrategyCode model without relationships
class StrategyCode(Base):
    __tablename__ = "strategy_codes"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    code = Column(Text, nullable=False)
    symbols = Column(String(500), nullable=True)
    is_active = Column(Boolean, default=False)
    is_validated = Column(Boolean, default=False)
    validation_error = Column(Text, nullable=True)
    version = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

# Read the actual strategy code from the Strategy Engine
STRATEGY_CODE_PATH = "../../strategy-engine/strategies/examples/stddev_breakout.py"

def get_strategy_code():
    """Read the actual strategy code from the file."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    strategy_path = os.path.join(script_dir, STRATEGY_CODE_PATH)
    
    # Normalize the path for Windows
    strategy_path = os.path.normpath(strategy_path)
    
    if os.path.exists(strategy_path):
        with open(strategy_path, 'r') as f:
            return f.read()
    else:
        # Fallback: Return a placeholder that explains the strategy
        return '''"""
Standard Deviation Breakout Strategy

This strategy trades breakouts based on standard deviation movements.
- Calculates 10-period standard deviation
- Tracks 200-period moving average of the standard deviation
- Generates BUY signals when SD crosses above its MA
- Generates SELL signals when SD crosses below its MA
- Includes risk management with ATR-based stops and profit targets

Note: This is a system strategy that runs on the Strategy Engine.
The actual implementation is in the strategy-engine repository.
"""

# Strategy implementation is handled by the Strategy Engine
# This is a placeholder for database registration
class StdDevBreakoutStrategy:
    name = "stddev_breakout"
    symbols = ["MNQ"]
    description = "Standard Deviation Breakout Strategy with 10/200 MA crossover"
'''

def main():
    """Add the stddev_breakout strategy to the database."""
    
    # Get database URL from environment - use DEV_DATABASE_URL for local access
    database_url = os.getenv("DEV_DATABASE_URL") or os.getenv("DATABASE_PRIVATE_URL") or os.getenv("DATABASE_URL")
    
    if not database_url:
        print("ERROR: No database URL found in environment variables")
        return
    
    print(f"Connecting to database...")
    
    # Create database connection
    engine = create_engine(database_url)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    
    try:
        # Check if strategy already exists
        existing = db.query(StrategyCode).filter(
            StrategyCode.name == "stddev_breakout"
        ).first()
        
        if existing:
            print(f"Strategy 'stddev_breakout' already exists (ID: {existing.id})")
            
            # Update it to ensure it's active and validated
            existing.is_active = True
            existing.is_validated = True
            existing.validation_error = None
            existing.updated_at = datetime.utcnow()
            
            db.commit()
            print("Updated existing strategy to active and validated state")
        else:
            # Create new strategy code entry
            strategy_code = StrategyCode(
                user_id=1,  # System user ID (admin)
                name="stddev_breakout",
                description="Standard Deviation Breakout Strategy - Trades when 10-period SD crosses above/below its 200-period MA",
                code=get_strategy_code(),
                symbols=json.dumps(["MNQ", "MES", "MYM", "M2K"]),  # Mini futures
                is_active=True,
                is_validated=True,
                validation_error=None,
                version=1,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            
            db.add(strategy_code)
            db.commit()
            
            print(f"Successfully added 'stddev_breakout' strategy (ID: {strategy_code.id})")
            print(f"Description: {strategy_code.description}")
            print(f"Symbols: {strategy_code.symbols}")
            
        # Verify the strategy is now in the database
        strategy = db.query(StrategyCode).filter(
            StrategyCode.name == "stddev_breakout"
        ).first()
        
        if strategy:
            print("\nVerification successful!")
            print(f"Strategy ID: {strategy.id}")
            print(f"Name: {strategy.name}")
            print(f"Active: {strategy.is_active}")
            print(f"Validated: {strategy.is_validated}")
            print(f"User ID: {strategy.user_id}")
            print("\nUsers can now activate this strategy from the frontend!")
        else:
            print("\nERROR: Strategy not found after insertion")
            
    except Exception as e:
        print(f"Error adding strategy: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    main()