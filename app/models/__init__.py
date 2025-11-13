# app/models/__init__.py
from .user import User
from .webhook import Webhook, WebhookLog
from .strategy import ActivatedStrategy
from .strategy_code import StrategyCode
from .broker import BrokerAccount, BrokerCredentials
from .subscription import Subscription
from .order import Order
from .trade import Trade, TradeExecution
from .maintenance import MaintenanceSettings
from .affiliate import Affiliate, AffiliateReferral, AffiliateClick, AffiliatePayout
from .creator_profile import CreatorProfile
from .creator_follower import CreatorFollower
from .strategy_pricing import StrategyPricing, PricingType, BillingInterval
from .strategy_purchase import StrategyPurchase, PurchaseStatus, PurchaseType
from .creator_earnings import CreatorEarnings, PayoutStatus
from .strategy_monetization import StrategyMonetization, StrategyPrice
# TODO: Uncomment after strategy_metrics table migration is fixed
# from .strategy_metrics import StrategyMetrics, CreatorDashboardCache

# This ensures all models are registered
__all__ = [
    "User",
    "Webhook",
    "WebhookLog",
    "ActivatedStrategy",
    "StrategyCode",
    "BrokerAccount",
    "BrokerCredentials",
    "Subscription",
    "Order",
    "Trade",
    "TradeExecution",
    "MaintenanceSettings",
    "Affiliate",
    "AffiliateReferral",
    "AffiliateClick",
    "AffiliatePayout",
    "CreatorProfile",
    "CreatorFollower",
    "StrategyPricing",
    "PricingType",
    "BillingInterval",
    "StrategyPurchase",
    "PurchaseStatus",
    "PurchaseType",
    "CreatorEarnings",
    "PayoutStatus",
    "StrategyMonetization",
    "StrategyPrice"
    # TODO: Uncomment after strategy_metrics table migration is fixed
    # "StrategyMetrics",
    # "CreatorDashboardCache"
]