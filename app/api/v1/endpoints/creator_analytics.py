# app/api/v1/endpoints/creator_analytics.py
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session

from app.api import deps
from app.models.user import User
from app.models.creator_profile import CreatorProfile
from app.services.creator_analytics_service import CreatorAnalyticsService
from app.schemas.creator_analytics import (
    DashboardResponse,
    RevenueResponse,
    SubscriberResponse,
    MetricsResponse,
    PayoutResponse
)

router = APIRouter()


@router.get("/dashboard", response_model=DashboardResponse)
async def get_creator_dashboard(
    period: str = Query("30d", regex="^(7d|30d|90d|1y)$"),
    current_user: User = Depends(deps.get_current_user),
    db: Session = Depends(deps.get_db)
) -> Dict[str, Any]:
    """
    Get comprehensive creator dashboard data.
    
    Period options:
    - 7d: Last 7 days
    - 30d: Last 30 days
    - 90d: Last 90 days
    - 1y: Last year
    """
    # Check if user is a creator
    creator_profile = db.query(CreatorProfile).filter(
        CreatorProfile.user_id == current_user.id
    ).first()
    
    if not creator_profile:
        raise HTTPException(
            status_code=403,
            detail="User is not a creator"
        )
    
    if not creator_profile.stripe_connect_id:
        raise HTTPException(
            status_code=400,
            detail="Creator has not completed Stripe Connect setup"
        )
    
    analytics_service = CreatorAnalyticsService(db)
    dashboard_data = await analytics_service.get_creator_dashboard(
        creator_id=current_user.id,
        period=period
    )
    
    return dashboard_data


@router.get("/revenue", response_model=RevenueResponse)
async def get_revenue_data(
    period: str = Query("30d", regex="^(7d|30d|90d|1y)$"),
    current_user: User = Depends(deps.get_current_user),
    db: Session = Depends(deps.get_db)
) -> Dict[str, Any]:
    """Get revenue data for the creator."""
    creator_profile = db.query(CreatorProfile).filter(
        CreatorProfile.user_id == current_user.id
    ).first()
    
    if not creator_profile or not creator_profile.stripe_connect_id:
        raise HTTPException(
            status_code=403,
            detail="Creator profile not found or Stripe not connected"
        )
    
    analytics_service = CreatorAnalyticsService(db)
    revenue_data = await analytics_service._get_revenue_data(
        stripe_account_id=creator_profile.stripe_connect_id,
        period=period
    )
    
    return revenue_data


@router.get("/subscribers", response_model=SubscriberResponse)
async def get_subscriber_data(
    current_user: User = Depends(deps.get_current_user),
    db: Session = Depends(deps.get_db)
) -> Dict[str, Any]:
    """Get subscriber data for the creator."""
    creator_profile = db.query(CreatorProfile).filter(
        CreatorProfile.user_id == current_user.id
    ).first()
    
    if not creator_profile or not creator_profile.stripe_connect_id:
        raise HTTPException(
            status_code=403,
            detail="Creator profile not found or Stripe not connected"
        )
    
    analytics_service = CreatorAnalyticsService(db)
    subscriber_data = await analytics_service._get_subscriber_data(
        stripe_account_id=creator_profile.stripe_connect_id
    )
    
    return subscriber_data


@router.get("/metrics", response_model=MetricsResponse)
async def get_strategy_metrics(
    period: str = Query("30d", regex="^(7d|30d|90d|1y)$"),
    strategy_id: Optional[str] = None,
    current_user: User = Depends(deps.get_current_user),
    db: Session = Depends(deps.get_db)
) -> Dict[str, Any]:
    """Get strategy performance metrics."""
    analytics_service = CreatorAnalyticsService(db)
    metrics_data = await analytics_service._get_strategy_metrics(
        creator_id=current_user.id,
        period=period
    )
    
    return metrics_data


@router.get("/payouts", response_model=PayoutResponse)
async def get_payout_data(
    period: str = Query("30d", regex="^(7d|30d|90d|1y)$"),
    current_user: User = Depends(deps.get_current_user),
    db: Session = Depends(deps.get_db)
) -> Dict[str, Any]:
    """Get payout data for the creator."""
    creator_profile = db.query(CreatorProfile).filter(
        CreatorProfile.user_id == current_user.id
    ).first()
    
    if not creator_profile or not creator_profile.stripe_connect_id:
        raise HTTPException(
            status_code=403,
            detail="Creator profile not found or Stripe not connected"
        )
    
    analytics_service = CreatorAnalyticsService(db)
    payout_data = await analytics_service._get_payout_data(
        stripe_account_id=creator_profile.stripe_connect_id,
        period=period
    )
    
    return payout_data


@router.post("/track/view")
async def track_strategy_view(
    strategy_id: str,
    duration: Optional[float] = None,
    current_user: Optional[User] = Depends(deps.get_current_user_optional),
    db: Session = Depends(deps.get_db)
) -> Dict[str, str]:
    """Track a strategy view (public endpoint for analytics)."""
    analytics_service = CreatorAnalyticsService(db)
    
    await analytics_service.track_strategy_view(
        strategy_id=strategy_id,
        viewer_id=current_user.id if current_user else None,
        duration=duration
    )
    
    return {"status": "tracked"}