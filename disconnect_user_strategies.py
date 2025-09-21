#!/usr/bin/env python3
"""
Script to disconnect and delete all activated strategies for a specific user.
This script safely removes all strategies and their associated data for user ID 163.
"""

import os
import sys
import asyncio
import logging
from typing import List
from sqlalchemy.orm import Session
from sqlalchemy import text

# Add the app directory to Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from app.db.session import SessionLocal, engine
from app.models.strategy import ActivatedStrategy, strategy_follower_quantities
from app.models.trade import Trade
from app.models.order import Order
from app.models.webhook import Webhook

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

USER_ID = 163

def disconnect_and_delete_user_strategies(user_id: int) -> dict:
    """
    Disconnect and delete all activated strategies for a specific user.
    
    Args:
        user_id (int): The ID of the user whose strategies should be deleted
        
    Returns:
        dict: Summary of the deletion operation
    """
    db = SessionLocal()
    summary = {
        'user_id': user_id,
        'strategies_found': 0,
        'strategies_deleted': 0,
        'trades_deleted': 0,
        'orders_deleted': 0,
        'follower_relationships_deleted': 0,
        'errors': []
    }
    
    try:
        # Find all activated strategies for the user
        strategies = db.query(ActivatedStrategy).filter(
            ActivatedStrategy.user_id == user_id
        ).all()
        
        summary['strategies_found'] = len(strategies)
        
        if not strategies:
            logger.info(f"No activated strategies found for user {user_id}")
            return summary
        
        logger.info(f"Found {len(strategies)} activated strategies for user {user_id}")
        
        for strategy in strategies:
            try:
                logger.info(f"Processing strategy {strategy.id} - {strategy.ticker} ({strategy.strategy_type})")
                
                # Delete associated trades
                trades_deleted = db.query(Trade).filter(Trade.strategy_id == strategy.id).count()
                db.query(Trade).filter(Trade.strategy_id == strategy.id).delete()
                summary['trades_deleted'] += trades_deleted
                logger.info(f"  Deleted {trades_deleted} trades for strategy {strategy.id}")
                
                # Delete associated orders
                orders_deleted = db.query(Order).filter(Order.strategy_id == strategy.id).count()
                db.query(Order).filter(Order.strategy_id == strategy.id).delete()
                summary['orders_deleted'] += orders_deleted
                logger.info(f"  Deleted {orders_deleted} orders for strategy {strategy.id}")
                
                # Delete follower relationships (for multiple strategy types)
                if strategy.strategy_type == 'multiple':
                    follower_relationships = db.execute(
                        text("SELECT COUNT(*) FROM strategy_follower_quantities WHERE strategy_id = :strategy_id"),
                        {"strategy_id": strategy.id}
                    ).scalar()
                    
                    if follower_relationships > 0:
                        db.execute(
                            text("DELETE FROM strategy_follower_quantities WHERE strategy_id = :strategy_id"),
                            {"strategy_id": strategy.id}
                        )
                        summary['follower_relationships_deleted'] += follower_relationships
                        logger.info(f"  Deleted {follower_relationships} follower relationships for strategy {strategy.id}")
                
                # Mark strategy as inactive first (safer approach)
                strategy.is_active = False
                db.commit()
                logger.info(f"  Marked strategy {strategy.id} as inactive")
                
                # Delete the strategy itself
                db.delete(strategy)
                db.commit()
                summary['strategies_deleted'] += 1
                logger.info(f"  Successfully deleted strategy {strategy.id}")
                
            except Exception as e:
                error_msg = f"Error processing strategy {strategy.id}: {str(e)}"
                logger.error(error_msg)
                summary['errors'].append(error_msg)
                db.rollback()
                continue
        
        logger.info(f"Completed deletion process for user {user_id}")
        logger.info(f"Summary: {summary}")
        
    except Exception as e:
        error_msg = f"Critical error during deletion process: {str(e)}"
        logger.error(error_msg)
        summary['errors'].append(error_msg)
        db.rollback()
        
    finally:
        db.close()
    
    return summary

