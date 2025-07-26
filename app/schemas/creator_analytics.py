# app/schemas/creator_analytics.py
from pydantic import BaseModel
from typing import Dict, List, Optional, Any
from datetime import datetime


class RevenueBreakdown(BaseModel):
    monthly: float
    yearly: float
    lifetime: float
    setup_fee: float


class RevenueResponse(BaseModel):
    total_revenue: float
    net_revenue: float
    platform_fee: float
    available_balance: float
    pending_balance: float
    breakdown: RevenueBreakdown
    currency: str = "usd"


class SubscriberBreakdown(BaseModel):
    monthly: int
    yearly: int
    lifetime: int


class SubscriberResponse(BaseModel):
    total_active: int
    total_trials: int
    breakdown: SubscriberBreakdown
    mrr: float  # Monthly Recurring Revenue
    arr: float  # Annual Recurring Revenue


class StrategyPerformance(BaseModel):
    strategy_id: str
    strategy_name: str
    views: int
    unique_viewers: int
    trial_starts: int
    conversion_rate: float
    avg_view_duration: float


class MetricsResponse(BaseModel):
    total_views: int
    total_unique_viewers: int
    total_trial_starts: int
    overall_conversion_rate: float
    top_strategies: List[StrategyPerformance]
    strategy_count: int


class RecentPayout(BaseModel):
    id: str
    amount: float
    status: str
    arrival_date: str
    created: str


class PayoutResponse(BaseModel):
    total_paid: float
    pending_payouts: float
    recent_payouts: List[RecentPayout]
    payout_schedule: str
    currency: str = "usd"


class DashboardResponse(BaseModel):
    revenue: RevenueResponse
    subscribers: SubscriberResponse
    metrics: MetricsResponse
    payouts: PayoutResponse
    period: str
    generated_at: str