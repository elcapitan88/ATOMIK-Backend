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
# TODO: Uncomment after strategy_metrics table migration is fixed
# from app.models.strategy_metrics import StrategyMetrics, CreatorDashboardCache
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

        # Get creator's Stripe account
        creator_profile = self.db.query(CreatorProfile).filter(
            CreatorProfile.user_id == creator_id
        ).first()

        if not creator_profile or not creator_profile.stripe_connect_account_id:
            return self._empty_dashboard()

        # Fetch data from Stripe
        revenue_data = await self._get_revenue_data(creator_profile.stripe_connect_account_id, period)
        subscriber_data = await self._get_subscriber_data(creator_profile.stripe_connect_account_id)
        payout_data = await self._get_payout_data(creator_profile.stripe_connect_account_id, period)

        dashboard_data = {
            "revenue": revenue_data,
            "subscribers": subscriber_data,
            "payouts": payout_data,
            "period": period,
            "generated_at": datetime.utcnow().isoformat()
        }

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
    
    
    def _empty_dashboard(self) -> Dict[str, Any]:
        """Return empty dashboard structure"""
        return {
            "revenue": self._empty_revenue_data(),
            "subscribers": self._empty_subscriber_data(),
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
    
    def _empty_payout_data(self) -> Dict[str, Any]:
        return {
            "total_paid": 0,
            "pending_payouts": 0,
            "recent_payouts": [],
            "payout_schedule": "automatic",
            "currency": "usd"
        }