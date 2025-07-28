# fastapi_backend/app/schemas/strategy_monetization.py
from pydantic import BaseModel, Field, validator
from typing import List, Optional, Dict, Any
from decimal import Decimal
from datetime import datetime
from enum import Enum

class PriceType(str, Enum):
    MONTHLY = "monthly"
    YEARLY = "yearly"
    LIFETIME = "lifetime"
    SETUP = "setup"

class BillingInterval(str, Enum):
    MONTH = "month"
    YEAR = "year"

class PricingOptionCreate(BaseModel):
    price_type: PriceType
    amount: float = Field(..., gt=0, description="Price amount in USD")
    billing_interval: Optional[BillingInterval] = None
    trial_period_days: int = Field(default=0, ge=0, le=30, description="Trial period in days (0-30)")
    
    @validator('billing_interval', always=True)
    def validate_billing_interval(cls, v, values):
        price_type = values.get('price_type')
        if price_type in [PriceType.MONTHLY, PriceType.YEARLY]:
            if v is None:
                # Set default based on price type
                return BillingInterval.MONTH if price_type == PriceType.MONTHLY else BillingInterval.YEAR
        elif price_type in [PriceType.LIFETIME, PriceType.SETUP]:
            if v is not None:
                raise ValueError(f"billing_interval must be null for {price_type} pricing")
            return None
        return v
    
    @validator('amount')
    def validate_amount_by_type(cls, v, values):
        price_type = values.get('price_type')
        min_amounts = {
            PriceType.SETUP: 1.0,
            PriceType.MONTHLY: 5.0,
            PriceType.YEARLY: 10.0,
            PriceType.LIFETIME: 10.0
        }
        if price_type and v < min_amounts.get(price_type, 1.0):
            raise ValueError(f"Minimum amount for {price_type} is ${min_amounts[price_type]}")
        return v
    
    @validator('trial_period_days')
    def validate_trial_period(cls, v, values):
        price_type = values.get('price_type')
        if v > 0 and price_type not in [PriceType.MONTHLY, PriceType.YEARLY]:
            raise ValueError("Trial periods are only available for subscription pricing")
        return v

class PricingOptionResponse(BaseModel):
    id: str
    price_type: str
    stripe_price_id: str
    amount: float
    currency: str
    billing_interval: Optional[str]
    trial_period_days: int
    is_active: bool
    display_name: str
    description: str
    
    class Config:
        from_attributes = True

class StrategyMonetizationCreate(BaseModel):
    pricing_options: List[PricingOptionCreate] = Field(..., min_items=1, max_items=4)
    
    @validator('pricing_options')
    def validate_unique_price_types(cls, v):
        price_types = [option.price_type for option in v]
        if len(price_types) != len(set(price_types)):
            raise ValueError("Each price type can only be specified once")
        return v

class StrategyMonetizationResponse(BaseModel):
    id: str
    webhook_id: int
    stripe_product_id: str
    creator_user_id: int
    is_active: bool
    total_subscribers: int
    estimated_monthly_revenue: float
    created_at: datetime
    prices: List[PricingOptionResponse]
    
    class Config:
        from_attributes = True

class StrategyPricingQuery(BaseModel):
    """Response model for public pricing queries (by webhook token)"""
    strategy_name: str
    creator_username: str
    pricing_options: List[Dict[str, Any]]
    
class MonetizationSetupRequest(BaseModel):
    pricing_options: List[PricingOptionCreate]

class MonetizationUpdateRequest(BaseModel):
    pricing_options: List[PricingOptionCreate]
    deactivate_existing: bool = Field(default=True, description="Whether to deactivate existing prices")

class PricingOptionUpdate(BaseModel):
    price_type: PriceType
    amount: Optional[float] = Field(None, gt=0)
    trial_period_days: Optional[int] = Field(None, ge=0, le=30)
    is_active: Optional[bool] = None

class MonetizationStatsResponse(BaseModel):
    """Response model for monetization statistics"""
    total_subscribers: int
    estimated_monthly_revenue: float
    active_pricing_options: int
    total_revenue_to_date: float
    platform_fee_percentage: float = 15.0
    creator_revenue_percentage: float = 85.0

class StripeProductResponse(BaseModel):
    """Response for Stripe product creation"""
    stripe_product_id: str
    product_name: str
    product_description: str
    created_at: datetime
    
class StripePriceResponse(BaseModel):
    """Response for Stripe price creation"""
    stripe_price_id: str
    amount: float
    currency: str
    billing_interval: Optional[str]
    trial_period_days: int
    created_at: datetime

# Error response models
class MonetizationError(BaseModel):
    error_code: str
    message: str
    details: Optional[Dict[str, Any]] = None

class ValidationError(BaseModel):
    field: str
    message: str
    value: Any

class MonetizationValidationError(BaseModel):
    error_code: str = "VALIDATION_ERROR"
    message: str = "Validation failed"
    validation_errors: List[ValidationError]

class PurchaseRequest(BaseModel):
    price_type: PriceType
    customer_email: Optional[str] = None

class PurchaseResponse(BaseModel):
    checkout_url: str
    session_id: str