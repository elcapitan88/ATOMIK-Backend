"""
Position tracking service for managing and caching trading positions.
Supports partial exit calculations and position synchronization with brokers.
"""

from typing import Optional, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session
import logging
import json
from redis.exceptions import RedisError

from ..core.redis_manager import get_redis_connection
from ..core.brokers.base import BaseBroker
from ..models.broker import BrokerAccount
from ..core.enhanced_logging import get_enhanced_logger, logging_context

logger = get_enhanced_logger(__name__)


class PositionService:
    """Service for tracking and managing trading positions across accounts."""
    
    def __init__(self, db: Session):
        self.db = db
        self._cache_ttl = 3600  # Cache positions for 1 hour (long enough for trading sessions)
        
    async def get_current_position(
        self, 
        account_id: str, 
        symbol: str,
        broker: Optional[BaseBroker] = None,
        account: Optional[BrokerAccount] = None,
        strategy_id: Optional[int] = None
    ) -> int:
        """
        Get current position for a symbol in an account.
        Uses database tracking as primary source with broker API as fallback.
        
        Args:
            account_id: The broker account ID
            symbol: The trading symbol/ticker
            broker: Optional broker instance (will be fetched if not provided)
            account: Optional account instance (will be fetched if not provided)
            strategy_id: Optional strategy ID for database position lookup
            
        Returns:
            Current position quantity (positive for long, negative for short, 0 for flat)
        """
        with logging_context(account_id=account_id, symbol=symbol):
            try:
                # PRIORITY 1: Use database position tracking if available
                if strategy_id:
                    db_position = await self._get_database_position(strategy_id, account_id, symbol)
                    if db_position is not None:
                        logger.info(f"Using database position: {db_position}",
                                   extra_context={"source": "database", "strategy_id": strategy_id})
                        return db_position
                
                # PRIORITY 2: Fallback to broker API
                logger.info("No database position found, fetching from broker API")
                
                # Get account if not provided
                if not account:
                    account = self.db.query(BrokerAccount).filter(
                        BrokerAccount.account_id == account_id,
                        BrokerAccount.is_active == True
                    ).first()
                    
                    if not account:
                        logger.warning(f"Account {account_id} not found")
                        return 0
                
                # Get broker instance if not provided
                if not broker:
                    broker = BaseBroker.get_broker_instance(account.broker_id, self.db)
                
                # Fetch positions from broker
                positions = await broker.get_positions(account)
                
                # Find position for the symbol
                current_position = 0
                for position in positions:
                    if position.get("symbol") == symbol:
                        current_position = int(position.get("quantity", 0))
                        break
                
                # Cache the position
                await self._cache_position(account_id, symbol, current_position)
                
                logger.info(f"Fetched position from broker: {current_position}",
                           extra_context={"source": "broker_api"})
                
                return current_position
                
            except Exception as e:
                logger.error(f"Error fetching position: {str(e)}",
                           extra_context={"error": str(e)})
                # Return 0 if we can't determine position (safer than erroring)
                return 0
    
    async def update_position_cache(
        self,
        account_id: str,
        symbol: str, 
        quantity_change: int,
        is_absolute: bool = False
    ) -> None:
        """
        Update cached position after trade execution.
        
        Args:
            account_id: The broker account ID
            symbol: The trading symbol/ticker
            quantity_change: The change in position (or absolute value if is_absolute=True)
            is_absolute: If True, quantity_change is the new absolute position
        """
        try:
            if is_absolute:
                # Set absolute position
                await self._cache_position(account_id, symbol, quantity_change)
                logger.info(f"Set absolute position to {quantity_change}",
                           extra_context={"account_id": account_id, "symbol": symbol})
            else:
                # Update relative to current position
                current = await self.get_current_position(account_id, symbol)
                new_position = current + quantity_change
                await self._cache_position(account_id, symbol, new_position)
                logger.info(f"Updated position from {current} to {new_position}",
                           extra_context={"account_id": account_id, "symbol": symbol, "change": quantity_change})
                
        except Exception as e:
            logger.error(f"Error updating position cache: {str(e)}",
                       extra_context={"account_id": account_id, "symbol": symbol})
    
    async def clear_position_cache(self, account_id: str, symbol: Optional[str] = None) -> None:
        """
        Clear cached positions for an account.
        
        Args:
            account_id: The broker account ID
            symbol: Optional symbol to clear (clears all if not specified)
        """
        with get_redis_connection() as redis_client:
            if not redis_client:
                return
            
            try:
                if symbol:
                    # Clear specific symbol
                    cache_key = self._get_cache_key(account_id, symbol)
                    redis_client.delete(cache_key)
                    logger.debug(f"Cleared position cache for {account_id}:{symbol}")
                else:
                    # Clear all positions for account
                    pattern = f"position:{account_id}:*"
                    keys = redis_client.keys(pattern)
                    if keys:
                        redis_client.delete(*keys)
                    logger.debug(f"Cleared all position caches for {account_id}")
                    
            except RedisError as e:
                logger.warning(f"Redis error clearing position cache: {e}")
    
    async def get_all_positions(self, account_id: str, broker: Optional[BaseBroker] = None) -> Dict[str, int]:
        """
        Get all positions for an account.
        
        Args:
            account_id: The broker account ID
            broker: Optional broker instance
            
        Returns:
            Dictionary mapping symbols to positions
        """
        positions_dict = {}
        
        try:
            # Get account
            account = self.db.query(BrokerAccount).filter(
                BrokerAccount.account_id == account_id,
                BrokerAccount.is_active == True
            ).first()
            
            if not account:
                logger.warning(f"Account {account_id} not found")
                return positions_dict
            
            # Get broker instance if not provided
            if not broker:
                broker = BaseBroker.get_broker_instance(account.broker_id, self.db)
            
            # Fetch all positions
            positions = await broker.get_positions(account)
            
            # Convert to dictionary
            for position in positions:
                symbol = position.get("symbol")
                quantity = int(position.get("quantity", 0))
                if symbol and quantity != 0:
                    positions_dict[symbol] = quantity
            
            logger.info(f"Retrieved {len(positions_dict)} positions for account {account_id}")
            
        except Exception as e:
            logger.error(f"Error fetching all positions: {str(e)}",
                       extra_context={"account_id": account_id})
        
        return positions_dict
    
    def _get_cache_key(self, account_id: str, symbol: str) -> str:
        """Generate Redis cache key for position."""
        return f"position:{account_id}:{symbol}"
    
    async def _get_cached_position(self, account_id: str, symbol: str) -> Optional[int]:
        """Get position from Redis cache."""
        with get_redis_connection() as redis_client:
            if not redis_client:
                return None
            
            try:
                cache_key = self._get_cache_key(account_id, symbol)
                cached_value = redis_client.get(cache_key)
                
                if cached_value:
                    return int(cached_value)
                    
            except (RedisError, ValueError) as e:
                logger.debug(f"Cache retrieval error: {e}")
                
        return None
    
    async def _cache_position(self, account_id: str, symbol: str, position: int) -> None:
        """Cache position in Redis."""
        with get_redis_connection() as redis_client:
            if not redis_client:
                return
            
            try:
                cache_key = self._get_cache_key(account_id, symbol)
                redis_client.setex(cache_key, self._cache_ttl, str(position))
                logger.debug(f"Cached position {position} for {account_id}:{symbol}")
                
            except RedisError as e:
                logger.warning(f"Redis error caching position: {e}")
    
    async def track_partial_exit(
        self,
        strategy_id: int,
        exit_type: str,
        quantity_exited: int,
        remaining_position: int
    ) -> None:
        """
        Track partial exit for audit and analysis.
        
        Args:
            strategy_id: The strategy ID
            exit_type: Type of exit (EXIT_50, EXIT_FINAL, etc.)
            quantity_exited: Amount exited in this transaction
            remaining_position: Position remaining after exit
        """
        try:
            # This could be extended to write to a database table for tracking
            logger.info(f"Partial exit tracked",
                       extra_context={
                           "strategy_id": strategy_id,
                           "exit_type": exit_type,
                           "quantity_exited": quantity_exited,
                           "remaining_position": remaining_position,
                           "timestamp": datetime.utcnow().isoformat()
                       })
            
            # Store in Redis for quick access (optional)
            with get_redis_connection() as redis_client:
                if redis_client:
                    exit_key = f"exit_tracking:{strategy_id}:{datetime.utcnow().date()}"
                    exit_data = {
                        "exit_type": exit_type,
                        "quantity": quantity_exited,
                        "remaining": remaining_position,
                        "timestamp": datetime.utcnow().isoformat()
                    }
                    redis_client.lpush(exit_key, json.dumps(exit_data))
                    redis_client.expire(exit_key, 86400 * 7)  # Keep for 7 days
                    
        except Exception as e:
            logger.error(f"Error tracking partial exit: {str(e)}")
    
    async def _get_database_position(self, strategy_id: int, account_id: str, symbol: str) -> Optional[int]:
        """
        Get position from database strategy tracking.
        
        Args:
            strategy_id: The strategy ID
            account_id: The broker account ID
            symbol: The trading symbol
            
        Returns:
            Current position from database or None if not found/stale
        """
        try:
            from ..models.strategy import ActivatedStrategy
            
            strategy = self.db.query(ActivatedStrategy).filter(
                ActivatedStrategy.id == strategy_id,
                ActivatedStrategy.account_id == account_id
            ).first()
            
            # Note: We match by strategy_id and account_id only since ticker might be 
            # different from symbol (e.g., ticker="MNQ" but symbol="MNQU5")
            
            if not strategy:
                logger.debug(f"No strategy found for position lookup: strategy_id={strategy_id}, account_id={account_id}")
                return None
            
            # Check if position data is recent (within last 24 hours for safety)
            if strategy.last_position_update:
                from datetime import datetime, timedelta
                if datetime.utcnow() - strategy.last_position_update > timedelta(hours=24):
                    logger.warning(f"Database position data is stale for strategy {strategy_id}")
                    return None
            
            position = strategy.last_known_position or 0
            logger.debug(f"Database position for strategy {strategy_id}: {position}")
            return position
            
        except Exception as e:
            logger.error(f"Error getting database position: {str(e)}")
            return None
    
    async def update_database_position(
        self,
        strategy_id: int,
        account_id: str,
        symbol: str,
        position_change: int,
        exit_type: Optional[str] = None,
        is_absolute: bool = False
    ) -> None:
        """
        Update position in database strategy tracking.
        
        Args:
            strategy_id: The strategy ID
            account_id: The broker account ID  
            symbol: The trading symbol
            position_change: The change in position (or absolute value if is_absolute=True)
            exit_type: The exit type if this is an exit (EXIT_50, EXIT_FINAL, etc.)
            is_absolute: If True, position_change is the new absolute position
        """
        try:
            from ..models.strategy import ActivatedStrategy
            from datetime import datetime
            
            strategy = self.db.query(ActivatedStrategy).filter(
                ActivatedStrategy.id == strategy_id,
                ActivatedStrategy.account_id == account_id
            ).first()
            
            if not strategy:
                logger.error(f"Strategy not found for position update: strategy_id={strategy_id}, account_id={account_id}")
                return
            
            old_position = strategy.last_known_position or 0
            
            if is_absolute:
                new_position = position_change
            else:
                new_position = old_position + position_change
            
            # VALIDATION AND DEBUGGING: Enhanced position tracking
            # Log detailed position change information
            position_type = "unknown"
            trade_direction = "unknown"
            
            # Determine trade direction and position type
            if new_position > 0:
                position_type = "LONG"
            elif new_position < 0:
                position_type = "SHORT"
            else:
                position_type = "FLAT"
                
            if position_change > 0:
                trade_direction = "BUY"
            elif position_change < 0:
                trade_direction = "SELL"
            
            # Enhanced logging for position changes
            logger.info(f"Position update details for strategy {strategy_id}:",
                       extra_context={
                           "old_position": old_position,
                           "position_change": position_change,
                           "new_position": new_position,
                           "position_type": position_type,
                           "trade_direction": trade_direction,
                           "exit_type": exit_type,
                           "is_absolute": is_absolute,
                           "symbol": symbol,
                           "account_id": account_id
                       })
            
            # VALIDATION: Check for potential position direction confusion
            # This helps catch the issues we saw in the logs
            if exit_type and "EXIT" in exit_type.upper():
                # This is an exit trade - validate direction makes sense
                if position_change > 0:  # BUY action (covers shorts)
                    if old_position >= 0:
                        logger.warning(f"BUY exit on non-short position: old={old_position}, change={position_change}",
                                     extra_context={
                                         "strategy_id": strategy_id,
                                         "potential_issue": "BUY exit should only happen on short positions (negative)",
                                         "exit_type": exit_type
                                     })
                elif position_change < 0:  # SELL action (covers longs)
                    if old_position <= 0:
                        logger.warning(f"SELL exit on non-long position: old={old_position}, change={position_change}",
                                     extra_context={
                                         "strategy_id": strategy_id,
                                         "potential_issue": "SELL exit should only happen on long positions (positive)",
                                         "exit_type": exit_type
                                     })
            
            # VALIDATION: Check for reasonable position bounds
            # This catches extreme values that might indicate calculation errors
            max_reasonable_position = 1000  # Adjust based on your trading limits
            if abs(new_position) > max_reasonable_position:
                logger.warning(f"Unusually large position detected: {new_position}",
                             extra_context={
                                 "strategy_id": strategy_id,
                                 "symbol": symbol,
                                 "potential_issue": "Position exceeds reasonable bounds"
                             })
            
            # Update strategy position tracking
            strategy.last_known_position = new_position
            strategy.last_position_update = datetime.utcnow()
            
            if exit_type:
                strategy.last_exit_type = exit_type
                # Increment partial exit count for non-final exits
                if "FINAL" not in exit_type.upper() and "100" not in exit_type:
                    strategy.partial_exits_count = (strategy.partial_exits_count or 0) + 1
                else:
                    # Reset on final exits
                    strategy.partial_exits_count = 0
            
            # Reset tracking on new entries
            if position_change > 0 and old_position <= 0:
                strategy.partial_exits_count = 0
                strategy.last_exit_type = None
            
            self.db.commit()
            
            logger.info(f"Updated database position for strategy {strategy_id}: {old_position} -> {new_position}",
                       extra_context={
                           "position_change": position_change,
                           "exit_type": exit_type,
                           "is_absolute": is_absolute
                       })
            
        except Exception as e:
            logger.error(f"Error updating database position: {str(e)}")
            self.db.rollback()
    
    async def validate_trade_direction(
        self,
        strategy_id: int,
        account_id: str,
        current_position: int,
        action: str,
        exit_type: Optional[str] = None
    ) -> tuple[bool, str]:
        """
        Validate that trade direction makes sense given current position.
        Returns (is_valid, reason).
        
        Args:
            strategy_id: The strategy ID
            account_id: The broker account ID
            current_position: Current position (positive=long, negative=short, 0=flat)
            action: Trade action (BUY or SELL)
            exit_type: Exit type if this is an exit trade
            
        Returns:
            Tuple of (is_valid, validation_message)
        """
        with logging_context(
            strategy_id=strategy_id,
            account_id=account_id,
            current_position=current_position,
            action=action,
            exit_type=exit_type
        ):
            # If no exit_type, this is likely an entry trade - generally valid
            if not exit_type or "EXIT" not in exit_type.upper():
                logger.debug("Entry trade validation - allowing all directions")
                return True, "Entry trade - direction validation passed"
            
            # This is an exit trade - validate direction
            if action == "BUY":
                # BUY exits should only happen when we have a short position to cover
                if current_position >= 0:
                    warning_msg = f"BUY exit attempted on non-short position {current_position}"
                    logger.warning(warning_msg, extra_context={
                        "validation_failed": True,
                        "expected": "negative position for BUY exit",
                        "actual": current_position
                    })
                    return False, warning_msg
                else:
                    return True, "BUY exit on short position - valid"
                    
            elif action == "SELL":
                # SELL exits should only happen when we have a long position to close
                if current_position <= 0:
                    warning_msg = f"SELL exit attempted on non-long position {current_position}"
                    logger.warning(warning_msg, extra_context={
                        "validation_failed": True,
                        "expected": "positive position for SELL exit",
                        "actual": current_position
                    })
                    return False, warning_msg
                else:
                    return True, "SELL exit on long position - valid"
            
            else:
                return False, f"Unknown action: {action}"
    
    async def sync_position_with_broker(
        self,
        strategy_id: int,
        account_id: str,
        symbol: str,
        broker: Optional[BaseBroker] = None,
        account: Optional[BrokerAccount] = None
    ) -> Dict[str, Any]:
        """
        Sync database position with broker API and report any discrepancies.
        
        Args:
            strategy_id: The strategy ID
            account_id: The broker account ID
            symbol: The trading symbol
            broker: Optional broker instance
            account: Optional account instance
            
        Returns:
            Dict with sync results and any discrepancies found
        """
        try:
            # Get database position
            db_position = await self._get_database_position(strategy_id, account_id, symbol)
            
            # Get broker position  
            if not account:
                account = self.db.query(BrokerAccount).filter(
                    BrokerAccount.account_id == account_id,
                    BrokerAccount.is_active == True
                ).first()
            
            if not broker:
                broker = BaseBroker.get_broker_instance(account.broker_id, self.db)
            
            positions = await broker.get_positions(account)
            broker_position = 0
            for position in positions:
                if position.get("symbol") == symbol:
                    broker_position = int(position.get("quantity", 0))
                    break
            
            # Compare positions
            discrepancy = None
            if db_position is not None and db_position != broker_position:
                discrepancy = broker_position - db_position
                logger.warning(f"Position discrepancy detected for strategy {strategy_id}: DB={db_position}, Broker={broker_position}, Diff={discrepancy}")
                
                # Optionally update database to match broker
                await self.update_database_position(
                    strategy_id=strategy_id,
                    account_id=account_id,
                    symbol=symbol,
                    position_change=broker_position,
                    is_absolute=True
                )
                logger.info(f"Updated database position to match broker: {broker_position}")
            
            return {
                "database_position": db_position,
                "broker_position": broker_position,
                "discrepancy": discrepancy,
                "synced": discrepancy is None,
                "corrected": discrepancy is not None
            }
            
        except Exception as e:
            logger.error(f"Error syncing position with broker: {str(e)}")
            return {
                "error": str(e),
                "synced": False
            }