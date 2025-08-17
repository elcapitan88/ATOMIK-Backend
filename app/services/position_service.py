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
        self._cache_ttl = 30  # Cache positions for 30 seconds
        
    async def get_current_position(
        self, 
        account_id: str, 
        symbol: str,
        broker: Optional[BaseBroker] = None,
        account: Optional[BrokerAccount] = None
    ) -> int:
        """
        Get current position for a symbol in an account.
        
        Args:
            account_id: The broker account ID
            symbol: The trading symbol/ticker
            broker: Optional broker instance (will be fetched if not provided)
            account: Optional account instance (will be fetched if not provided)
            
        Returns:
            Current position quantity (positive for long, negative for short, 0 for flat)
        """
        with logging_context(account_id=account_id, symbol=symbol):
            # Try cache first
            cached_position = await self._get_cached_position(account_id, symbol)
            if cached_position is not None:
                logger.debug(f"Retrieved cached position: {cached_position}")
                return cached_position
            
            # Fetch from broker if not cached
            try:
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
                logger.error(f"Error fetching position from broker: {str(e)}",
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