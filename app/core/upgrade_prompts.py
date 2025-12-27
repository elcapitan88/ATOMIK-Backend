# app/core/upgrade_prompts.py
"""
Centralized module for handling subscription upgrade prompts and messaging.
This ensures consistent upgrade messaging throughout the application.
"""
from typing import Dict, Any, Optional, Tuple
from fastapi import HTTPException, Response
from app.core.config import settings

# Base URL for pricing page
PRICING_URL = f"{settings.FRONTEND_URL}/pricing"

# Define common upgrade reasons with consistent naming
class UpgradeReason:
    ACCOUNT_LIMIT = "account_limit"
    WEBHOOK_LIMIT = "webhook_limit"
    STRATEGY_LIMIT = "strategy_limit"
    GROUP_STRATEGY = "group_strategy"
    WEBHOOK_SHARING = "webhook_sharing"
    ADVANCED_FEATURES = "advanced_features"
    API_RATE_LIMIT = "api_rate_limit"
    WEBHOOK_RATE_LIMIT = "webhook_rate_limit"
    MARKETPLACE_SELL = "marketplace_sell"
    EXECUTION_REQUIRED = "execution_required"

# Define tier details for quick reference
TIER_DETAILS = {
    "free": {
        "name": "Free",
        "accounts": "0",
        "webhooks": "0",
        "strategies": "0",
        "group_strategies": False,
        "webhook_sharing": False,
        "can_execute": False,
        "marketplace_subscribe": False,
        "marketplace_sell": False,
    },
    "starter": {
        "name": "Starter",
        "accounts": "2",
        "webhooks": "3",
        "strategies": "3",
        "group_strategies": True,
        "webhook_sharing": True,
        "can_execute": True,
        "marketplace_subscribe": True,
        "marketplace_sell": False,
        "price_monthly": "$49/month",
        "price_yearly": "$468/year ($39/month)",
    },
    "trader": {
        "name": "Trader",
        "accounts": "10",
        "webhooks": "10",
        "strategies": "10",
        "group_strategies": True,
        "webhook_sharing": True,
        "can_execute": True,
        "marketplace_subscribe": True,
        "marketplace_sell": True,
        "price_monthly": "$129/month",
        "price_yearly": "$1,188/year (~$99/month)",
    },
    "unlimited": {
        "name": "Unlimited",
        "accounts": "Unlimited",
        "webhooks": "Unlimited",
        "strategies": "Unlimited",
        "group_strategies": True,
        "webhook_sharing": True,
        "can_execute": True,
        "marketplace_subscribe": True,
        "marketplace_sell": True,
        "price_monthly": "$249/month",
        "price_yearly": "$2,388/year (~$199/month)",
    }
}

# Upgrade messages by reason
UPGRADE_MESSAGES = {
    UpgradeReason.ACCOUNT_LIMIT: {
        "free": "Free accounts cannot connect trading accounts. Upgrade to Starter ($49/month) to connect up to 2 accounts.",
        "starter": "You've reached the maximum number of connected accounts (2) for your Starter plan. Upgrade to Trader ($129/month) for up to 10 accounts, or Unlimited ($249/month) for unlimited accounts.",
        "trader": "You've reached the maximum number of connected accounts (10) for your Trader plan. Upgrade to Unlimited ($249/month) for unlimited accounts.",
    },
    UpgradeReason.WEBHOOK_LIMIT: {
        "free": "Free accounts cannot create webhooks. Upgrade to Starter ($49/month) to create up to 3 webhooks.",
        "starter": "You've reached the maximum number of webhooks (3) for your Starter plan. Upgrade to Trader ($129/month) for up to 10 webhooks, or Unlimited ($249/month) for unlimited webhooks.",
        "trader": "You've reached the maximum number of webhooks (10) for your Trader plan. Upgrade to Unlimited ($249/month) for unlimited webhooks.",
    },
    UpgradeReason.STRATEGY_LIMIT: {
        "free": "Free accounts cannot create strategies. Upgrade to Starter ($49/month) to create up to 3 strategies.",
        "starter": "You've reached the maximum number of strategies (3) for your Starter plan. Upgrade to Trader ($129/month) for up to 10 strategies, or Unlimited ($249/month) for unlimited strategies.",
        "trader": "You've reached the maximum number of strategies (10) for your Trader plan. Upgrade to Unlimited ($249/month) for unlimited strategies.",
    },
    UpgradeReason.GROUP_STRATEGY: {
        "free": "Group strategies require a paid subscription. Upgrade to Starter ($49/month) to access this feature.",
    },
    UpgradeReason.WEBHOOK_SHARING: {
        "free": "Webhook sharing requires a paid subscription. Upgrade to Starter ($49/month) to access this feature.",
    },
    UpgradeReason.MARKETPLACE_SELL: {
        "free": "Selling strategies on the marketplace requires the Trader plan ($129/month) or higher.",
        "starter": "Selling strategies on the marketplace requires the Trader plan ($129/month) or higher. Upgrade to start earning from your strategies.",
    },
    UpgradeReason.EXECUTION_REQUIRED: {
        "free": "Trade execution requires a paid subscription. Upgrade to Starter ($49/month) to start trading.",
    },
    UpgradeReason.WEBHOOK_RATE_LIMIT: {
        "starter": "You've exceeded the webhook rate limit for your Starter tier. Upgrade to Trader or Unlimited for higher limits.",
        "trader": "You've exceeded the webhook rate limit for your Trader tier. Upgrade to Unlimited for the highest limits.",
    },
    UpgradeReason.API_RATE_LIMIT: {
        "starter": "You've exceeded the API rate limit for your Starter tier. Upgrade to Trader or Unlimited for higher limits.",
        "trader": "You've exceeded the API rate limit for your Trader tier. Upgrade to Unlimited for the highest limits.",
    },
    UpgradeReason.ADVANCED_FEATURES: {
        "free": "This feature requires a paid subscription. Upgrade to Starter ($49/month) to access it.",
        "starter": "This feature requires the Trader plan ($129/month) or higher.",
    }
}

