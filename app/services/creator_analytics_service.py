# app/services/creator_analytics_service.py
import stripe
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta, date
from sqlalchemy.orm import Session
from sqlalchemy import func
import json
import logging

from app.models.user import User
from app.models.webhook import Webhook
from app.models.strategy_metrics import StrategyMetrics, CreatorDashboardCache
from app.models.creator_profile import CreatorProfile
from app.services.stripe_connect_service import StripeConnectService
from app.core.config import settings

logger = logging.getLogger(__name__)


class CreatorAnalyticsService:
    """Service for creator analytics using Stripe APIs + local metrics"""
    
    def __init__(self, db: Session):
        self.db = db
        self.stripe_service = StripeConnectService()
        stripe.api_key = settings.STRIPE_SECRET_KEY
    
    async def get_creator_dashboard(
        self, 
        creator_id: int, 
        period: str = "30d"
    ) -> Dict[str, Any]:
        """Get comprehensive creator dashboard data"""
        
        # Check cache first
        cache_key = f"dashboard_{period}"
        cached_data = await self._get_cached_data(creator_id, cache_key)
        if cached_data:
            return cached_data
        
        # Get creator's Stripe account
        creator_profile = self.db.query(CreatorProfile).filter(
            CreatorProfile.user_id == creator_id
        ).first()
        
        if not creator_profile or not creator_profile.stripe_connect_id:
            return self._empty_dashboard()
        
        # Fetch data in parallel
        revenue_data = await self._get_revenue_data(creator_profile.stripe_connect_id, period)
        subscriber_data = await self._get_subscriber_data(creator_profile.stripe_connect_id)
        strategy_metrics = await self._get_strategy_metrics(creator_id, period)
        payout_data = await self._get_payout_data(creator_profile.stripe_connect_id, period)
        
        dashboard_data = {
            "revenue": revenue_data,
            "subscribers": subscriber_data,
            "metrics": strategy_metrics,
            "payouts": payout_data,
            "period": period,
            "generated_at": datetime.utcnow().isoformat()
        }
        
        # Cache for 1 hour
        await self._cache_data(creator_id, cache_key, dashboard_data, hours=1)
        
        return dashboard_data
    
    async def _get_revenue_data(
        self, 
        stripe_account_id: str, 
        period: str
    ) -> Dict[str, Any]:
        """Get revenue data from Stripe"""
        try:
            # Calculate date range
            end_date = datetime.utcnow()
            if period == "7d":
                start_date = end_date - timedelta(days=7)
            elif period == "30d":
                start_date = end_date - timedelta(days=30)
            elif period == "90d":
                start_date = end_date - timedelta(days=90)
            else:  # yearly
                start_date = end_date - timedelta(days=365)
            
            # Get successful charges from Stripe
            charges = stripe.Charge.list(
                created={
                    "gte": int(start_date.timestamp()),
                    "lte": int(end_date.timestamp())
                },
                status="succeeded",
                limit=100,
                stripe_account=stripe_account_id
            )
            
            # Calculate revenue breakdown
            total_revenue = 0
            monthly_revenue = 0
            yearly_revenue = 0
            lifetime_revenue = 0
            setup_revenue = 0
            
            for charge in charges.data:
                amount = charge.amount / 100  # Convert from cents
                total_revenue += amount
                
                # Get metadata to categorize revenue
                metadata = charge.metadata or {}
                pricing_type = metadata.get("pricing_type", "")
                
                if pricing_type == "monthly":
                    monthly_revenue += amount
                elif pricing_type == "yearly":
                    yearly_revenue += amount
                elif pricing_type == "lifetime":
                    lifetime_revenue += amount
                elif pricing_type == "setup":
                    setup_revenue += amount
            
            # Calculate platform fee (15%)
            platform_fee = total_revenue * 0.15
            net_revenue = total_revenue - platform_fee
            
            # Get balance for available funds
            balance = stripe.Balance.retrieve(stripe_account=stripe_account_id)
            available_balance = sum(b.amount for b in balance.available) / 100
            pending_balance = sum(b.amount for b in balance.pending) / 100
            
            return {
                "total_revenue": round(total_revenue, 2),
                "net_revenue": round(net_revenue, 2),
                "platform_fee": round(platform_fee, 2),
                "available_balance": round(available_balance, 2),
                "pending_balance": round(pending_balance, 2),
                "breakdown": {
                    "monthly": round(monthly_revenue, 2),
                    "yearly": round(yearly_revenue, 2),
                    "lifetime": round(lifetime_revenue, 2),
                    "setup_fee": round(setup_revenue, 2)
                },
                "currency": "usd"
            }
            
        except Exception as e:
            logger.error(f"Error fetching revenue data: {str(e)}")
            return self._empty_revenue_data()
    
    async def _get_subscriber_data(
        self, 
        stripe_account_id: str
    ) -> Dict[str, Any]:
        """Get subscriber data from Stripe"""
        try:
            # Get active subscriptions
            active_subs = stripe.Subscription.list(
                status="active",
                limit=100,
                stripe_account=stripe_account_id
            )
            
            # Get trialing subscriptions
            trial_subs = stripe.Subscription.list(
                status="trialing",
                limit=100,
                stripe_account=stripe_account_id
            )
            
            # Count by type
            monthly_count = 0
            yearly_count = 0
            lifetime_count = 0
            
            for sub in active_subs.data:
                if sub.items.data[0].price.recurring:
                    interval = sub.items.data[0].price.recurring.interval
                    if interval == "month":
                        monthly_count += 1
                    elif interval == "year":
                        yearly_count += 1
                else:
                    lifetime_count += 1
            
            # Calculate MRR (Monthly Recurring Revenue)
            mrr = 0
            for sub in active_subs.data:
                if sub.items.data[0].price.recurring:
                    price = sub.items.data[0].price.unit_amount / 100
                    interval = sub.items.data[0].price.recurring.interval
                    if interval == "month":
                        mrr += price
                    elif interval == "year":
                        mrr += price / 12
            
            return {
                "total_active": active_subs.total_count,
                "total_trials": trial_subs.total_count,
                "breakdown": {
                    "monthly": monthly_count,
                    "yearly": yearly_count,
                    "lifetime": lifetime_count
                },
                "mrr": round(mrr, 2),
                "arr": round(mrr * 12, 2)  # Annual Recurring Revenue
            }
            
        except Exception as e:
            logger.error(f"Error fetching subscriber data: {str(e)}")
            return self._empty_subscriber_data()
    
    async def _get_strategy_metrics(
        self, 
        creator_id: int, 
        period: str
    ) -> Dict[str, Any]:
        """Get strategy performance metrics from local database"""
        # Get creator's strategies
        strategies = self.db.query(Webhook).filter(
            Webhook.user_id == creator_id
        ).all()
        
        if not strategies:
            return self._empty_metrics_data()
        
        # Calculate date range
        end_date = date.today()
        if period == "7d":
            start_date = end_date - timedelta(days=7)
        elif period == "30d":
            start_date = end_date - timedelta(days=30)
        elif period == "90d":
            start_date = end_date - timedelta(days=90)
        else:  # yearly
            start_date = end_date - timedelta(days=365)
        
        # Aggregate metrics
        total_views = 0
        total_unique_viewers = 0
        total_trial_starts = 0
        strategy_performance = []
        
        for strategy in strategies:
            metrics = self.db.query(
                func.sum(StrategyMetrics.views).label('total_views'),
                func.sum(StrategyMetrics.unique_viewers).label('unique_viewers'),
                func.sum(StrategyMetrics.trial_starts).label('trial_starts'),
                func.avg(StrategyMetrics.avg_view_duration).label('avg_duration')
            ).filter(
                StrategyMetrics.strategy_id == strategy.id,
                StrategyMetrics.date >= start_date,
                StrategyMetrics.date <= end_date
            ).first()
            
            if metrics and metrics.total_views:
                total_views += metrics.total_views or 0
                total_unique_viewers += metrics.unique_viewers or 0
                total_trial_starts += metrics.trial_starts or 0
                
                conversion_rate = 0
                if metrics.unique_viewers > 0:
                    conversion_rate = (metrics.trial_starts / metrics.unique_viewers) * 100
                
                strategy_performance.append({
                    "strategy_id": str(strategy.id),
                    "strategy_name": strategy.name,
                    "views": metrics.total_views or 0,
                    "unique_viewers": metrics.unique_viewers or 0,
                    "trial_starts": metrics.trial_starts or 0,
                    "conversion_rate": round(conversion_rate, 2),
                    "avg_view_duration": round(metrics.avg_duration or 0, 1)
                })
        
        # Sort by views
        strategy_performance.sort(key=lambda x: x["views"], reverse=True)
        
        return {
            "total_views": total_views,
            "total_unique_viewers": total_unique_viewers,
            "total_trial_starts": total_trial_starts,
            "overall_conversion_rate": round(
                (total_trial_starts / total_unique_viewers * 100) if total_unique_viewers > 0 else 0, 
                2
            ),
            "top_strategies": strategy_performance[:5],  # Top 5 strategies
            "strategy_count": len(strategies)
        }
    
    async def _get_payout_data(
        self, 
        stripe_account_id: str, 
        period: str
    ) -> Dict[str, Any]:
        """Get payout data from Stripe"""
        try:
            # Get recent payouts
            payouts = stripe.Payout.list(
                limit=10,
                stripe_account=stripe_account_id
            )
            
            # Calculate totals
            total_paid = 0
            pending_payouts = 0
            
            recent_payouts = []
            for payout in payouts.data:
                amount = payout.amount / 100
                
                if payout.status == "paid":
                    total_paid += amount
                elif payout.status in ["pending", "in_transit"]:
                    pending_payouts += amount
                
                recent_payouts.append({
                    "id": payout.id,
                    "amount": round(amount, 2),
                    "status": payout.status,
                    "arrival_date": datetime.fromtimestamp(payout.arrival_date).isoformat(),
                    "created": datetime.fromtimestamp(payout.created).isoformat()
                })
            
            return {
                "total_paid": round(total_paid, 2),
                "pending_payouts": round(pending_payouts, 2),
                "recent_payouts": recent_payouts[:5],  # Last 5 payouts
                "payout_schedule": "automatic",  # Can be fetched from Stripe account
                "currency": "usd"
            }
            
        except Exception as e:
            logger.error(f"Error fetching payout data: {str(e)}")
            return self._empty_payout_data()
    
    async def _get_cached_data(
        self, 
        creator_id: int, 
        cache_key: str
    ) -> Optional[Dict[str, Any]]:
        """Get cached dashboard data"""
        cache_entry = self.db.query(CreatorDashboardCache).filter(
            CreatorDashboardCache.creator_id == creator_id,
            CreatorDashboardCache.cache_key == cache_key,
            CreatorDashboardCache.expires_at > datetime.utcnow()
        ).first()
        
        if cache_entry:
            return cache_entry.cache_value
        return None
    
    async def _cache_data(
        self, 
        creator_id: int, 
        cache_key: str, 
        data: Dict[str, Any], 
        hours: int = 1
    ):
        """Cache dashboard data"""
        expires_at = datetime.utcnow() + timedelta(hours=hours)
        
        # Check if cache entry exists
        cache_entry = self.db.query(CreatorDashboardCache).filter(
            CreatorDashboardCache.creator_id == creator_id,
            CreatorDashboardCache.cache_key == cache_key
        ).first()
        
        if cache_entry:
            cache_entry.cache_value = data
            cache_entry.expires_at = expires_at
            cache_entry.updated_at = datetime.utcnow()
        else:
            cache_entry = CreatorDashboardCache(
                creator_id=creator_id,
                cache_key=cache_key,
                cache_value=data,
                expires_at=expires_at
            )
            self.db.add(cache_entry)
        
        self.db.commit()
    
    async def track_strategy_view(
        self, 
        strategy_id: str, 
        viewer_id: Optional[int] = None,
        duration: Optional[float] = None
    ):
        """Track a strategy view"""
        today = date.today()
        
        # Get or create today's metrics
        metrics = self.db.query(StrategyMetrics).filter(
            StrategyMetrics.strategy_id == strategy_id,
            StrategyMetrics.date == today
        ).first()
        
        if not metrics:
            metrics = StrategyMetrics(
                strategy_id=strategy_id,
                date=today
            )
            self.db.add(metrics)
        
        # Update metrics
        metrics.views += 1
        if viewer_id:
            # In production, use Redis or similar to track unique viewers
            metrics.unique_viewers += 1
        
        if duration:
            # Update average duration
            total_duration = metrics.avg_view_duration * (metrics.views - 1)
            metrics.avg_view_duration = (total_duration + duration) / metrics.views
        
        self.db.commit()
    
    def _empty_dashboard(self) -> Dict[str, Any]:
        """Return empty dashboard structure"""
        return {
            "revenue": self._empty_revenue_data(),
            "subscribers": self._empty_subscriber_data(),
            "metrics": self._empty_metrics_data(),
            "payouts": self._empty_payout_data(),
            "period": "30d",
            "generated_at": datetime.utcnow().isoformat()
        }
    
    def _empty_revenue_data(self) -> Dict[str, Any]:
        return {
            "total_revenue": 0,
            "net_revenue": 0,
            "platform_fee": 0,
            "available_balance": 0,
            "pending_balance": 0,
            "breakdown": {
                "monthly": 0,
                "yearly": 0,
                "lifetime": 0,
                "setup_fee": 0
            },
            "currency": "usd"
        }
    
    def _empty_subscriber_data(self) -> Dict[str, Any]:
        return {
            "total_active": 0,
            "total_trials": 0,
            "breakdown": {
                "monthly": 0,
                "yearly": 0,
                "lifetime": 0
            },
            "mrr": 0,
            "arr": 0
        }
    
    def _empty_metrics_data(self) -> Dict[str, Any]:
        return {
            "total_views": 0,
            "total_unique_viewers": 0,
            "total_trial_starts": 0,
            "overall_conversion_rate": 0,
            "top_strategies": [],
            "strategy_count": 0
        }
    
    def _empty_payout_data(self) -> Dict[str, Any]:
        return {
            "total_paid": 0,
            "pending_payouts": 0,
            "recent_payouts": [],
            "payout_schedule": "automatic",
            "currency": "usd"
        }