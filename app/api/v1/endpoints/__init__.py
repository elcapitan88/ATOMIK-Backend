# app/api/v1/endpoints/__init__.py

# Import all endpoint modules to make them available for import
from . import auth
from . import binance
from . import broker
from . import futures_contracts
from . import strategy
from . import subscriptions as subscription
from . import tradovate
from . import webhooks
from . import admin

# Import new endpoints with error handling
try:
    from . import chat
except ImportError as e:
    print(f"Warning: Could not import chat endpoint: {e}")
    chat = None

try:
    from . import feature_flags
except ImportError as e:
    print(f"Warning: Could not import feature_flags endpoint: {e}")
    feature_flags = None

try:
    from . import interactivebrokers
except ImportError as e:
    print(f"Warning: Could not import interactivebrokers endpoint: {e}")
    interactivebrokers = None

try:
    from . import creators
except ImportError as e:
    print(f"Warning: Could not import creators endpoint: {e}")
    creators = None

try:
    from . import marketplace
except ImportError as e:
    print(f"Warning: Could not import marketplace endpoint: {e}")
    marketplace = None

__all__ = [
    "auth",
    "binance", 
    "broker",
    "futures_contracts",
    "strategy",
    "subscription",
    "tradovate",
    "webhooks",
    "admin"
]

# Add to __all__ only if import succeeded
if chat is not None:
    __all__.append("chat")
if feature_flags is not None:
    __all__.append("feature_flags")
if interactivebrokers is not None:
    __all__.append("interactivebrokers")
if creators is not None:
    __all__.append("creators")
if marketplace is not None:
    __all__.append("marketplace")