"""
Market hours configuration and checking service
"""
from datetime import datetime, time, timedelta
from typing import Optional, Dict
import pytz
import logging

logger = logging.getLogger(__name__)

# Market configurations
MARKET_CONFIGS = {
    'NYSE': {
        'timezone': 'America/New_York',
        'open_time': time(9, 30),   # 9:30 AM
        'close_time': time(16, 0),  # 4:00 PM
        'trading_days': [0, 1, 2, 3, 4],  # Monday to Friday
        'name': 'New York Stock Exchange',
        'display_hours': '9:30 AM - 4:00 PM EST'
    },
    'LONDON': {
        'timezone': 'Europe/London',
        'open_time': time(8, 0),    # 8:00 AM GMT
        'close_time': time(16, 30), # 4:30 PM GMT
        'trading_days': [0, 1, 2, 3, 4],
        'name': 'London Stock Exchange',
        'display_hours': '3:00 AM - 11:30 AM EST'  # Converted to EST
    },
    'ASIA': {
        'timezone': 'Asia/Tokyo',
        'open_time': time(9, 0),    # 9:00 AM JST
        'close_time': time(15, 0),  # 3:00 PM JST
        'trading_days': [0, 1, 2, 3, 4],
        'name': 'Tokyo Stock Exchange',
        'display_hours': '7:00 PM - 1:00 AM EST'  # Converted to EST (previous day)
    }
}


def is_market_open(market: str) -> bool:
    """
    Check if a specific market is currently open

    Args:
        market: Market identifier ('NYSE', 'LONDON', 'ASIA', '24/7')

    Returns:
        True if market is open, False otherwise
    """
    if not market or market == '24/7':
        return True

    config = MARKET_CONFIGS.get(market)
    if not config:
        logger.warning(f"Unknown market: {market}, defaulting to open")
        return True

    try:
        # Get current time in market timezone
        tz = pytz.timezone(config['timezone'])
        now = datetime.now(tz)

        # Check if it's a trading day
        if now.weekday() not in config['trading_days']:
            return False

        # Check if within trading hours
        current_time = now.time()
        return config['open_time'] <= current_time < config['close_time']

    except Exception as e:
        logger.error(f"Error checking market hours for {market}: {e}")
        return True  # Default to open on error


def get_next_market_event(market: str) -> Optional[dict]:
    """
    Get the next market open or close event

    Args:
        market: Market identifier

    Returns:
        Dict with 'action' ('open' or 'close') and 'datetime', or None
    """
    if not market or market == '24/7':
        return None

    config = MARKET_CONFIGS.get(market)
    if not config:
        return None

    try:
        tz = pytz.timezone(config['timezone'])
        now = datetime.now(tz)
        current_time = now.time()
        current_day = now.weekday()

        # If it's a trading day
        if current_day in config['trading_days']:
            # If before market open
            if current_time < config['open_time']:
                open_datetime = now.replace(
                    hour=config['open_time'].hour,
                    minute=config['open_time'].minute,
                    second=0,
                    microsecond=0
                )
                return {'action': 'open', 'datetime': open_datetime}

            # If market is open
            elif current_time < config['close_time']:
                close_datetime = now.replace(
                    hour=config['close_time'].hour,
                    minute=config['close_time'].minute,
                    second=0,
                    microsecond=0
                )
                return {'action': 'close', 'datetime': close_datetime}

        # Find next trading day
        days_ahead = 1
        while days_ahead <= 7:
            next_day = (current_day + days_ahead) % 7
            if next_day in config['trading_days']:
                next_date = now + timedelta(days=days_ahead)
                open_datetime = next_date.replace(
                    hour=config['open_time'].hour,
                    minute=config['open_time'].minute,
                    second=0,
                    microsecond=0
                )
                return {'action': 'open', 'datetime': open_datetime}
            days_ahead += 1

    except Exception as e:
        logger.error(f"Error getting next market event for {market}: {e}")

    return None


def get_market_info(market: str) -> Dict[str, any]:
    """
    Get display information for a market

    Args:
        market: Market identifier

    Returns:
        Dict with market name, display hours, and open status
    """
    if market == '24/7':
        return {
            'name': 'Always On',
            'display_hours': '24/7 - Continuous Trading',
            'is_open': True
        }

    config = MARKET_CONFIGS.get(market, {})
    return {
        'name': config.get('name', market),
        'display_hours': config.get('display_hours', ''),
        'is_open': is_market_open(market)
    }
