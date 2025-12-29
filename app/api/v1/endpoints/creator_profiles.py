"""Creator profile endpoints for social features."""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, and_, desc
from decimal import Decimal

from app.api.deps import get_db, get_current_user, get_current_user_optional
from app.models.user import User
from app.models.creator_profile import CreatorProfile
from app.models.creator_follower import CreatorFollower
from app.models.strategy_monetization import StrategyMonetization
from app.models.strategy_code import StrategyCode
from app.models.webhook import Webhook
from app.schemas.creator_profile import (
    CreatorProfilePublic,
    CreatorFollowResponse,
    CreatorStrategyList
)

router = APIRouter()


# =============================================================================
# Phase 2: Helper function for creator aggregate performance metrics
# =============================================================================

def _calculate_creator_aggregate_performance(db: Session, user_id: int) -> dict:
    """
    Calculate aggregate performance metrics across all of a creator's published strategies.
    Only includes locked/published strategies with verified live trades.
    """
    # Get all locked strategies for this creator (published to marketplace)
    strategies = db.query(StrategyCode).filter(
        StrategyCode.user_id == user_id,
        StrategyCode.locked_at.isnot(None)  # Only published/locked strategies
    ).all()

    if not strategies:
        return {
            "published_strategies_count": 0,
            "total_live_trades": 0,
            "total_live_winning_trades": 0,
            "total_live_pnl": 0.0,
            "aggregate_win_rate": 0.0,
            "has_performance_data": False
        }

    # Aggregate metrics
    total_trades = sum(s.live_total_trades or 0 for s in strategies)
    total_wins = sum(s.live_winning_trades or 0 for s in strategies)
    total_pnl = sum(float(s.live_total_pnl or 0) for s in strategies)

    # Calculate aggregate win rate
    aggregate_win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0.0

    return {
        "published_strategies_count": len(strategies),
        "total_live_trades": total_trades,
        "total_live_winning_trades": total_wins,
        "total_live_pnl": round(total_pnl, 2),
        "aggregate_win_rate": round(aggregate_win_rate, 2),
        "has_performance_data": total_trades > 0
    }


@router.get("/profile/{username}")
async def get_creator_profile_by_username(
    username: str,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    """Get creator profile by username for public viewing."""

    # Find user by username
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="Creator not found")

    # Check if user is a creator
    creator_profile = db.query(CreatorProfile).filter(
        CreatorProfile.user_id == user.id
    ).first()

    if not creator_profile:
        raise HTTPException(status_code=404, detail="Creator profile not found")

    # Count shared strategies (both monetized and free)
    strategy_count = db.query(func.count(Webhook.id)).filter(
        and_(
            Webhook.user_id == user.id,
            Webhook.is_shared == True,
            Webhook.is_active == True
        )
    ).scalar() or 0

    # Check if current user is following this creator
    is_following = False
    if current_user:
        is_following = db.query(CreatorFollower).filter(
            and_(
                CreatorFollower.follower_user_id == current_user.id,
                CreatorFollower.creator_user_id == user.id
            )
        ).first() is not None

    # Build social media dict
    social_media = {}
    if user.x_handle:
        social_media['x_handle'] = user.x_handle
    if user.tiktok_handle:
        social_media['tiktok_handle'] = user.tiktok_handle
    if user.instagram_handle:
        social_media['instagram_handle'] = user.instagram_handle
    if user.youtube_handle:
        social_media['youtube_handle'] = user.youtube_handle
    if user.discord_handle:
        social_media['discord_handle'] = user.discord_handle

    # Phase 2: Calculate aggregate performance metrics
    performance = _calculate_creator_aggregate_performance(db, user.id)

    return {
        "user_id": user.id,
        "username": user.username,
        "profile_picture": user.profile_picture,
        "bio": creator_profile.bio,
        "trading_experience": creator_profile.trading_experience,
        "follower_count": creator_profile.follower_count,
        "total_subscribers": creator_profile.total_subscribers,
        "strategy_count": strategy_count,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "is_following": is_following,
        "is_verified": creator_profile.is_verified,
        "current_tier": creator_profile.current_tier,
        "social_media": social_media,
        # Phase 2: Trust metrics - aggregate performance across all strategies
        "performance": performance
    }


