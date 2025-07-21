# app/schemas/creator.py
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from decimal import Decimal
from datetime import datetime


class SocialLinks(BaseModel):
    twitter: Optional[str] = None
    linkedin: Optional[str] = None
    discord: Optional[str] = None


class CreatorProfileCreate(BaseModel):
    bio: Optional[str] = Field(None, max_length=1000, description="Creator bio")
    trading_experience: Optional[str] = Field(None, max_length=50, description="Trading experience level")
    two_fa_enabled: bool = Field(False, description="Whether 2FA is enabled")


class CreatorProfileUpdate(BaseModel):
    display_name: Optional[str] = Field(None, max_length=100, description="Creator display name")
    bio: Optional[str] = Field(None, max_length=1000, description="Creator bio")
    trading_experience: Optional[str] = Field(None, max_length=50, description="Trading experience level")
    two_fa_enabled: Optional[bool] = Field(None, description="Whether 2FA is enabled")


class CreatorProfileResponse(BaseModel):
    id: str
    user_id: int
    display_name: Optional[str]
    bio: Optional[str]
    trading_experience: Optional[str]
    total_subscribers: int
    current_tier: str
    platform_fee_override: Optional[Decimal]
    stripe_connect_account_id: Optional[str]
    is_verified: bool
    two_fa_enabled: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

    @property
    def platform_fee_percentage(self) -> float:
        """Get platform fee as percentage for display."""
        if self.platform_fee_override is not None:
            return float(self.platform_fee_override) * 100
        
        tier_fees = {
            'bronze': 20.0,
            'silver': 15.0,
            'gold': 10.0
        }
        return tier_fees.get(self.current_tier, 20.0)


class CreatorEarningsResponse(BaseModel):
    id: str
    creator_id: str
    purchase_id: str
    gross_amount: Decimal
    platform_fee: Decimal
    net_amount: Decimal
    payout_status: str
    payout_date: Optional[datetime]
    stripe_transfer_id: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class StrategyPerformance(BaseModel):
    strategy_name: str
    subscriber_count: int
    revenue: float


class EarningsHistory(BaseModel):
    amount: float
    date: datetime
    status: str


class CreatorAnalyticsResponse(BaseModel):
    total_revenue: Decimal
    total_subscribers: int
    active_strategies: int
    conversion_rate: float
    revenue_growth: float
    subscriber_growth: float
    top_performing_strategies: List[StrategyPerformance]
    recent_earnings: List[EarningsHistory]


class StripeConnectSetupRequest(BaseModel):
    refresh_url: str = Field(..., description="URL to redirect if user needs to refresh onboarding")
    return_url: str = Field(..., description="URL to redirect after successful onboarding")


class StripeConnectSetupResponse(BaseModel):
    account_link_url: str = Field(..., description="Stripe onboarding URL")
    account_id: str = Field(..., description="Stripe Connect account ID")


class TierProgressResponse(BaseModel):
    current_tier: str
    current_subscribers: int
    current_fee_percentage: float
    next_tier: Optional[str]
    subscribers_to_next_tier: int
    progress_percentage: float
    tier_benefits: Optional[Dict[str, Any]]
    next_tier_benefits: Optional[Dict[str, Any]]