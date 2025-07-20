# app/services/creator_service.py
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Dict, Any, Optional
import logging
from datetime import datetime, timedelta
from decimal import Decimal

from app.models.user import User
from app.models.creator_profile import CreatorProfile
from app.models.creator_earnings import CreatorEarnings
from app.models.strategy_purchase import StrategyPurchase
from app.models.webhook import Webhook
from app.schemas.creator import CreatorProfileCreate, CreatorProfileUpdate, CreatorAnalyticsResponse

logger = logging.getLogger(__name__)


class CreatorService:
    """Service for handling creator operations."""
    
    async def create_creator_profile(
        self,
        db: Session,
        user_id: int,
        creator_data: CreatorProfileCreate
    ) -> CreatorProfile:
        """
        Create a new creator profile.
        """
        try:
            # Get user to use username as display name
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                raise Exception("User not found")
            
            # Create creator profile
            creator_profile = CreatorProfile(
                user_id=user_id,
                display_name=user.username,  # Use atomik username as display name
                bio=creator_data.bio,
                trading_experience=creator_data.trading_experience,
                total_subscribers=0,
                current_tier="bronze",  # Start with bronze tier
                is_verified=False,
                two_fa_enabled=creator_data.two_fa_enabled or False
            )
            
            db.add(creator_profile)
            db.commit()
            db.refresh(creator_profile)
            
            # Update user's creator_profile_id
            user.creator_profile_id = creator_profile.id
            db.commit()
            
            logger.info(f"Created creator profile {creator_profile.id} for user {user_id}")
            return creator_profile
            
        except Exception as e:
            db.rollback()
            logger.error(f"Error creating creator profile: {str(e)}")
            raise
    
    async def update_creator_profile(
        self,
        db: Session,
        creator_profile: CreatorProfile,
        update_data: CreatorProfileUpdate
    ) -> CreatorProfile:
        """
        Update an existing creator profile.
        """
        try:
            # Update fields if provided
            if update_data.display_name is not None:
                creator_profile.display_name = update_data.display_name
                
            if update_data.bio is not None:
                creator_profile.bio = update_data.bio
                
            if update_data.trading_experience is not None:
                creator_profile.trading_experience = update_data.trading_experience
                
            if update_data.two_fa_enabled is not None:
                creator_profile.two_fa_enabled = update_data.two_fa_enabled
            
            # Update timestamp
            creator_profile.updated_at = datetime.utcnow()
            
            db.commit()
            db.refresh(creator_profile)
            
            logger.info(f"Updated creator profile {creator_profile.id}")
            return creator_profile
            
        except Exception as e:
            db.rollback()
            logger.error(f"Error updating creator profile: {str(e)}")
            raise
    
    async def get_creator_analytics(
        self,
        db: Session,
        creator_profile: CreatorProfile,
        period: str = "30d"
    ) -> CreatorAnalyticsResponse:
        """
        Get analytics data for a creator.
        """
        try:
            # Parse period
            days = self._parse_period(period)
            start_date = datetime.utcnow() - timedelta(days=days)
            
            # Get creator's webhooks
            webhooks = db.query(Webhook).filter(
                Webhook.user_id == creator_profile.user_id
            ).all()
            webhook_ids = [w.id for w in webhooks]
            
            if not webhook_ids:
                return CreatorAnalyticsResponse(
                    total_revenue=Decimal('0'),
                    total_subscribers=0,
                    active_strategies=0,
                    conversion_rate=0.0,
                    revenue_growth=0.0,
                    subscriber_growth=0.0,
                    top_performing_strategies=[],
                    recent_earnings=[]
                )
            
            # Total revenue in period
            total_revenue = db.query(func.sum(CreatorEarnings.net_amount)).filter(
                CreatorEarnings.creator_id == creator_profile.id,
                CreatorEarnings.created_at >= start_date
            ).scalar() or Decimal('0')
            
            # Total subscribers (active purchases)
            total_subscribers = db.query(func.count(StrategyPurchase.id)).filter(
                StrategyPurchase.webhook_id.in_(webhook_ids),
                StrategyPurchase.status.in_(["pending", "completed"])
            ).scalar() or 0
            
            # Active strategies (monetized webhooks)
            active_strategies = db.query(func.count(Webhook.id)).filter(
                Webhook.user_id == creator_profile.user_id,
                Webhook.is_monetized == True
            ).scalar() or 0
            
            # Calculate conversion rate (subscribers / total webhook views)
            # For now, we'll use a placeholder calculation
            conversion_rate = 0.0
            if total_subscribers > 0:
                # This would need actual view tracking
                conversion_rate = min(total_subscribers / 100.0, 1.0) * 100
            
            # Revenue growth (compare to previous period)
            previous_start = start_date - timedelta(days=days)
            previous_revenue = db.query(func.sum(CreatorEarnings.net_amount)).filter(
                CreatorEarnings.creator_id == creator_profile.id,
                CreatorEarnings.created_at >= previous_start,
                CreatorEarnings.created_at < start_date
            ).scalar() or Decimal('0')
            
            revenue_growth = 0.0
            if previous_revenue > 0:
                revenue_growth = float((total_revenue - previous_revenue) / previous_revenue * 100)
            
            # Subscriber growth
            previous_subscribers = db.query(func.count(StrategyPurchase.id)).filter(
                StrategyPurchase.webhook_id.in_(webhook_ids),
                StrategyPurchase.status.in_(["pending", "completed"]),
                StrategyPurchase.created_at < start_date
            ).scalar() or 0
            
            subscriber_growth = 0.0
            if previous_subscribers > 0:
                subscriber_growth = ((total_subscribers - previous_subscribers) / previous_subscribers) * 100
            
            # Top performing strategies
            top_strategies = db.query(
                Webhook.name,
                func.count(StrategyPurchase.id).label('subscriber_count'),
                func.sum(CreatorEarnings.net_amount).label('revenue')
            ).join(
                StrategyPurchase, Webhook.id == StrategyPurchase.webhook_id
            ).join(
                CreatorEarnings, StrategyPurchase.id == CreatorEarnings.purchase_id
            ).filter(
                Webhook.user_id == creator_profile.user_id,
                CreatorEarnings.created_at >= start_date
            ).group_by(
                Webhook.id, Webhook.name
            ).order_by(
                func.sum(CreatorEarnings.net_amount).desc()
            ).limit(5).all()
            
            top_performing_strategies = [
                {
                    "strategy_name": strategy.name,
                    "subscriber_count": strategy.subscriber_count,
                    "revenue": float(strategy.revenue or 0)
                }
                for strategy in top_strategies
            ]
            
            # Recent earnings
            recent_earnings = db.query(CreatorEarnings).filter(
                CreatorEarnings.creator_id == creator_profile.id,
                CreatorEarnings.created_at >= start_date
            ).order_by(
                CreatorEarnings.created_at.desc()
            ).limit(10).all()
            
            return CreatorAnalyticsResponse(
                total_revenue=total_revenue,
                total_subscribers=total_subscribers,
                active_strategies=active_strategies,
                conversion_rate=conversion_rate,
                revenue_growth=revenue_growth,
                subscriber_growth=subscriber_growth,
                top_performing_strategies=top_performing_strategies,
                recent_earnings=[
                    {
                        "amount": float(earning.net_amount),
                        "date": earning.created_at,
                        "status": earning.payout_status
                    }
                    for earning in recent_earnings
                ]
            )
            
        except Exception as e:
            logger.error(f"Error getting creator analytics: {str(e)}")
            raise
    
    async def get_tier_progress(self, creator_profile: CreatorProfile) -> Dict[str, Any]:
        """
        Get creator's current tier and progress to next tier.
        """
        try:
            current_subscribers = creator_profile.total_subscribers
            current_tier = creator_profile.current_tier
            
            # Define tier thresholds
            tier_thresholds = {
                "bronze": {"min": 0, "max": 99, "next": "silver", "fee": 0.20},
                "silver": {"min": 100, "max": 199, "next": "gold", "fee": 0.15},
                "gold": {"min": 200, "max": float('inf'), "next": None, "fee": 0.10}
            }
            
            tier_info = tier_thresholds.get(current_tier, tier_thresholds["bronze"])
            
            # Calculate progress to next tier
            progress_percentage = 0.0
            subscribers_to_next = 0
            
            if tier_info["next"]:
                next_tier_threshold = tier_thresholds[tier_info["next"]]["min"]
                subscribers_to_next = max(0, next_tier_threshold - current_subscribers)
                
                if tier_info["max"] != float('inf'):
                    tier_range = tier_info["max"] - tier_info["min"] + 1
                    progress_in_tier = current_subscribers - tier_info["min"]
                    progress_percentage = (progress_in_tier / tier_range) * 100
                else:
                    progress_percentage = 100.0
            else:
                progress_percentage = 100.0  # Already at highest tier
            
            return {
                "current_tier": current_tier,
                "current_subscribers": current_subscribers,
                "current_fee_percentage": tier_info["fee"] * 100,
                "next_tier": tier_info["next"],
                "subscribers_to_next_tier": subscribers_to_next,
                "progress_percentage": min(progress_percentage, 100.0),
                "tier_benefits": self._get_tier_benefits(current_tier),
                "next_tier_benefits": self._get_tier_benefits(tier_info["next"]) if tier_info["next"] else None
            }
            
        except Exception as e:
            logger.error(f"Error getting tier progress: {str(e)}")
            raise
    
    async def update_creator_tier(self, db: Session, creator_profile: CreatorProfile) -> str:
        """
        Update creator tier based on subscriber count.
        """
        try:
            current_subscribers = creator_profile.total_subscribers
            
            # Determine new tier
            if current_subscribers >= 200:
                new_tier = "gold"
            elif current_subscribers >= 100:
                new_tier = "silver"
            else:
                new_tier = "bronze"
            
            # Update if tier changed
            if creator_profile.current_tier != new_tier:
                old_tier = creator_profile.current_tier
                creator_profile.current_tier = new_tier
                creator_profile.updated_at = datetime.utcnow()
                db.commit()
                
                logger.info(f"Updated creator {creator_profile.id} tier from {old_tier} to {new_tier}")
                return new_tier
            
            return creator_profile.current_tier
            
        except Exception as e:
            db.rollback()
            logger.error(f"Error updating creator tier: {str(e)}")
            raise
    
    def _parse_period(self, period: str) -> int:
        """Parse period string to number of days."""
        period_map = {
            "7d": 7,
            "30d": 30,
            "90d": 90,
            "1y": 365
        }
        return period_map.get(period, 30)
    
    def _get_tier_benefits(self, tier: Optional[str]) -> Optional[Dict[str, Any]]:
        """Get benefits for a specific tier."""
        if not tier:
            return None
            
        benefits = {
            "bronze": {
                "platform_fee": "20%",
                "features": ["Basic creator dashboard", "Standard payout schedule"],
                "color": "#CD7F32"
            },
            "silver": {
                "platform_fee": "15%",
                "features": ["Enhanced analytics", "Priority support", "Faster payouts"],
                "color": "#C0C0C0"
            },
            "gold": {
                "platform_fee": "10%",
                "features": ["Advanced analytics", "Premium support", "Instant payouts", "Featured listings"],
                "color": "#FFD700"
            }
        }
        
        return benefits.get(tier)