"""
Exit calculator service for computing trade quantities based on exit types.
Handles partial exits, percentage-based exits, and position-aware calculations.
"""

import math
from typing import Optional, Tuple
from datetime import datetime
import logging
import re

from ..models.strategy import ActivatedStrategy
from ..schemas.webhook import ExitType
from ..core.enhanced_logging import get_enhanced_logger, logging_context

logger = get_enhanced_logger(__name__)


class ExitCalculator:
    """Calculate appropriate exit quantities based on exit type and current positions."""
    
    @staticmethod
    async def calculate_exit_quantity(
        strategy: ActivatedStrategy,
        exit_type: str,
        current_position: int,
        configured_quantity: int,
        action: str
    ) -> Tuple[int, str]:
        """
        Calculate exit quantity based on exit type and current position.
        
        Args:
            strategy: The activated strategy
            exit_type: Type of exit from webhook comment (EXIT_50, EXIT_FINAL, etc.)
            current_position: Current position in the account
            configured_quantity: Strategy's configured quantity
            action: Trade action (BUY or SELL)
            
        Returns:
            Tuple of (quantity to trade, reason/explanation)
        """
        
        with logging_context(
            strategy_id=strategy.id,
            exit_type=exit_type,
            current_position=current_position,
            action=action
        ):
            # Parse exit type first to handle ENTRY comments
            exit_type_upper = (exit_type or "").upper()
            
            # Handle ENTRY signals for both BUY and SELL (BUY = long entry, SELL = short entry)
            if exit_type_upper == "ENTRY":
                logger.info(f"{action} ENTRY: using configured quantity {configured_quantity}")
                return configured_quantity, f"{action} entry using configured quantity"
            
            # Determine if we have a position to exit
            has_long_position = current_position > 0
            has_short_position = current_position < 0
            has_no_position = current_position == 0
            
            # Handle BUY actions 
            if action == "BUY":
                # BUY can be: 1) Long entry, 2) Short exit
                if has_short_position and exit_type_upper and ("EXIT" in exit_type_upper or "STOP" in exit_type_upper):
                    # This is a short exit - calculate based on short position size
                    position_size = abs(current_position)
                    logger.info(f"BUY exit from short position of {current_position}")
                elif exit_type_upper == "" or exit_type_upper == "ENTRY":
                    # This is a long entry
                    logger.info(f"BUY entry: using configured quantity {configured_quantity}")
                    return configured_quantity, "Long entry using configured quantity"
                else:
                    # BUY with exit type but no short position
                    if has_long_position:
                        # Has long position but BUY exit doesn't make sense
                        logger.warning(f"BUY exit attempted on long position {current_position}")
                        return 0, "Cannot BUY to exit long position - use SELL"
                    else:
                        # No position but trying to exit - this is an error
                        if "EXIT" in exit_type_upper or "STOP" in exit_type_upper:
                            logger.warning(f"BUY exit attempted with no position")
                            return 0, "No position to exit"
                        else:
                            # No exit type - treat as entry
                            logger.info(f"BUY action with no position: using configured quantity {configured_quantity}")
                            return configured_quantity, "Long entry using configured quantity"
            
            # Handle SELL actions
            elif action == "SELL":
                # SELL can be: 1) Short entry, 2) Long exit
                if has_long_position and exit_type_upper and ("EXIT" in exit_type_upper or "STOP" in exit_type_upper):
                    # This is a long exit - calculate based on long position size
                    position_size = current_position
                    logger.info(f"SELL exit from long position of {current_position}")
                elif exit_type_upper == "" or exit_type_upper == "ENTRY":
                    # This is a short entry
                    logger.info(f"SELL entry: using configured quantity {configured_quantity}")
                    return configured_quantity, "Short entry using configured quantity"
                else:
                    # SELL with exit type but no long position - check if we should exit anyway
                    if has_no_position:
                        logger.warning(f"No position to exit for strategy {strategy.id}")
                        return 0, "No position to exit"
                    else:
                        # Has short position but SELL exit doesn't make sense
                        logger.warning(f"SELL exit attempted on short position {current_position}")
                        return 0, "Cannot SELL to exit short position - use BUY"
            
            # If we reach here, we're processing an exit
            if has_no_position:
                logger.warning(f"No position to exit for strategy {strategy.id}")
                return 0, "No position to exit"
            
            # Use absolute position size for percentage calculations
            position_size = abs(current_position)
            
            # Handle exits with no specific exit type
            if exit_type_upper == "":
                logger.info(f"Exit with no type specified, closing full position: {position_size}")
                return position_size, "Full position exit (no exit type specified)"
            
            # Half position exits
            if exit_type_upper in ["EXIT_50", "EXIT_HALF"]:
                quantity = math.ceil(position_size * 0.5)
                logger.info(f"Calculating 50% exit: {position_size} * 0.5 = {quantity}")
                return quantity, "50% partial exit"
            
            # Quarter position exits
            if exit_type_upper == "EXIT_25":
                quantity = math.ceil(position_size * 0.25)
                logger.info(f"Calculating 25% exit: {position_size} * 0.25 = {quantity}")
                return quantity, "25% partial exit"
            
            # Three-quarter position exits
            if exit_type_upper == "EXIT_75":
                quantity = math.ceil(position_size * 0.75)
                logger.info(f"Calculating 75% exit: {position_size} * 0.75 = {quantity}")
                return quantity, "75% partial exit"
            
            # Final/All exits
            if exit_type_upper in ["EXIT_FINAL", "EXIT_ALL", "EXIT_100"]:
                logger.info(f"Final exit: closing entire position of {position_size}")
                return position_size, "Final exit - closing all remaining"
            
            # Handle custom percentage exits (e.g., EXIT_33, EXIT_67)
            percentage_match = re.match(r"EXIT_(\d+)", exit_type_upper)
            if percentage_match:
                try:
                    percentage = int(percentage_match.group(1))
                    if 0 < percentage <= 100:
                        quantity = math.ceil(current_position * (percentage / 100))
                        logger.info(f"Custom {percentage}% exit: {current_position} * {percentage/100} = {quantity}")
                        return quantity, f"Custom {percentage}% exit"
                    else:
                        logger.warning(f"Invalid percentage {percentage}, using full position")
                        return current_position, f"Invalid percentage {percentage}, defaulting to full exit"
                except ValueError:
                    logger.error(f"Could not parse percentage from {exit_type_upper}")
                    return current_position, "Parse error - defaulting to full exit"
            
            # Handle scale-out patterns (EXIT_1, EXIT_2, EXIT_3)
            scale_match = re.match(r"EXIT_(\d)$", exit_type_upper)
            if scale_match:
                exit_number = int(scale_match.group(1))
                return ExitCalculator._calculate_scaled_exit(
                    current_position, 
                    exit_number,
                    strategy.partial_exits_count
                )
            
            # Default: exit full position for unrecognized exit types
            logger.warning(f"Unrecognized exit type '{exit_type_upper}', defaulting to full position exit")
            return current_position, f"Unrecognized exit type - defaulting to full exit"
    
    @staticmethod
    def _calculate_scaled_exit(
        current_position: int, 
        exit_number: int,
        previous_exits: int
    ) -> Tuple[int, str]:
        """
        Calculate quantity for scaled exits (EXIT_1, EXIT_2, EXIT_3).
        
        This implements a common scale-out strategy:
        - EXIT_1: Exit 1/3 of original position
        - EXIT_2: Exit 1/2 of remaining (1/3 of original)
        - EXIT_3: Exit all remaining (1/3 of original)
        
        Args:
            current_position: Current position quantity
            exit_number: The exit number (1, 2, 3, etc.)
            previous_exits: Number of previous partial exits
            
        Returns:
            Tuple of (quantity to exit, explanation)
        """
        if exit_number == 1:
            # First exit: 1/3 of position
            quantity = math.ceil(current_position / 3)
            return quantity, "Scale-out exit 1/3"
        elif exit_number == 2:
            # Second exit: 1/2 of remaining (which should be 2/3 of original)
            quantity = math.ceil(current_position / 2)
            return quantity, "Scale-out exit 2/3 (half of remaining)"
        else:
            # Third or subsequent exits: all remaining
            return current_position, f"Scale-out exit {exit_number} (all remaining)"
    
    @staticmethod
    def validate_exit_quantity(
        action: str,
        calculated_quantity: int,
        current_position: int,
        max_position_size: Optional[int] = None,
        exit_type: Optional[str] = None
    ) -> Tuple[int, bool, str]:
        """
        Validate and adjust exit quantity to prevent over-trading.
        
        Args:
            action: Trade action (BUY or SELL)
            calculated_quantity: The calculated quantity to trade
            current_position: Current position in the account
            max_position_size: Optional maximum position size limit
            exit_type: Optional exit type to determine if this is an entry or exit
            
        Returns:
            Tuple of (adjusted quantity, is_valid, validation_message)
        """
        # No trades with zero quantity
        if calculated_quantity <= 0:
            return 0, False, "Cannot trade zero or negative quantity"
        
        # Determine if this is an entry or exit
        exit_type_upper = (exit_type or "").upper()
        is_entry = exit_type_upper == "ENTRY" or exit_type_upper == ""
        is_exit = "EXIT" in exit_type_upper
        
        # For SELL orders
        if action == "SELL":
            if is_entry:
                # SELL ENTRY (short entry) - don't validate against current position
                return calculated_quantity, True, "Valid short entry quantity"
            elif is_exit and calculated_quantity > current_position:
                # SELL EXIT - ensure we don't sell more than we have
                logger.warning(
                    f"Reducing sell quantity from {calculated_quantity} to {current_position} to match position"
                )
                return current_position, True, f"Quantity adjusted to match position ({current_position})"
            else:
                return calculated_quantity, True, "Valid sell quantity"
        
        # For BUY orders, check max position size if configured
        if action == "BUY" and max_position_size:
            new_position = current_position + calculated_quantity
            if new_position > max_position_size:
                allowed_quantity = max(0, max_position_size - current_position)
                if allowed_quantity <= 0:
                    return 0, False, f"Would exceed max position size of {max_position_size}"
                logger.warning(
                    f"Reducing buy quantity from {calculated_quantity} to {allowed_quantity} due to position limit"
                )
                return allowed_quantity, True, f"Quantity adjusted to respect max position {max_position_size}"
        
        return calculated_quantity, True, "Valid quantity"
    
    @staticmethod
    def get_exit_progression(strategy: ActivatedStrategy, exit_type: str) -> str:
        """
        Determine the progression of exits for logging and tracking.
        
        Args:
            strategy: The strategy being executed
            exit_type: The current exit type
            
        Returns:
            Description of exit progression (e.g., "First partial exit", "Final exit")
        """
        exit_count = strategy.partial_exits_count or 0
        last_exit = strategy.last_exit_type or ""
        
        # Check if this is a final exit
        if exit_type in ["EXIT_FINAL", "EXIT_ALL", "EXIT_100"]:
            return f"Final exit after {exit_count} partial exit(s)"
        
        # Check if this is the first exit
        if exit_count == 0:
            return "First partial exit"
        
        # Check if this is a continuation of partial exits
        if "EXIT" in exit_type and exit_type not in ["ENTRY"]:
            return f"Partial exit #{exit_count + 1}"
        
        return "Exit"
    
    @staticmethod
    def should_reset_exit_tracking(action: str, exit_type: str) -> bool:
        """
        Determine if exit tracking should be reset (new position cycle).
        
        Args:
            action: Trade action (BUY or SELL)
            exit_type: Exit type from comment
            
        Returns:
            True if tracking should be reset, False otherwise
        """
        # Reset on new entries
        if action == "BUY" or exit_type == "ENTRY":
            return True
        
        # Reset after final exits
        if exit_type in ["EXIT_FINAL", "EXIT_ALL", "EXIT_100"]:
            return True
        
        return False