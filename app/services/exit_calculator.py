"""
Exit calculator service for computing trade quantities based on exit types.
Handles partial exits, percentage-based exits, and position-aware calculations.

SIMPLIFIED LOGIC:
- action (BUY/SELL) + current_position determines intent (entry vs exit)
- comment is ONLY parsed for partial exit types (EXIT_50, EXIT_FINAL, etc.)
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
        Calculate quantity based on action and current position.

        Logic:
        - BUY + no position or long = Long entry (configured_quantity)
        - BUY + short position = Cover short (position-based, check for partial)
        - SELL + long position = Exit long (position-based, check for partial)
        - SELL + no position or short = Short entry (configured_quantity)

        Args:
            strategy: The activated strategy
            exit_type: Type of exit from webhook comment (EXIT_50, EXIT_FINAL, etc.)
            current_position: Current position in the account (positive=long, negative=short)
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
            exit_type_upper = (exit_type or "").upper()

            # ===================
            # BUY ACTION
            # ===================
            if action == "BUY":
                if current_position < 0:
                    # Covering a short position
                    position_size = abs(current_position)
                    logger.info(f"BUY to cover short position of {current_position}")
                    return ExitCalculator._calculate_exit_amount(position_size, exit_type_upper)
                else:
                    # Long entry (position is 0 or already long - scaling in)
                    logger.info(f"BUY entry: using configured quantity {configured_quantity}")
                    return configured_quantity, "Long entry"

            # ===================
            # SELL ACTION
            # ===================
            elif action == "SELL":
                if current_position > 0:
                    # Exiting a long position
                    logger.info(f"SELL to exit long position of {current_position}")
                    return ExitCalculator._calculate_exit_amount(current_position, exit_type_upper)
                else:
                    # Short entry (position is 0 or already short - scaling in)
                    logger.info(f"SELL entry: using configured quantity {configured_quantity}")
                    return configured_quantity, "Short entry"

            # Unknown action - shouldn't happen
            logger.warning(f"Unknown action '{action}', defaulting to configured quantity")
            return configured_quantity, f"Unknown action - using configured quantity"

    @staticmethod
    def _calculate_exit_amount(position_size: int, exit_type_upper: str) -> Tuple[int, str]:
        """
        Calculate exit quantity based on position size and exit type.

        Only parses for EXIT_XX patterns:
        - EXIT_50 / EXIT_HALF = 50%
        - EXIT_25 = 25%
        - EXIT_75 = 75%
        - EXIT_FINAL / EXIT_ALL / EXIT_100 = 100%
        - Custom: EXIT_33, EXIT_67, etc.
        - Default (no pattern) = 100% full exit

        Args:
            position_size: Absolute size of current position
            exit_type_upper: Uppercase exit type string

        Returns:
            Tuple of (quantity to exit, reason)
        """
        if position_size <= 0:
            return 0, "No position to exit"

        # Half position exits
        if "EXIT_50" in exit_type_upper or "EXIT_HALF" in exit_type_upper:
            quantity = math.ceil(position_size * 0.5)
            logger.info(f"50% exit: {position_size} * 0.5 = {quantity}")
            return quantity, "50% partial exit"

        # Quarter position exits
        if "EXIT_25" in exit_type_upper:
            quantity = math.ceil(position_size * 0.25)
            logger.info(f"25% exit: {position_size} * 0.25 = {quantity}")
            return quantity, "25% partial exit"

        # Three-quarter position exits
        if "EXIT_75" in exit_type_upper:
            quantity = math.ceil(position_size * 0.75)
            logger.info(f"75% exit: {position_size} * 0.75 = {quantity}")
            return quantity, "75% partial exit"

        # Final/All exits
        if "EXIT_FINAL" in exit_type_upper or "EXIT_ALL" in exit_type_upper or "EXIT_100" in exit_type_upper:
            logger.info(f"Final exit: closing entire position of {position_size}")
            return position_size, "Final exit - closing all"

        # Handle custom percentage exits (e.g., EXIT_33, EXIT_67)
        percentage_match = re.search(r"EXIT_(\d+)", exit_type_upper)
        if percentage_match:
            try:
                percentage = int(percentage_match.group(1))
                if 0 < percentage <= 100:
                    quantity = math.ceil(position_size * (percentage / 100))
                    logger.info(f"Custom {percentage}% exit: {position_size} * {percentage/100} = {quantity}")
                    return quantity, f"{percentage}% partial exit"
            except ValueError:
                pass  # Fall through to default

        # Handle scale-out patterns (EXIT_1, EXIT_2, EXIT_3) - single digit only
        scale_match = re.search(r"EXIT_([1-3])(?!\d)", exit_type_upper)
        if scale_match:
            exit_number = int(scale_match.group(1))
            return ExitCalculator._calculate_scaled_exit(position_size, exit_number)

        # Default: full position exit
        logger.info(f"Full exit (default): closing entire position of {position_size}")
        return position_size, "Full exit"

    @staticmethod
    def _calculate_scaled_exit(
        position_size: int,
        exit_number: int
    ) -> Tuple[int, str]:
        """
        Calculate quantity for scaled exits (EXIT_1, EXIT_2, EXIT_3).

        Scale-out strategy:
        - EXIT_1: Exit 1/3 of position
        - EXIT_2: Exit 1/2 of remaining
        - EXIT_3: Exit all remaining

        Args:
            position_size: Current position quantity
            exit_number: The exit number (1, 2, 3)

        Returns:
            Tuple of (quantity to exit, explanation)
        """
        if exit_number == 1:
            quantity = math.ceil(position_size / 3)
            return quantity, "Scale-out 1/3"
        elif exit_number == 2:
            quantity = math.ceil(position_size / 2)
            return quantity, "Scale-out 1/2 of remaining"
        else:
            return position_size, f"Scale-out final (all remaining)"

    @staticmethod
    def validate_exit_quantity(
        action: str,
        calculated_quantity: int,
        current_position: int,
        max_position_size: Optional[int] = None,
        exit_type: Optional[str] = None
    ) -> Tuple[int, bool, str]:
        """
        Validate and adjust quantity to prevent over-trading.

        Args:
            action: Trade action (BUY or SELL)
            calculated_quantity: The calculated quantity to trade
            current_position: Current position in the account
            max_position_size: Optional maximum position size limit
            exit_type: Optional exit type (not used in simplified logic)

        Returns:
            Tuple of (adjusted quantity, is_valid, validation_message)
        """
        # No trades with zero or negative quantity
        if calculated_quantity <= 0:
            return 0, False, "Cannot trade zero or negative quantity"

        # For SELL exiting a long: don't sell more than we have
        if action == "SELL" and current_position > 0:
            if calculated_quantity > current_position:
                logger.warning(f"Reducing SELL from {calculated_quantity} to {current_position} (position limit)")
                return current_position, True, f"Adjusted to position size ({current_position})"

        # For BUY covering a short: don't buy more than we're short
        if action == "BUY" and current_position < 0:
            short_size = abs(current_position)
            if calculated_quantity > short_size:
                logger.warning(f"Reducing BUY from {calculated_quantity} to {short_size} (position limit)")
                return short_size, True, f"Adjusted to position size ({short_size})"

        # Check max position size for entries
        if max_position_size and max_position_size > 0:
            if action == "BUY" and current_position >= 0:
                # Long entry - check if we'd exceed max
                new_position = current_position + calculated_quantity
                if new_position > max_position_size:
                    allowed = max(0, max_position_size - current_position)
                    if allowed <= 0:
                        return 0, False, f"Would exceed max position size of {max_position_size}"
                    logger.warning(f"Reducing BUY from {calculated_quantity} to {allowed} (max position)")
                    return allowed, True, f"Adjusted for max position ({max_position_size})"

            elif action == "SELL" and current_position <= 0:
                # Short entry - check if we'd exceed max (as negative)
                new_position = abs(current_position) + calculated_quantity
                if new_position > max_position_size:
                    allowed = max(0, max_position_size - abs(current_position))
                    if allowed <= 0:
                        return 0, False, f"Would exceed max position size of {max_position_size}"
                    logger.warning(f"Reducing SELL from {calculated_quantity} to {allowed} (max position)")
                    return allowed, True, f"Adjusted for max position ({max_position_size})"

        return calculated_quantity, True, "Valid quantity"

    @staticmethod
    def get_exit_progression(strategy: ActivatedStrategy, exit_type: str) -> str:
        """
        Determine the progression of exits for logging and tracking.

        Args:
            strategy: The strategy being executed
            exit_type: The current exit type

        Returns:
            Description of exit progression
        """
        exit_count = strategy.partial_exits_count or 0
        exit_type_upper = (exit_type or "").upper()

        if "EXIT_FINAL" in exit_type_upper or "EXIT_ALL" in exit_type_upper or "EXIT_100" in exit_type_upper:
            return f"Final exit after {exit_count} partial exit(s)"

        if exit_count == 0:
            return "First exit"

        return f"Exit #{exit_count + 1}"

    @staticmethod
    def should_reset_exit_tracking(action: str, current_position: int, new_position: int) -> bool:
        """
        Determine if exit tracking should be reset (new position cycle).

        Args:
            action: Trade action (BUY or SELL)
            current_position: Position before trade
            new_position: Position after trade

        Returns:
            True if tracking should be reset, False otherwise
        """
        # Reset when position goes to zero (fully closed)
        if new_position == 0:
            return True

        # Reset when opening a new position from flat
        if current_position == 0 and new_position != 0:
            return True

        # Reset when flipping direction (long to short or vice versa)
        if (current_position > 0 and new_position < 0) or (current_position < 0 and new_position > 0):
            return True

        return False
