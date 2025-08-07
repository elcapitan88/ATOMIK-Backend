# app/services/marketplace_service.py
from sqlalchemy.orm import Session
from typing import Optional, Dict, Any
import logging
from datetime import datetime, timedelta
from decimal import Decimal

from app.models.user import User
from app.models.webhook import Webhook
from app.models.strategy_pricing import StrategyPricing, PricingType, BillingInterval
from app.models.strategy_purchase import StrategyPurchase, PurchaseStatus, PurchaseType
from app.models.creator_profile import CreatorProfile
from app.models.creator_earnings import CreatorEarnings, PayoutStatus
from app.schemas.marketplace import StrategyPricingCreate, StrategyPricingUpdate
from app.services.stripe_connect_service import StripeConnectService

logger = logging.getLogger(__name__)


class MarketplaceService:
    """Service for handling marketplace operations."""
    
    def __init__(self):
        self.stripe_service = StripeConnectService()
    
    async def create_strategy_pricing(
        self,
        db: Session,
        webhook: Webhook,
        pricing_data: StrategyPricingCreate
    ) -> StrategyPricing:
        """
        Create pricing configuration for a strategy.
        """
        try:
            # Create pricing record
            pricing = StrategyPricing(
                webhook_id=webhook.id,
                pricing_type=pricing_data.pricing_type,
                billing_interval=pricing_data.billing_interval,
                base_amount=pricing_data.base_amount,
                yearly_amount=pricing_data.yearly_amount,
                setup_fee=pricing_data.setup_fee,
                trial_days=pricing_data.trial_days or 0,
                is_trial_enabled=pricing_data.is_trial_enabled or False,
                is_active=True
            )
            
            # If this is a subscription, we'll need to create Stripe prices
            if pricing_data.pricing_type in ["subscription", "initiation_plus_sub"]:
                # Get creator's Stripe account
                creator_profile = db.query(CreatorProfile).filter(
                    CreatorProfile.user_id == webhook.user_id
                ).first()
                
                if creator_profile and creator_profile.stripe_connect_account_id:
                    # Create Stripe product for this strategy
                    product_id = await self.stripe_service.create_product(
                        name=f"Strategy: {webhook.name}",
                        description=f"Access to {webhook.name} trading strategy",
                        connected_account=creator_profile.stripe_connect_account_id,
                        metadata={
                            "webhook_id": str(webhook.id),
                            "creator_id": str(creator_profile.id)
                        }
                    )
                    
                    # Create monthly price if base_amount is set
                    if pricing_data.base_amount:
                        monthly_price_id = await self.stripe_service.create_price(
                            amount=pricing_data.base_amount,
                            currency="usd",
                            interval="month",
                            product_id=product_id,
                            connected_account=creator_profile.stripe_connect_account_id
                        )
                        pricing.stripe_price_id = monthly_price_id
                    
                    # Create yearly price if yearly_amount is set
                    if pricing_data.yearly_amount:
                        yearly_price_id = await self.stripe_service.create_price(
                            amount=pricing_data.yearly_amount,
                            currency="usd",
                            interval="year",
                            product_id=product_id,
                            connected_account=creator_profile.stripe_connect_account_id
                        )
                        pricing.stripe_yearly_price_id = yearly_price_id
            
            db.add(pricing)
            db.commit()
            db.refresh(pricing)
            
            logger.info(f"Created pricing {pricing.id} for webhook {webhook.id}")
            return pricing
            
        except Exception as e:
            db.rollback()
            logger.error(f"Error creating strategy pricing: {str(e)}")
            raise
    
    async def update_strategy_pricing(
        self,
        db: Session,
        pricing: StrategyPricing,
        update_data: StrategyPricingUpdate
    ) -> StrategyPricing:
        """
        Update existing pricing configuration.
        """
        try:
            # Update fields if provided
            if update_data.pricing_type is not None:
                pricing.pricing_type = update_data.pricing_type
                
            if update_data.billing_interval is not None:
                pricing.billing_interval = update_data.billing_interval
                
            if update_data.base_amount is not None:
                pricing.base_amount = update_data.base_amount
                
            if update_data.yearly_amount is not None:
                pricing.yearly_amount = update_data.yearly_amount
                
            if update_data.setup_fee is not None:
                pricing.setup_fee = update_data.setup_fee
                
            if update_data.trial_days is not None:
                pricing.trial_days = update_data.trial_days
                
            if update_data.is_trial_enabled is not None:
                pricing.is_trial_enabled = update_data.is_trial_enabled
                
            if update_data.is_active is not None:
                pricing.is_active = update_data.is_active
            
            # Update timestamp
            pricing.updated_at = datetime.utcnow()
            
            db.commit()
            db.refresh(pricing)
            
            logger.info(f"Updated pricing {pricing.id}")
            return pricing
            
        except Exception as e:
            db.rollback()
            logger.error(f"Error updating strategy pricing: {str(e)}")
            raise
    
    async def process_strategy_purchase(
        self,
        db: Session,
        user: User,
        webhook: Webhook,
        pricing: StrategyPricing,
        payment_method_id: str,
        trial_requested: bool = False
    ) -> StrategyPurchase:
        """
        Process a one-time strategy purchase.
        """
        try:
            # Get creator profile
            creator_profile = db.query(CreatorProfile).filter(
                CreatorProfile.user_id == webhook.user_id
            ).first()
            
            if not creator_profile:
                raise Exception("Creator profile not found")
            
            # Calculate amounts
            amount = pricing.base_amount or Decimal('0')
            platform_fee = await self.stripe_service.calculate_platform_fee(
                creator_profile, amount
            )
            creator_payout = amount - platform_fee
            
            # Handle trial period
            trial_ends_at = None
            if trial_requested and pricing.is_trial_enabled and pricing.trial_days > 0:
                trial_ends_at = datetime.utcnow() + timedelta(days=pricing.trial_days)
            
            # Create purchase record
            purchase = StrategyPurchase(
                user_id=user.id,
                webhook_id=webhook.id,
                pricing_id=pricing.id,
                amount_paid=amount,
                platform_fee=platform_fee,
                creator_payout=creator_payout,
                purchase_type=PurchaseType.ONE_TIME,
                status=PurchaseStatus.PENDING,
                trial_ends_at=trial_ends_at
            )
            
            # Process payment with Stripe if not a trial
            if not trial_requested or not pricing.is_trial_enabled:
                if not creator_profile.stripe_connect_account_id:
                    raise Exception("Creator has not set up Stripe Connect")
                
                payment_intent = await self.stripe_service.create_payment_with_app_fee(
                    amount=amount,
                    currency="usd",
                    payment_method_id=payment_method_id,
                    connected_account_id=creator_profile.stripe_connect_account_id,
                    application_fee=platform_fee,
                    description=f"Purchase: {webhook.name}",
                    metadata={
                        "user_id": str(user.id),
                        "webhook_id": str(webhook.id),
                        "purchase_id": str(purchase.id)
                    }
                )
                
                purchase.stripe_payment_intent_id = payment_intent["id"]
                
                # Update status based on payment result
                if payment_intent["status"] == "succeeded":
                    purchase.status = PurchaseStatus.COMPLETED
            else:
                # Trial purchase - mark as completed without payment
                purchase.status = PurchaseStatus.COMPLETED
                purchase.amount_paid = Decimal('0')
                purchase.platform_fee = Decimal('0')
                purchase.creator_payout = Decimal('0')
            
            db.add(purchase)
            db.commit()
            db.refresh(purchase)
            
            # Create earnings record if payment was successful
            if purchase.status == PurchaseStatus.COMPLETED and purchase.creator_payout > 0:
                await self._create_earnings_record(db, creator_profile, purchase)
            
            logger.info(f"Processed strategy purchase {purchase.id}")
            return purchase
            
        except Exception as e:
            db.rollback()
            logger.error(f"Error processing strategy purchase: {str(e)}")
            raise
    
    async def process_strategy_subscription(
        self,
        db: Session,
        user: User,
        webhook: Webhook,
        pricing: StrategyPricing,
        payment_method_id: str,
        billing_interval: str,
        trial_requested: bool = False
    ) -> StrategyPurchase:
        """
        Process a strategy subscription.
        """
        try:
            # Get creator profile
            creator_profile = db.query(CreatorProfile).filter(
                CreatorProfile.user_id == webhook.user_id
            ).first()
            
            if not creator_profile:
                raise Exception("Creator profile not found")
            
            if not creator_profile.stripe_connect_account_id:
                raise Exception("Creator has not set up Stripe Connect")
            
            # Determine price based on billing interval
            if billing_interval == BillingInterval.YEARLY and pricing.yearly_amount:
                amount = pricing.yearly_amount
                stripe_price_id = pricing.stripe_yearly_price_id
            else:
                amount = pricing.base_amount or Decimal('0')
                stripe_price_id = pricing.stripe_price_id
            
            if not stripe_price_id:
                raise Exception("Stripe price not configured for this billing interval")
            
            # Calculate fees
            platform_fee_percentage = creator_profile.platform_fee * 100  # Convert to percentage
            platform_fee = await self.stripe_service.calculate_platform_fee(
                creator_profile, amount
            )
            creator_payout = amount - platform_fee
            
            # Handle trial period
            trial_days = None
            trial_ends_at = None
            if trial_requested and pricing.is_trial_enabled and pricing.trial_days > 0:
                trial_days = pricing.trial_days
                trial_ends_at = datetime.utcnow() + timedelta(days=pricing.trial_days)
            
            # Create purchase record
            purchase = StrategyPurchase(
                user_id=user.id,
                webhook_id=webhook.id,
                pricing_id=pricing.id,
                amount_paid=amount,
                platform_fee=platform_fee,
                creator_payout=creator_payout,
                purchase_type=PurchaseType.SUBSCRIPTION,
                status=PurchaseStatus.PENDING,
                trial_ends_at=trial_ends_at
            )
            
            # Create Stripe subscription
            subscription = await self.stripe_service.create_subscription_with_fee(
                customer_id=user.stripe_customer_id,  # Assumes user has Stripe customer ID
                price_id=stripe_price_id,
                connected_account_id=creator_profile.stripe_connect_account_id,
                application_fee_percent=platform_fee_percentage,
                trial_period_days=trial_days,
                metadata={
                    "user_id": str(user.id),
                    "webhook_id": str(webhook.id),
                    "purchase_id": str(purchase.id)
                }
            )
            
            purchase.stripe_subscription_id = subscription["id"]
            purchase.status = PurchaseStatus.COMPLETED
            
            db.add(purchase)
            db.commit()
            db.refresh(purchase)
            
            # Create earnings record if not in trial
            if not trial_requested and purchase.creator_payout > 0:
                await self._create_earnings_record(db, creator_profile, purchase)
            
            logger.info(f"Processed strategy subscription {purchase.id}")
            return purchase
            
        except Exception as e:
            db.rollback()
            logger.error(f"Error processing strategy subscription: {str(e)}")
            raise
    
    async def _create_earnings_record(
        self,
        db: Session,
        creator_profile: CreatorProfile,
        purchase: StrategyPurchase
    ) -> CreatorEarnings:
        """
        Create an earnings record for a creator.
        """
        try:
            earnings = CreatorEarnings(
                creator_id=creator_profile.id,
                purchase_id=purchase.id,
                gross_amount=purchase.amount_paid,
                platform_fee=purchase.platform_fee,
                net_amount=purchase.creator_payout,
                payout_status=PayoutStatus.PENDING
            )
            
            db.add(earnings)
            db.commit()
            db.refresh(earnings)
            
            logger.info(f"Created earnings record {earnings.id}")
            return earnings
            
        except Exception as e:
            db.rollback()
            logger.error(f"Error creating earnings record: {str(e)}")
            raise