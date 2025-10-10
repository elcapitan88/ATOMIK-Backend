"""Creator profile endpoints for social features."""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, and_, desc

from app.api.deps import get_db, get_current_user, get_current_user_optional
from app.models.user import User
from app.models.creator_profile import CreatorProfile
from app.models.creator_follower import CreatorFollower
from app.models.strategy_monetization import StrategyMonetization
from app.models.webhook import Webhook
from app.schemas.creator_profile import (
    CreatorProfilePublic,
    CreatorFollowResponse,
    CreatorStrategyList
)

router = APIRouter()


@router.get("/profile/{username}", response_model=CreatorProfilePublic)
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

    # Count active strategies
    strategy_count = db.query(func.count(StrategyMonetization.id)).filter(
        and_(
            StrategyMonetization.creator_user_id == user.id,
            StrategyMonetization.is_active == True
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

    return CreatorProfilePublic(
        user_id=user.id,
        username=user.username,
        profile_picture=user.profile_picture,
        bio=creator_profile.bio,
        trading_experience=creator_profile.trading_experience,
        follower_count=creator_profile.follower_count,
        total_subscribers=creator_profile.total_subscribers,
        strategy_count=strategy_count,
        created_at=user.created_at,
        is_following=is_following,
        is_verified=creator_profile.is_verified,
        current_tier=creator_profile.current_tier,
        social_media=social_media
    )


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

        strategy_list.append({
            "id": str(monetization.id) if monetization else f"webhook_{webhook.id}",
            "webhook_id": webhook.id,
            "name": webhook.name,
            "description": webhook.details,
            "stripe_product_id": monetization.stripe_product_id if monetization else None,
            "total_subscribers": webhook.subscriber_count or 0,
            "estimated_monthly_revenue": estimated_revenue,
            "min_price": min_price,
            "created_at": webhook.sharing_enabled_at or webhook.created_at,
            "is_monetized": monetization is not None,
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