@router.get("/{creator_id}/strategies", response_model=CreatorStrategyList)
async def get_creator_strategies(
    creator_id: int,
    db: Session = Depends(get_db),
    limit: int = Query(20, le=100),
    offset: int = Query(0, ge=0),
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    """Get list of creator's shared strategies (both monetized and free)."""

    # Verify creator exists
    creator = db.query(User).filter(User.id == creator_id).first()
    if not creator:
        raise HTTPException(status_code=404, detail="Creator not found")

    # Get shared webhooks (both monetized and non-monetized)
    shared_webhooks = db.query(Webhook).filter(
        and_(
            Webhook.user_id == creator_id,
            Webhook.is_shared == True,
            Webhook.is_active == True
        )
    ).order_by(desc(Webhook.sharing_enabled_at)).all()

    # Apply pagination
    total = len(shared_webhooks)
    paginated_webhooks = shared_webhooks[offset:offset + limit]

    # Build strategy list response
    strategy_list = []
    for webhook in paginated_webhooks:
        # Check if webhook is monetized
        monetization = db.query(StrategyMonetization).filter(
            StrategyMonetization.webhook_id == webhook.id
        ).first()

        # Get minimum price for monetized strategies
        min_price = None
        estimated_revenue = 0.0
        if monetization and monetization.prices:
            min_price = min(float(price.amount) for price in monetization.prices)
            estimated_revenue = float(monetization.estimated_monthly_revenue)

        # Check if current user is subscribed to this strategy
        is_subscribed = False
        if current_user:
            from app.models.webhook import WebhookSubscription
            from app.models.strategy_purchases import StrategyPurchase
            # Check for free subscription
            free_sub = db.query(WebhookSubscription).filter(
                WebhookSubscription.webhook_id == webhook.id,
                WebhookSubscription.user_id == current_user.id
            ).first()
            # Check for paid subscription
            paid_sub = db.query(StrategyPurchase).filter(
                StrategyPurchase.webhook_id == webhook.id,
                StrategyPurchase.user_id == current_user.id,
                StrategyPurchase.status.in_(['active', 'completed'])
            ).first()
            is_subscribed = free_sub is not None or paid_sub is not None

        strategy_list.append({
            "id": str(monetization.id) if monetization else f"webhook_{webhook.id}",
            "webhook_id": webhook.id,
            "token": webhook.token,
            "name": webhook.name,
            "description": webhook.details,
            "stripe_product_id": monetization.stripe_product_id if monetization else None,
            "total_subscribers": webhook.subscriber_count or 0,
            "estimated_monthly_revenue": estimated_revenue,
            "min_price": min_price,
            "created_at": webhook.sharing_enabled_at or webhook.created_at,
            "is_monetized": monetization is not None,
            "is_subscribed": is_subscribed,
            "usage_intent": webhook.usage_intent,
            "rating": webhook.rating or 0.0
        })

    return CreatorStrategyList(
        strategies=strategy_list,
        total=total,
        has_more=offset + len(strategy_list) < total
    )


@router.post("/{creator_id}/follow", response_model=CreatorFollowResponse)
async def follow_creator(
    creator_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Follow a creator."""

    # Validate creator exists and is actually a creator
    creator = db.query(User).join(CreatorProfile).filter(
        User.id == creator_id
    ).first()

    if not creator:
        raise HTTPException(status_code=404, detail="Creator not found")

    # Can't follow yourself
    if creator_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot follow yourself")

    # Check if already following
    existing_follow = db.query(CreatorFollower).filter(
        and_(
            CreatorFollower.follower_user_id == current_user.id,
            CreatorFollower.creator_user_id == creator_id
        )
    ).first()

    if existing_follow:
        raise HTTPException(status_code=400, detail="Already following this creator")

    # Create follow relationship
    follow = CreatorFollower(
        follower_user_id=current_user.id,
        creator_user_id=creator_id
    )
    db.add(follow)

    # Update follower count
    creator_profile = db.query(CreatorProfile).filter(
        CreatorProfile.user_id == creator_id
    ).first()
    creator_profile.follower_count += 1

    db.commit()

    return CreatorFollowResponse(
        is_following=True,
        follower_count=creator_profile.follower_count
    )


@router.delete("/{creator_id}/unfollow", response_model=CreatorFollowResponse)
async def unfollow_creator(
    creator_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Unfollow a creator."""

    # Find the follow relationship
    follow = db.query(CreatorFollower).filter(
        and_(
            CreatorFollower.follower_user_id == current_user.id,
            CreatorFollower.creator_user_id == creator_id
        )
    ).first()

    if not follow:
        raise HTTPException(status_code=400, detail="Not following this creator")

    # Remove follow relationship
    db.delete(follow)

    # Update follower count
    creator_profile = db.query(CreatorProfile).filter(
        CreatorProfile.user_id == creator_id
    ).first()
    if creator_profile and creator_profile.follower_count > 0:
        creator_profile.follower_count -= 1

    db.commit()

    return CreatorFollowResponse(
        is_following=False,
        follower_count=creator_profile.follower_count
    )


@router.get("/{creator_id}/followers")
async def get_creator_followers(
    creator_id: int,
    db: Session = Depends(get_db),
    limit: int = Query(20, le=100),
    offset: int = Query(0, ge=0)
):
    """Get list of creator's followers."""

    # Verify creator exists
    creator = db.query(User).filter(User.id == creator_id).first()
    if not creator:
        raise HTTPException(status_code=404, detail="Creator not found")

    # Get paginated followers
    followers_query = db.query(CreatorFollower).join(
        User, CreatorFollower.follower_user_id == User.id
    ).filter(
        CreatorFollower.creator_user_id == creator_id
    ).order_by(desc(CreatorFollower.followed_at))

    total = followers_query.count()
    followers = followers_query.offset(offset).limit(limit).all()

    # Build follower list
    follower_list = []
    for follow in followers:
        follower_list.append({
            "user_id": follow.follower.id,
            "username": follow.follower.username,
            "profile_picture": follow.follower.profile_picture,
            "followed_at": follow.followed_at
        })

    return {
        "followers": follower_list,
        "total": total,
        "has_more": offset + len(followers) < total
    }


@router.get("/users/{user_id}/following")
async def get_user_following(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    limit: int = Query(20, le=100),
    offset: int = Query(0, ge=0)
):
    """Get list of creators that a user is following."""

    # Only allow users to see their own following list (privacy)
    if user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Can only view your own following list")

    # Get paginated following list
    following_query = db.query(CreatorFollower).join(
        User, CreatorFollower.creator_user_id == User.id
    ).filter(
        CreatorFollower.follower_user_id == user_id
    ).order_by(desc(CreatorFollower.followed_at))

    total = following_query.count()
    following = following_query.offset(offset).limit(limit).all()

    # Build following list
    following_list = []
    for follow in following:
        following_list.append({
            "user_id": follow.creator.id,
            "username": follow.creator.username,
            "profile_picture": follow.creator.profile_picture,
            "followed_at": follow.followed_at
        })

    return {
        "following": following_list,
        "total": total,
        "has_more": offset + len(following) < total
    }


# =============================================================================
# Phase 2: Additional Performance Endpoints
# =============================================================================

@router.get("/profile/{username}/performance")
async def get_creator_performance_by_username(
    username: str,
    db: Session = Depends(get_db)
):
    """
    Get aggregate performance metrics for a creator across all their published strategies.
    No authentication required - this is public trust data.

    Returns:
        - published_strategies_count: Number of locked/published strategies
        - total_live_trades: Total verified live trades across all strategies
        - total_live_winning_trades: Total winning trades
        - total_live_pnl: Aggregate P&L across all strategies
        - aggregate_win_rate: Overall win rate percentage
        - strategies: List of individual strategy performance summaries
    """
    # Find user by username
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="Creator not found")

    # Check if user has a creator profile
    creator_profile = db.query(CreatorProfile).filter(
        CreatorProfile.user_id == user.id
    ).first()

    if not creator_profile:
        raise HTTPException(status_code=404, detail="Creator profile not found")

    # Calculate aggregate metrics
    aggregate = _calculate_creator_aggregate_performance(db, user.id)

    # Get individual strategy performance summaries
    strategies = db.query(StrategyCode).filter(
        StrategyCode.user_id == user.id,
        StrategyCode.locked_at.isnot(None)
    ).order_by(desc(StrategyCode.live_total_trades)).all()

    strategy_summaries = []
    for s in strategies:
        strategy_summaries.append({
            "id": s.id,
            "name": s.name,
            "version": s.version,
            "combined_hash": s.combined_hash,
            "short_hash": s.combined_hash[:8] if s.combined_hash else None,
            "locked_at": s.locked_at.isoformat() if s.locked_at else None,
            "live_total_trades": s.live_total_trades or 0,
            "live_winning_trades": s.live_winning_trades or 0,
            "live_total_pnl": float(s.live_total_pnl) if s.live_total_pnl else 0.0,
            "live_win_rate": float(s.live_win_rate) if s.live_win_rate else 0.0,
            "live_first_trade_at": s.live_first_trade_at.isoformat() if s.live_first_trade_at else None,
            "live_last_trade_at": s.live_last_trade_at.isoformat() if s.live_last_trade_at else None
        })

    return {
        "creator_username": username,
        "creator_id": user.id,
        "is_verified": creator_profile.is_verified,
        **aggregate,
        "strategies": strategy_summaries
    }


@router.get("/{creator_id}/performance")
async def get_creator_performance_by_id(
    creator_id: int,
    db: Session = Depends(get_db)
):
    """
    Get aggregate performance metrics for a creator by user ID.
    No authentication required - this is public trust data.
    """
    # Find user by ID
    user = db.query(User).filter(User.id == creator_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Creator not found")

    # Check if user has a creator profile
    creator_profile = db.query(CreatorProfile).filter(
        CreatorProfile.user_id == user.id
    ).first()

    if not creator_profile:
        raise HTTPException(status_code=404, detail="Creator profile not found")

    # Calculate aggregate metrics
    aggregate = _calculate_creator_aggregate_performance(db, user.id)

    # Get individual strategy performance summaries
    strategies = db.query(StrategyCode).filter(
        StrategyCode.user_id == user.id,
        StrategyCode.locked_at.isnot(None)
    ).order_by(desc(StrategyCode.live_total_trades)).all()

    strategy_summaries = []
    for s in strategies:
        strategy_summaries.append({
            "id": s.id,
            "name": s.name,
            "version": s.version,
            "combined_hash": s.combined_hash,
            "short_hash": s.combined_hash[:8] if s.combined_hash else None,
            "locked_at": s.locked_at.isoformat() if s.locked_at else None,
            "live_total_trades": s.live_total_trades or 0,
            "live_winning_trades": s.live_winning_trades or 0,
            "live_total_pnl": float(s.live_total_pnl) if s.live_total_pnl else 0.0,
            "live_win_rate": float(s.live_win_rate) if s.live_win_rate else 0.0,
            "live_first_trade_at": s.live_first_trade_at.isoformat() if s.live_first_trade_at else None,
            "live_last_trade_at": s.live_last_trade_at.isoformat() if s.live_last_trade_at else None
        })

    return {
        "creator_username": user.username,
        "creator_id": user.id,
        "is_verified": creator_profile.is_verified,
        **aggregate,
        "strategies": strategy_summaries
    }