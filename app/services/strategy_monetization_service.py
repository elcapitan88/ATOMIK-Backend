# fastapi_backend/app/services/strategy_monetization_service.py
import logging
from typing import List, Dict, Optional, Any
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from ..models.webhook import Webhook
from ..models.user import User
from ..schemas.strategy_monetization import (
    StrategyMonetizationCreate,
    PricingOptionCreate,
    StrategyMonetizationResponse
)
from .stripe_connect_service import StripeConnectService
from ..core.config import settings

logger = logging.getLogger(__name__)

class StrategyMonetizationService:
    """
    Service for handling strategy monetization setup with dynamic Stripe integration.
    This replaces the manual Stripe dashboard work by automatically creating products and prices.
    """
    
    def __init__(self, db: Session):
        self.db = db
        self.stripe_service = StripeConnectService()
    
    async def setup_strategy_monetization(
        self,
        webhook_id: int,
        creator_user_id: int,
        pricing_options: List[PricingOptionCreate]
    ) -> StrategyMonetizationResponse:
        """
        Set up monetization for a strategy by automatically creating Stripe products and prices.
        
        This method:
        1. Creates a Stripe Product for the strategy
        2. Creates multiple Stripe Prices based on pricing options
        3. Stores all Stripe IDs in the database
        4. Enables the strategy for purchase
        
        Args:
            webhook_id: The webhook/strategy ID to monetize
            creator_user_id: The creator's user ID  
            pricing_options: List of pricing options to create
            
        Returns:
            StrategyMonetizationResponse with created monetization data
        """
        try:
            # Get the webhook/strategy
            webhook = self.db.query(Webhook).filter(
                Webhook.id == webhook_id,
                Webhook.user_id == creator_user_id
            ).first()
            
            if not webhook:
                raise ValueError("Strategy not found or access denied")
            
            # Get creator user for Stripe Connect account
            creator = self.db.query(User).filter(User.id == creator_user_id).first()
            if not creator or not creator.creator_profile or not creator.creator_profile.stripe_connect_account_id:
                raise ValueError("Creator profile or Stripe Connect account not found")
            
            stripe_account_id = creator.creator_profile.stripe_connect_account_id
            
            # Check if monetization already exists
            from ..models.strategy_monetization import StrategyMonetization
            existing_monetization = self.db.query(StrategyMonetization).filter(
                StrategyMonetization.webhook_id == webhook_id
            ).first()
            
            if existing_monetization:
                # Update existing monetization
                return await self._update_existing_monetization(
                    existing_monetization, 
                    stripe_account_id, 
                    pricing_options
                )
            
            # Create new Stripe Product automatically
            stripe_product = await self.stripe_service.create_strategy_product(
                strategy_name=webhook.name,
                strategy_description=webhook.details or f"Trading strategy: {webhook.name}",
                stripe_account_id=stripe_account_id
            )
            
            logger.info(f"Created Stripe product {stripe_product['id']} for strategy {webhook.name}")
            
            # Create StrategyMonetization record
            strategy_monetization = StrategyMonetization(
                webhook_id=webhook_id,
                stripe_product_id=stripe_product['id'],
                creator_user_id=creator_user_id,
                is_active=True,
                total_subscribers=0,
                estimated_monthly_revenue=0.00,
                created_at=datetime.utcnow()
            )
            
            self.db.add(strategy_monetization)
            self.db.flush()  # Get the ID
            
            # Create Stripe Prices for each pricing option
            created_prices = []
            for pricing_option in pricing_options:
                try:
                    stripe_price = await self.stripe_service.create_strategy_price(
                        product_id=stripe_product['id'],
                        amount=pricing_option.amount,
                        currency='usd',
                        billing_interval=pricing_option.billing_interval,
                        trial_period_days=pricing_option.trial_period_days,
                        stripe_account_id=stripe_account_id
                    )
                    
                    # Create StrategyPrice record
                    from ..models.strategy_monetization import StrategyPrice
                    strategy_price = StrategyPrice(
                        strategy_monetization_id=strategy_monetization.id,
                        price_type=pricing_option.price_type,
                        stripe_price_id=stripe_price['id'],
                        amount=pricing_option.amount,
                        currency='usd',
                        billing_interval=pricing_option.billing_interval,
                        trial_period_days=pricing_option.trial_period_days or 0,
                        is_active=True,
                        created_at=datetime.utcnow()
                    )
                    
                    self.db.add(strategy_price)
                    created_prices.append(strategy_price)
                    
                    logger.info(f"Created Stripe price {stripe_price['id']} for {pricing_option.price_type}")
                    
                except Exception as price_error:
                    logger.error(f"Failed to create price for {pricing_option.price_type}: {str(price_error)}")
                    # Continue with other prices, but log the error
                    continue
            
            if not created_prices:
                # If no prices were created successfully, clean up
                await self.stripe_service.delete_product(stripe_product['id'], stripe_account_id)
                raise ValueError("Failed to create any pricing options")
            
            # Update webhook to mark as monetized and shared
            webhook.is_monetized = True
            webhook.usage_intent = 'monetize'
            webhook.is_shared = True  # Ensure monetized strategies are shared to marketplace
            if not webhook.sharing_enabled_at:
                webhook.sharing_enabled_at = datetime.utcnow()
            
            # Commit all changes
            self.db.commit()
            self.db.refresh(strategy_monetization)
            
            # Calculate estimated revenue
            estimated_monthly = self._calculate_estimated_monthly_revenue(created_prices)
            strategy_monetization.estimated_monthly_revenue = estimated_monthly
            self.db.commit()
            
            logger.info(f"Successfully set up monetization for strategy {webhook.name} with {len(created_prices)} pricing options")
            
            return StrategyMonetizationResponse(
                id=strategy_monetization.id,
                webhook_id=webhook_id,
                stripe_product_id=stripe_product['id'],
                creator_user_id=creator_user_id,
                is_active=True,
                total_subscribers=0,
                estimated_monthly_revenue=estimated_monthly,
                created_at=strategy_monetization.created_at,
                prices=[
                    {
                        'id': price.id,
                        'price_type': price.price_type,
                        'stripe_price_id': price.stripe_price_id,
                        'amount': price.amount,
                        'currency': price.currency,
                        'billing_interval': price.billing_interval,
                        'trial_period_days': price.trial_period_days,
                        'is_active': price.is_active
                    } for price in created_prices
                ]
            )
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to set up strategy monetization: {str(e)}")
            raise
    
    async def _update_existing_monetization(
        self,
        existing_monetization,
        stripe_account_id: str,
        pricing_options: List[PricingOptionCreate]
    ) -> StrategyMonetizationResponse:
        """Update existing monetization with new pricing options."""
        try:
            from ..models.strategy_monetization import StrategyPrice
            
            # Deactivate existing prices
            existing_prices = self.db.query(StrategyPrice).filter(
                StrategyPrice.strategy_monetization_id == existing_monetization.id
            ).all()
            
            for price in existing_prices:
                price.is_active = False
                # Also deactivate in Stripe
                try:
                    await self.stripe_service.deactivate_price(price.stripe_price_id, stripe_account_id)
                except Exception as e:
                    logger.warning(f"Failed to deactivate Stripe price {price.stripe_price_id}: {str(e)}")
            
            # Create new prices
            created_prices = []
            for pricing_option in pricing_options:
                try:
                    stripe_price = await self.stripe_service.create_strategy_price(
                        product_id=existing_monetization.stripe_product_id,
                        amount=pricing_option.amount,
                        currency='usd',
                        billing_interval=pricing_option.billing_interval,
                        trial_period_days=pricing_option.trial_period_days,
                        stripe_account_id=stripe_account_id
                    )
                    
                    strategy_price = StrategyPrice(
                        strategy_monetization_id=existing_monetization.id,
                        price_type=pricing_option.price_type,
                        stripe_price_id=stripe_price['id'],
                        amount=pricing_option.amount,
                        currency='usd',
                        billing_interval=pricing_option.billing_interval,
                        trial_period_days=pricing_option.trial_period_days or 0,
                        is_active=True,
                        created_at=datetime.utcnow()
                    )
                    
                    self.db.add(strategy_price)
                    created_prices.append(strategy_price)
                    
                except Exception as price_error:
                    logger.error(f"Failed to update price for {pricing_option.price_type}: {str(price_error)}")
                    continue
            
            if not created_prices:
                raise ValueError("Failed to create any updated pricing options")
            
            # Update estimated revenue
            estimated_monthly = self._calculate_estimated_monthly_revenue(created_prices)
            existing_monetization.estimated_monthly_revenue = estimated_monthly
            existing_monetization.is_active = True
            
            self.db.commit()
            
            return StrategyMonetizationResponse(
                id=existing_monetization.id,
                webhook_id=existing_monetization.webhook_id,
                stripe_product_id=existing_monetization.stripe_product_id,
                creator_user_id=existing_monetization.creator_user_id,
                is_active=existing_monetization.is_active,
                total_subscribers=existing_monetization.total_subscribers,
                estimated_monthly_revenue=estimated_monthly,
                created_at=existing_monetization.created_at,
                prices=[
                    {
                        'id': price.id,
                        'price_type': price.price_type,
                        'stripe_price_id': price.stripe_price_id,
                        'amount': price.amount,
                        'currency': price.currency,
                        'billing_interval': price.billing_interval,
                        'trial_period_days': price.trial_period_days,
                        'is_active': price.is_active
                    } for price in created_prices
                ]
            )
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to update strategy monetization: {str(e)}")
            raise
    
    def _calculate_estimated_monthly_revenue(self, prices) -> float:
        """Calculate conservative estimated monthly revenue based on pricing options."""
        monthly_revenue = 0.0
        
        for price in prices:
            if price.price_type == 'monthly':
                # Assume 10 monthly subscribers initially
                monthly_revenue += float(price.amount) * 10
            elif price.price_type == 'yearly':
                # Assume 5 yearly subscribers, divide by 12 for monthly
                monthly_revenue += (float(price.amount) * 5) / 12
            elif price.price_type == 'lifetime':
                # Assume 2 lifetime purchases per month
                monthly_revenue += (float(price.amount) * 2)
            elif price.price_type == 'setup':
                # Assume 5 setup fees per month
                monthly_revenue += float(price.amount) * 5
        
        return monthly_revenue
    
    async def get_strategy_monetization(
        self,
        webhook_id: int,
        creator_user_id: int
    ) -> Optional[StrategyMonetizationResponse]:
        """Get existing monetization data for a strategy."""
        try:
            from ..models.strategy_monetization import StrategyMonetization, StrategyPrice
            
            monetization = self.db.query(StrategyMonetization).filter(
                StrategyMonetization.webhook_id == webhook_id,
                StrategyMonetization.creator_user_id == creator_user_id
            ).first()
            
            if not monetization:
                return None
            
            # Get active prices
            prices = self.db.query(StrategyPrice).filter(
                StrategyPrice.strategy_monetization_id == monetization.id,
                StrategyPrice.is_active == True
            ).all()
            
            return StrategyMonetizationResponse(
                id=monetization.id,
                webhook_id=monetization.webhook_id,
                stripe_product_id=monetization.stripe_product_id,
                creator_user_id=monetization.creator_user_id,
                is_active=monetization.is_active,
                total_subscribers=monetization.total_subscribers,
                estimated_monthly_revenue=monetization.estimated_monthly_revenue,
                created_at=monetization.created_at,
                prices=[
                    {
                        'id': price.id,
                        'price_type': price.price_type,
                        'stripe_price_id': price.stripe_price_id,
                        'amount': price.amount,
                        'currency': price.currency,
                        'billing_interval': price.billing_interval,
                        'trial_period_days': price.trial_period_days,
                        'is_active': price.is_active
                    } for price in prices
                ]
            )
            
        except Exception as e:
            logger.error(f"Failed to get strategy monetization: {str(e)}")
            return None
    
    async def get_strategy_pricing_options(self, webhook_token: str) -> List[Dict[str, Any]]:
        """
        Get pricing options for a strategy by webhook token.
        This replaces environment variable lookups with database queries.
        """
        try:
            # Get webhook by token
            webhook = self.db.query(Webhook).filter(
                Webhook.token == webhook_token,
                Webhook.is_shared == True  # Only for shared/monetized strategies
            ).first()
            
            if not webhook:
                return []
            
            # Get monetization data
            from ..models.strategy_monetization import StrategyMonetization, StrategyPrice
            
            monetization = self.db.query(StrategyMonetization).filter(
                StrategyMonetization.webhook_id == webhook.id,
                StrategyMonetization.is_active == True
            ).first()
            
            if not monetization:
                return []
            
            # Get active prices
            prices = self.db.query(StrategyPrice).filter(
                StrategyPrice.strategy_monetization_id == monetization.id,
                StrategyPrice.is_active == True
            ).all()
            
            return [
                {
                    'price_type': price.price_type,
                    'stripe_price_id': price.stripe_price_id,
                    'amount': float(price.amount),
                    'currency': price.currency,
                    'billing_interval': price.billing_interval,
                    'trial_period_days': price.trial_period_days,
                    'display_name': self._get_price_display_name(price.price_type),
                    'description': self._get_price_description(price.price_type, price.amount, price.billing_interval)
                } for price in prices
            ]
            
        except Exception as e:
            logger.error(f"Failed to get strategy pricing options: {str(e)}")
            return []
    
    def _get_price_display_name(self, price_type: str) -> str:
        """Get human-readable display name for price type."""
        display_names = {
            'monthly': 'Monthly Subscription',
            'yearly': 'Annual Subscription', 
            'lifetime': 'Lifetime Access',
            'setup': 'Setup Fee'
        }
        return display_names.get(price_type, price_type.title())
    
    def _get_price_description(self, price_type: str, amount: float, billing_interval: Optional[str]) -> str:
        """Get description for price option."""
        if price_type == 'monthly':
            return f'${amount}/month - Recurring monthly access'
        elif price_type == 'yearly':
            return f'${amount}/year - Save with annual billing'
        elif price_type == 'lifetime':
            return f'${amount} - One-time payment for permanent access'
        elif price_type == 'setup':
            return f'${amount} - One-time setup fee'
        else:
            return f'${amount}'