def verify_deletion(user_id: int) -> dict:
    """
    Verify that all strategies have been properly deleted for the user.
    
    Args:
        user_id (int): The ID of the user to verify
        
    Returns:
        dict: Verification results
    """
    db = SessionLocal()
    verification = {
        'user_id': user_id,
        'remaining_strategies': 0,
        'remaining_trades': 0,
        'remaining_orders': 0,
        'remaining_follower_relationships': 0
    }
    
    try:
        # Check for remaining strategies
        remaining_strategies = db.query(ActivatedStrategy).filter(
            ActivatedStrategy.user_id == user_id
        ).count()
        verification['remaining_strategies'] = remaining_strategies
        
        # Check for remaining trades associated with the user's strategies
        # Note: This is a more complex query since we need to join through strategies
        remaining_trades = db.execute(
            text("""
                SELECT COUNT(t.id) 
                FROM trades t 
                JOIN activated_strategies s ON t.strategy_id = s.id 
                WHERE s.user_id = :user_id
            """),
            {"user_id": user_id}
        ).scalar() or 0
        verification['remaining_trades'] = remaining_trades
        
        # Check for remaining orders
        remaining_orders = db.execute(
            text("""
                SELECT COUNT(o.id) 
                FROM orders o 
                JOIN activated_strategies s ON o.strategy_id = s.id 
                WHERE s.user_id = :user_id
            """),
            {"user_id": user_id}
        ).scalar() or 0
        verification['remaining_orders'] = remaining_orders
        
        # Check for remaining follower relationships
        remaining_followers = db.execute(
            text("""
                SELECT COUNT(*) 
                FROM strategy_follower_quantities sfq 
                JOIN activated_strategies s ON sfq.strategy_id = s.id 
                WHERE s.user_id = :user_id
            """),
            {"user_id": user_id}
        ).scalar() or 0
        verification['remaining_follower_relationships'] = remaining_followers
        
    except Exception as e:
        logger.error(f"Error during verification: {str(e)}")
        verification['error'] = str(e)
    finally:
        db.close()
    
    return verification

def main():
    """Main function to execute the strategy deletion process."""
    logger.info(f"Starting strategy deletion process for user {USER_ID}")
    logger.info("=" * 60)
    
    # Confirm database connection
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        logger.info("Database connection successful")
    except Exception as e:
        logger.error(f"Database connection failed: {str(e)}")
        return
    
    # Get user confirmation
    print(f"\nWARNING: This will permanently delete ALL activated strategies for user ID {USER_ID}")
    print("This action cannot be undone!")
    print("\nThis includes:")
    print("- All activated strategies")
    print("- All associated trades")
    print("- All associated orders") 
    print("- All follower relationships")
    
    confirm = input(f"\nDo you want to proceed with deleting all strategies for user {USER_ID}? (yes/no): ")
    
    if confirm.lower() != 'yes':
        logger.info("Operation cancelled by user")
        return
    
    # Perform the deletion
    logger.info("Starting deletion process...")
    summary = disconnect_and_delete_user_strategies(USER_ID)
    
    # Display results
    print("\n" + "=" * 60)
    print("DELETION SUMMARY")
    print("=" * 60)
    print(f"User ID: {summary['user_id']}")
    print(f"Strategies found: {summary['strategies_found']}")
    print(f"Strategies deleted: {summary['strategies_deleted']}")
    print(f"Trades deleted: {summary['trades_deleted']}")
    print(f"Orders deleted: {summary['orders_deleted']}")
    print(f"Follower relationships deleted: {summary['follower_relationships_deleted']}")
    
    if summary['errors']:
        print(f"\nErrors encountered: {len(summary['errors'])}")
        for error in summary['errors']:
            print(f"  - {error}")
    
    # Verify deletion
    logger.info("Verifying deletion...")
    verification = verify_deletion(USER_ID)
    
    print("\n" + "=" * 60)
    print("VERIFICATION RESULTS")
    print("=" * 60)
    print(f"Remaining strategies: {verification['remaining_strategies']}")
    print(f"Remaining trades: {verification['remaining_trades']}")
    print(f"Remaining orders: {verification['remaining_orders']}")
    print(f"Remaining follower relationships: {verification['remaining_follower_relationships']}")
    
    if (verification['remaining_strategies'] == 0 and 
        verification['remaining_trades'] == 0 and 
        verification['remaining_orders'] == 0 and 
        verification['remaining_follower_relationships'] == 0):
        print("\n✅ SUCCESS: All strategies and associated data have been successfully deleted!")
    else:
        print("\n❌ WARNING: Some data may still remain. Please check the verification results above.")
    
    logger.info("Script completed")

if __name__ == "__main__":
    main()