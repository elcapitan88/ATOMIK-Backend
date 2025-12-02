from typing import Dict, List, Tuple
from .futures_contracts import FuturesContractManager, get_current_futures_contracts

def get_tickers() -> Dict[str, str]:
    """Get current futures contract mappings"""
    return get_current_futures_contracts()

def get_display_tickers() -> List[str]:
    """Get display tickers for validation"""
    return FuturesContractManager.FUTURES_SYMBOLS + FuturesContractManager.MONTHLY_FUTURES_SYMBOLS

def get_contract_ticker(display_ticker: str) -> str:
    """Get full contract spec for a display ticker"""
    contracts = get_current_futures_contracts()
    return contracts.get(display_ticker, display_ticker)

def get_display_ticker(contract_ticker: str) -> str:
    """Convert full contract to display ticker"""
    # First check if it's already a display ticker
    all_symbols = FuturesContractManager.FUTURES_SYMBOLS + FuturesContractManager.MONTHLY_FUTURES_SYMBOLS
    if contract_ticker in all_symbols:
        return contract_ticker
    
    # Extract base symbol from contract ticker (e.g., "ESU5" -> "ES")
    for symbol in all_symbols:
        if contract_ticker.startswith(symbol):
            return symbol
    
    return contract_ticker

def validate_ticker(ticker: str) -> Tuple[bool, str]:
    """
    Validate if a ticker is supported.
    Accepts both display tickers (ES) and contract tickers (ESU5).
    Returns (is_valid, result_or_error_message).
    """
    if not ticker:
        return False, "Ticker cannot be empty"

    # Normalize ticker - uppercase and strip whitespace
    normalized_ticker = ticker.strip().upper()

    all_symbols = FuturesContractManager.FUTURES_SYMBOLS + FuturesContractManager.MONTHLY_FUTURES_SYMBOLS

    # Check if it's a valid display ticker (e.g., "ES", "MBT")
    if normalized_ticker in all_symbols:
        return True, get_contract_ticker(normalized_ticker)

    # Check if it's a valid contract ticker (e.g., "ESU5", "MBTQ5")
    # Extract base symbol and validate
    for symbol in all_symbols:
        if normalized_ticker.startswith(symbol) and len(normalized_ticker) == len(symbol) + 2:
            # Verify it matches current contract format
            current_contracts = get_current_futures_contracts()
            if normalized_ticker == current_contracts.get(symbol):
                return True, normalized_ticker
            # Even if not current contract, still valid format
            return True, normalized_ticker

    # Return helpful error message with valid options
    return False, f"'{ticker}' is not a supported ticker. Valid tickers: {', '.join(all_symbols)}"