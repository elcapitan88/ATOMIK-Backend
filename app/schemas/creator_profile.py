"""Schemas for creator profile social features."""
from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel


class CreatorProfilePublic(BaseModel):
    """Public creator profile schema for social viewing."""
    user_id: int
    username: str
    profile_picture: Optional[str] = None
    bio: Optional[str] = None
    trading_experience: Optional[str] = None
    follower_count: int = 0
    total_subscribers: int = 0
    strategy_count: int = 0
    created_at: datetime
    is_following: bool = False
    is_verified: bool = False
    current_tier: str = "bronze"
    social_media: Dict[str, str] = {}

    class Config:
        from_attributes = True


class CreatorFollowResponse(BaseModel):
    """Response for follow/unfollow actions."""
    is_following: bool
    follower_count: int


class CreatorStrategyItem(BaseModel):
    """Individual strategy item in creator's strategy list."""
    id: str
    webhook_id: int
    name: str
    description: Optional[str] = None
    stripe_product_id: Optional[str] = None  # Can be None for free strategies
    total_subscribers: int = 0
    estimated_monthly_revenue: float = 0.0
    min_price: Optional[float] = None
    created_at: datetime
    is_monetized: bool = False  # Indicates if strategy is monetized
    usage_intent: Optional[str] = None  # personal, share_free, monetize
    rating: float = 0.0  # Strategy rating

    class Config:
        from_attributes = True


class CreatorStrategyList(BaseModel):
    """List of creator's strategies with pagination."""
    strategies: List[Dict[str, Any]]
    total: int
    has_more: bool


class FollowerItem(BaseModel):
    """Individual follower item."""
    user_id: int
    username: str
    profile_picture: Optional[str] = None
    followed_at: datetime

    class Config:
        from_attributes = True


class FollowerList(BaseModel):
    """List of followers with pagination."""
    followers: List[FollowerItem]
    total: int
    has_more: bool


class FollowingItem(BaseModel):
    """Individual following item."""
    user_id: int
    username: str
    profile_picture: Optional[str] = None
    followed_at: datetime

    class Config:
        from_attributes = True


class FollowingList(BaseModel):
    """List of users being followed with pagination."""
    following: List[FollowingItem]
    total: int
    has_more: bool