def get_upgrade_message(reason: str, current_tier: str) -> str:
    """
    Get the appropriate upgrade message based on reason and current tier.

    Args:
        reason: The reason code for the upgrade prompt
        current_tier: User's current subscription tier

    Returns:
        str: The formatted upgrade message
    """
    # Normalize tier name
    current_tier = current_tier.lower() if current_tier else "free"

    # If tier not found, default to free
    if current_tier not in ["free", "starter", "trader", "unlimited"]:
        current_tier = "free"

    # Unlimited tier doesn't need upgrade messages
    if current_tier == "unlimited":
        return "You already have the highest tier (Unlimited)."

    # Get message for reason and tier
    tier_messages = UPGRADE_MESSAGES.get(reason, {})
    message = tier_messages.get(current_tier)

    # Default message if specific one not found
    if not message:
        next_tier = get_next_tier(current_tier)
        next_tier_name = TIER_DETAILS.get(next_tier, {}).get("name", "a higher tier")
        message = f"This feature or limit requires a higher tier. Please upgrade to {next_tier_name} to access it."

    return message

def get_next_tier(current_tier: str) -> Optional[str]:
    """Get the next tier up from the current one"""
    current_tier = current_tier.lower() if current_tier else "free"
    if current_tier == "free":
        return "starter"
    elif current_tier == "starter":
        return "trader"
    elif current_tier == "trader":
        return "unlimited"
    return None

def build_upgrade_response(
    reason: str,
    current_tier: str,
    status_code: int = 403,
    add_headers: bool = True
) -> Dict[str, Any]:
    """
    Build a standardized upgrade response.

    Args:
        reason: The reason code for the upgrade prompt
        current_tier: User's current subscription tier
        status_code: HTTP status code to use
        add_headers: Whether to add upgrade headers

    Returns:
        dict: Response body with upgrade information
    """
    message = get_upgrade_message(reason, current_tier)
    next_tier = get_next_tier(current_tier)

    response = {
        "detail": message,
        "error_code": "subscription_limit",
        "reason": reason,
        "current_tier": current_tier,
        "upgrade_url": f"{PRICING_URL}?from={current_tier}&to={next_tier}" if next_tier else None,
    }

    # Add comparison between current tier and recommended next tier
    if next_tier:
        response["tier_comparison"] = {
            "current": TIER_DETAILS.get(current_tier, {}),
            "recommended": TIER_DETAILS.get(next_tier, {})
        }

    return response

def upgrade_exception(
    reason: str,
    current_tier: str,
    detail: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None
) -> HTTPException:
    """
    Create an HTTPException with upgrade information.

    Args:
        reason: The reason code for the upgrade prompt
        current_tier: User's current subscription tier
        detail: Optional custom message
        headers: Additional headers to include

    Returns:
        HTTPException: Exception with upgrade information
    """
    message = detail or get_upgrade_message(reason, current_tier)
    next_tier = get_next_tier(current_tier)

    error_headers = headers or {}
    if next_tier:
        error_headers.update({
            "X-Upgrade-Required": "true",
            "X-Current-Tier": current_tier,
            "X-Recommended-Tier": next_tier,
            "X-Upgrade-Reason": reason,
            "X-Upgrade-URL": f"{PRICING_URL}?from={current_tier}&to={next_tier}"
        })

    return HTTPException(
        status_code=403,
        detail=message,
        headers=error_headers
    )

def add_upgrade_headers(response: Response, current_tier: str, reason: str) -> None:
    """
    Add upgrade-related headers to a FastAPI response.

    Args:
        response: FastAPI Response object
        current_tier: User's current subscription tier
        reason: Reason for the upgrade prompt
    """
    next_tier = get_next_tier(current_tier)
    if next_tier:
        response.headers["X-Upgrade-Required"] = "true"
        response.headers["X-Current-Tier"] = current_tier
        response.headers["X-Recommended-Tier"] = next_tier
        response.headers["X-Upgrade-Reason"] = reason
        response.headers["X-Upgrade-URL"] = f"{PRICING_URL}?from={current_tier}&to={next_tier}"
