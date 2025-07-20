# app/schemas/marketplace.py
from pydantic import BaseModel, Field
from typing import Optional, List
from decimal import Decimal
from datetime import datetime
from enum import Enum

from app.models.strategy_pricing import PricingType, BillingInterval
from app.models.strategy_purchase import PurchaseStatus, PurchaseType


class StrategyPricingCreate(BaseModel):
    webhook_id: int = Field(..., description="ID of the webhook/strategy")
    pricing_type: PricingType = Field(..., description="Type of pricing model")
    billing_interval: Optional[BillingInterval] = Field(None, description="Billing interval for subscriptions")
    base_amount: Optional[Decimal] = Field(None, description="Base price (monthly for subscriptions)")
    yearly_amount: Optional[Decimal] = Field(None, description="Yearly price (optional discount)")
    setup_fee: Optional[Decimal] = Field(None, description="One-time setup fee")
    trial_days: Optional[int] = Field(0, description="Number of trial days")
    is_trial_enabled: Optional[bool] = Field(False, description="Whether trials are enabled")

    class Config:
        use_enum_values = True


class StrategyPricingUpdate(BaseModel):
    pricing_type: Optional[PricingType] = None
    billing_interval: Optional[BillingInterval] = None
    base_amount: Optional[Decimal] = None
    yearly_amount: Optional[Decimal] = None
    setup_fee: Optional[Decimal] = None
    trial_days: Optional[int] = None
    is_trial_enabled: Optional[bool] = None
    is_active: Optional[bool] = None

    class Config:
        use_enum_values = True


class StrategyPricingResponse(BaseModel):
    id: str
    webhook_id: int
    pricing_type: str
    billing_interval: Optional[str]
    base_amount: Optional[Decimal]
    yearly_amount: Optional[Decimal]
    setup_fee: Optional[Decimal]
    trial_days: int
    is_trial_enabled: bool
    stripe_price_id: Optional[str]
    stripe_yearly_price_id: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class StrategyPurchaseRequest(BaseModel):
    payment_method_id: str = Field(..., description="Stripe payment method ID")
    start_trial: bool = Field(False, description="Whether to start with trial period")


class SubscriptionRequest(BaseModel):
    payment_method_id: str = Field(..., description="Stripe payment method ID")
    billing_interval: BillingInterval = Field(..., description="Monthly or yearly billing")
    start_trial: bool = Field(False, description="Whether to start with trial period")

    class Config:
        use_enum_values = True


class StrategyPurchaseResponse(BaseModel):
    id: str
    user_id: int
    webhook_id: int
    pricing_id: str
    stripe_payment_intent_id: Optional[str]
    stripe_subscription_id: Optional[str]
    amount_paid: Decimal
    platform_fee: Decimal
    creator_payout: Decimal
    purchase_type: str
    status: str
    trial_ends_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class SubscriptionResponse(BaseModel):
    id: str
    user_id: int
    webhook_id: int
    pricing_id: str
    stripe_subscription_id: str
    amount_paid: Decimal
    platform_fee: Decimal
    creator_payout: Decimal
    purchase_type: str
    status: str
    trial_ends_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class UserPurchaseSummary(BaseModel):
    id: str
    status: str
    purchase_type: str
    amount_paid: Decimal
    trial_ends_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class PricingOptionsResponse(BaseModel):
    webhook_id: int
    pricing_type: str
    base_amount: Optional[Decimal] = None
    yearly_amount: Optional[Decimal] = None
    setup_fee: Optional[Decimal] = None
    trial_days: Optional[int] = 0
    is_trial_enabled: bool = False
    billing_intervals: List[str] = []
    is_free: bool
    user_has_access: bool
    user_purchase: Optional[UserPurchaseSummary] = None

    class Config:
        from_attributes = True