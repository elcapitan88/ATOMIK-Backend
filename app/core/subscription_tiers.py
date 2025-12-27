# app/core/subscription_tiers.py
from enum import Enum
from typing import Dict, Any, Optional
from datetime import datetime, timedelta


class SubscriptionTier(str, Enum):
    """
    Enumeration of available subscription tiers.

    Tier Structure:
    - FREE: Browse marketplace, view strategies, no execution
    - STARTER: $49/month - 3 strategies, 2 accounts
    - TRADER: $129/month - 10 strategies, 10 accounts
    - UNLIMITED: $249/month - Unlimited everything
    """
    FREE = "free"          # Browse only, no trading execution
    STARTER = "starter"    # $49/mo - Entry-level paid tier
    TRADER = "trader"      # $129/mo - Most popular for active traders
    UNLIMITED = "unlimited"  # $249/mo - Unlimited everything


# Define resource limits for each tier
TIER_LIMITS = {
    SubscriptionTier.FREE: {
        "connected_accounts": 0,
        "active_webhooks": 0,
        "active_strategies": 0,
        "group_strategies_allowed": False,
        "can_share_webhooks": False,
        "can_execute": False,
        "marketplace_subscribe": False,
        "marketplace_sell": False,
    },
    SubscriptionTier.STARTER: {
        "connected_accounts": 2,
        "active_webhooks": 3,
        "active_strategies": 3,
        "group_strategies_allowed": True,
        "can_share_webhooks": True,
        "can_execute": True,
        "marketplace_subscribe": True,
        "marketplace_sell": False,
    },
    SubscriptionTier.TRADER: {
        "connected_accounts": 10,
        "active_webhooks": 10,
        "active_strategies": 10,
        "group_strategies_allowed": True,
        "can_share_webhooks": True,
        "can_execute": True,
        "marketplace_subscribe": True,
        "marketplace_sell": True,
    },
    SubscriptionTier.UNLIMITED: {
        "connected_accounts": float('inf'),  # Unlimited
        "active_webhooks": float('inf'),     # Unlimited
        "active_strategies": float('inf'),   # Unlimited
        "group_strategies_allowed": True,
        "can_share_webhooks": True,
        "can_execute": True,
        "marketplace_subscribe": True,
        "marketplace_sell": True,
    }
}


# Pricing information for reference (actual prices in Stripe)
TIER_PRICING = {
    SubscriptionTier.FREE: {
        "monthly": 0,
        "yearly": 0,
    },
    SubscriptionTier.STARTER: {
        "monthly": 49,
        "yearly": 468,  # 20% off ($39/month)
    },
    SubscriptionTier.TRADER: {
        "monthly": 129,
        "yearly": 1188,  # ~$99/month, 20% off
    },
    SubscriptionTier.UNLIMITED: {
        "monthly": 249,
        "yearly": 2388,  # ~$199/month, 20% off
    }
}


def get_tier_limit(tier: str, resource: str) -> int:
    """
    Get the resource limit for a specific subscription tier

    Args:
        tier: Subscription tier (free, starter, trader, unlimited)
        resource: Resource type (connected_accounts, active_webhooks, etc.)

    Returns:
        int: Resource limit number (float('inf') for unlimited)
    """
    tier_enum = SubscriptionTier(tier.lower()) if isinstance(tier, str) else tier

    if tier_enum not in TIER_LIMITS:
        raise ValueError(f"Unknown subscription tier: {tier}")

    if resource not in TIER_LIMITS[tier_enum]:
        raise ValueError(f"Unknown resource type: {resource}")

    return TIER_LIMITS[tier_enum][resource]


def is_feature_allowed(tier: str, feature: str) -> bool:
    """
    Check if a feature is allowed for a specific subscription tier

    Args:
        tier: Subscription tier (free, starter, trader, unlimited)
        feature: Feature to check

    Returns:
        bool: True if the feature is allowed, False otherwise
    """
    tier_enum = SubscriptionTier(tier.lower()) if isinstance(tier, str) else tier

    if tier_enum not in TIER_LIMITS:
        raise ValueError(f"Unknown subscription tier: {tier}")

    if feature not in TIER_LIMITS[tier_enum]:
        raise ValueError(f"Unknown feature: {feature}")

    return TIER_LIMITS[tier_enum][feature]


def check_resource_limit(tier: str, resource: str, current_count: int) -> bool:
    """
    Check if adding another resource would exceed the tier's limit

    Args:
        tier: Subscription tier (free, starter, trader, unlimited)
        resource: Resource type to check
        current_count: Current number of resources in use

    Returns:
        bool: True if adding another resource is allowed, False otherwise
    """
    limit = get_tier_limit(tier, resource)

    # Special case for unlimited resources
    if limit == float('inf'):
        return True

    return current_count < limit


def is_in_trial_period(subscription_created_at: datetime) -> bool:
    """
    Check if a subscription is still in the trial period

    Args:
        subscription_created_at: When the subscription was created

    Returns:
        bool: True if in trial period, False otherwise
    """
    if not subscription_created_at:
        return False

    trial_end_date = subscription_created_at + timedelta(days=7)  # 7-day trial
    return datetime.utcnow() <= trial_end_date


def get_tier_limits(tier: str) -> Dict[str, Any]:
    """
    Get all resource limits for a specific subscription tier

    Args:
        tier: Subscription tier (free, starter, trader, unlimited)

    Returns:
        Dict: All limits for the tier
    """
    tier_enum = SubscriptionTier(tier.lower()) if isinstance(tier, str) else tier

    if tier_enum not in TIER_LIMITS:
        raise ValueError(f"Unknown subscription tier: {tier}")

    return TIER_LIMITS[tier_enum].copy()


def get_next_tier(current_tier: str) -> Optional[str]:
    """
    Get the next tier up from the current one

    Args:
        current_tier: Current subscription tier

    Returns:
        Optional[str]: Next tier name or None if already at highest tier
    """
    tier_order = [
        SubscriptionTier.FREE,
        SubscriptionTier.STARTER,
        SubscriptionTier.TRADER,
        SubscriptionTier.UNLIMITED
    ]

    try:
        current_enum = SubscriptionTier(current_tier.lower())
        current_index = tier_order.index(current_enum)

        if current_index < len(tier_order) - 1:
            return tier_order[current_index + 1].value
        return None
    except (ValueError, IndexError):
        return None


def can_execute_trades(tier: str) -> bool:
    """
    Check if a tier can execute trades

    Args:
        tier: Subscription tier

    Returns:
        bool: True if tier can execute trades
    """
    return is_feature_allowed(tier, "can_execute")


def can_sell_on_marketplace(tier: str) -> bool:
    """
    Check if a tier can sell strategies on the marketplace

    Args:
        tier: Subscription tier

    Returns:
        bool: True if tier can sell on marketplace
    """
    return is_feature_allowed(tier, "marketplace_sell")