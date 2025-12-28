# app/services/stripe_connect_service.py
import stripe
from typing import Dict, Any, Optional, List
import logging
from decimal import Decimal

from app.core.config import settings
from app.models.creator_profile import CreatorProfile
from app.models.strategy_pricing import StrategyPricing

logger = logging.getLogger(__name__)

# Set Stripe API key
stripe.api_key = settings.STRIPE_SECRET_KEY


class StripeConnectService:
    """Service for handling Stripe Connect operations."""
    
    def __init__(self):
        self.api_key = settings.STRIPE_SECRET_KEY
        
    async def create_express_account(self, creator_profile: CreatorProfile) -> str:
        """
        Create a Stripe Express account for a creator with embedded components support.
        """
        try:
            account = stripe.Account.create(
                country="US",  # Default to US, can be made configurable
                email=creator_profile.user.email if creator_profile.user else None,
                capabilities={
                    "card_payments": {"requested": True},
                    "transfers": {"requested": True},
                },
                business_type="individual",  # Default to individual
                # Controller settings for Express accounts with Stripe liability
                controller={
                    "requirement_collection": "stripe",  # Stripe handles KYC/identity verification
                    "losses": {
                        "payments": "stripe"  # Stripe assumes liability for negative balances
                    },
                    "fees": {
                        "payer": "application"  # Platform pays Stripe fees
                    },
                    "stripe_dashboard": {
                        "type": "express"  # Creators get limited Stripe dashboard for payouts
                    }
                },
                metadata={
                    "creator_id": str(creator_profile.id),
                    "user_id": str(creator_profile.user_id),
                    "display_name": creator_profile.display_name or "Creator"
                }
            )
            
            logger.info(f"Created Stripe Express account {account.id} for creator {creator_profile.id}")
            return account.id
            
        except stripe.StripeError as e:
            logger.error(f"Stripe error creating account: {str(e)}")
            raise Exception(f"Failed to create Stripe account: {str(e)}")
        except Exception as e:
            logger.error(f"Error creating Stripe account: {str(e)}")
            raise
    
    async def create_account_link(
        self, 
        account_id: str, 
        refresh_url: str, 
        return_url: str,
        creator_profile: Optional[CreatorProfile] = None
    ) -> Dict[str, Any]:
        """
        Create an account link for onboarding with prefilled user information.
        """
        try:
            # Build the account link data
            account_link_data = {
                "account": account_id,
                "refresh_url": refresh_url,
                "return_url": return_url,
                "type": "account_onboarding",
            }
            
            # Add prefill data if creator profile is provided
            if creator_profile and creator_profile.user:
                user = creator_profile.user
                account_link_data["collect"] = "eventually_due"
                
                # First, update the Stripe account with prefill data
                # This is more reliable than using account_link prefill
                account_update_data = {}
                
                # Email
                if user.email:
                    account_update_data["email"] = user.email
                
                # Individual information
                individual_data = {}
                if creator_profile.display_name:
                    name_parts = creator_profile.display_name.split(" ", 1)
                    individual_data["first_name"] = name_parts[0]
                    if len(name_parts) > 1:
                        individual_data["last_name"] = name_parts[1]
                elif user.full_name:
                    name_parts = user.full_name.split(" ", 1)
                    individual_data["first_name"] = name_parts[0]
                    if len(name_parts) > 1:
                        individual_data["last_name"] = name_parts[1]
                elif user.username:
                    individual_data["first_name"] = user.username
                
                # Phone number
                if user.phone:
                    individual_data["phone"] = user.phone
                
                # Add individual data if we have any
                if individual_data:
                    account_update_data["individual"] = individual_data
                
                # Business profile data
                business_profile_data = {}
                if user.website:
                    business_profile_data["url"] = user.website
                
                if business_profile_data:
                    account_update_data["business_profile"] = business_profile_data
                
                # Update the Stripe account with prefill data
                if account_update_data:
                    try:
                        stripe.Account.modify(account_id, **account_update_data)
                        logger.info(f"Updated Stripe account {account_id} with prefill data")
                    except stripe.StripeError as update_error:
                        logger.warning(f"Could not update account prefill data: {update_error}")
                        # Continue with account link creation even if prefill fails
            
            account_link = stripe.AccountLink.create(**account_link_data)
            
            logger.info(f"Created account link for account {account_id} with prefill data")
            return account_link
            
        except stripe.StripeError as e:
            logger.error(f"Stripe error creating account link: {str(e)}")
            raise Exception(f"Failed to create account link: {str(e)}")
        except Exception as e:
            logger.error(f"Error creating account link: {str(e)}")
            raise

    async def create_payment_with_app_fee(
        self,
        amount: Decimal,
        currency: str,
        payment_method_id: str,
        connected_account_id: str,
        application_fee: Decimal,
        description: str,
        metadata: Dict[str, str]
    ) -> Dict[str, Any]:
        """
        Create a payment intent with application fee for one-time purchases.
        """
        try:
            # Convert Decimal to cents (Stripe expects integer cents)
            amount_cents = int(amount * 100)
            fee_cents = int(application_fee * 100)
            
            payment_intent = stripe.PaymentIntent.create(
                amount=amount_cents,
                currency=currency.lower(),
                payment_method=payment_method_id,
                confirmation_method="manual",
                confirm=True,
                return_url=f"{settings.FRONTEND_URL}/marketplace/payment-success",
                application_fee_amount=fee_cents,
                transfer_data={
                    "destination": connected_account_id,
                },
                description=description,
                metadata=metadata
            )
            
            logger.info(f"Created payment intent {payment_intent.id} with fee {fee_cents} cents")
            return payment_intent
            
        except stripe.StripeError as e:
            logger.error(f"Stripe error creating payment: {str(e)}")
            raise Exception(f"Failed to create payment: {str(e)}")
        except Exception as e:
            logger.error(f"Error creating payment: {str(e)}")
            raise
    
    async def create_subscription_with_fee(
        self,
        customer_id: str,
        price_id: str,
        connected_account_id: str,
        application_fee_percent: float,
        trial_period_days: Optional[int] = None,
        metadata: Dict[str, str] = None
    ) -> Dict[str, Any]:
        """
        Create a subscription with application fee percentage.
        """
        try:
            subscription_data = {
                "customer": customer_id,
                "items": [{"price": price_id}],
                "application_fee_percent": application_fee_percent,
                "transfer_data": {
                    "destination": connected_account_id,
                },
                "metadata": metadata or {}
            }
            
            # Add trial period if specified
            if trial_period_days and trial_period_days > 0:
                subscription_data["trial_period_days"] = trial_period_days
            
            subscription = stripe.Subscription.create(**subscription_data)
            
            logger.info(f"Created subscription {subscription.id} with {application_fee_percent}% fee")
            return subscription
            
        except stripe.StripeError as e:
            logger.error(f"Stripe error creating subscription: {str(e)}")
            raise Exception(f"Failed to create subscription: {str(e)}")
        except Exception as e:
            logger.error(f"Error creating subscription: {str(e)}")
            raise
    
    async def create_price(
        self,
        amount: Decimal,
        currency: str,
        interval: str,
        product_id: str,
        connected_account: str
    ) -> str:
        """
        Create a Stripe price for subscriptions.
        """
        try:
            # Convert Decimal to cents
            amount_cents = int(amount * 100)
            
            price = stripe.Price.create(
                unit_amount=amount_cents,
                currency=currency.lower(),
                recurring={"interval": interval},  # "month" or "year"
                product=product_id,
                stripe_account=connected_account
            )
            
            logger.info(f"Created price {price.id} for {amount} {currency}/{interval}")
            return price.id
            
        except stripe.StripeError as e:
            logger.error(f"Stripe error creating price: {str(e)}")
            raise Exception(f"Failed to create price: {str(e)}")
        except Exception as e:
            logger.error(f"Error creating price: {str(e)}")
            raise
    
    async def create_product(
        self,
        name: str,
        description: str,
        connected_account: str,
        metadata: Dict[str, str] = None
    ) -> str:
        """
        Create a Stripe product for a strategy.
        """
        try:
            product = stripe.Product.create(
                name=name,
                description=description,
                type="service",
                metadata=metadata or {},
                stripe_account=connected_account
            )
            
            logger.info(f"Created product {product.id} for strategy")
            return product.id
            
        except stripe.StripeError as e:
            logger.error(f"Stripe error creating product: {str(e)}")
            raise Exception(f"Failed to create product: {str(e)}")
        except Exception as e:
            logger.error(f"Error creating product: {str(e)}")
            raise
    
    async def cancel_subscription(
        self,
        subscription_id: str,
        stripe_account: str = None
    ) -> Dict[str, Any]:
        """
        Cancel a Stripe subscription.

        Args:
            subscription_id: The Stripe subscription ID
            stripe_account: Optional connected account ID for Stripe Connect subscriptions
        """
        try:
            modify_params = {"cancel_at_period_end": True}
            if stripe_account:
                modify_params["stripe_account"] = stripe_account

            subscription = stripe.Subscription.modify(
                subscription_id,
                **modify_params
            )

            logger.info(f"Cancelled subscription {subscription_id}" + (f" on account {stripe_account}" if stripe_account else ""))
            return subscription

        except stripe.StripeError as e:
            logger.error(f"Stripe error cancelling subscription: {str(e)}")
            raise Exception(f"Failed to cancel subscription: {str(e)}")
        except Exception as e:
            logger.error(f"Error cancelling subscription: {str(e)}")
            raise
    
    async def handle_connect_webhook(self, event_data: Dict[str, Any]) -> None:
        """
        Handle Stripe Connect webhook events.
        """
        try:
            event_type = event_data.get("type")
            
            if event_type == "account.updated":
                await self._handle_account_updated(event_data)
            elif event_type == "payment_intent.succeeded":
                await self._handle_payment_succeeded(event_data)
            elif event_type == "invoice.payment_succeeded":
                await self._handle_subscription_payment(event_data)
            elif event_type == "customer.subscription.deleted":
                await self._handle_subscription_cancelled(event_data)
            else:
                logger.info(f"Unhandled webhook event: {event_type}")
                
        except Exception as e:
            logger.error(f"Error handling webhook event: {str(e)}")
            raise
    
    async def calculate_platform_fee(
        self, 
        creator_profile: CreatorProfile, 
        amount: Decimal
    ) -> Decimal:
        """
        Calculate platform fee based on creator tier and amount.
        """
        try:
            # Get platform fee percentage
            fee_percentage = creator_profile.platform_fee
            
            # Calculate fee amount
            fee_amount = amount * Decimal(str(fee_percentage))
            
            # Round to 2 decimal places
            return fee_amount.quantize(Decimal('0.01'))
            
        except Exception as e:
            logger.error(f"Error calculating platform fee: {str(e)}")
            raise
    
    async def create_account_session(
        self,
        account_id: str,
        creator_profile: Optional[CreatorProfile] = None
    ) -> Dict[str, Any]:
        """
        Create an Account Session for Stripe Embedded Components.
        This enables in-app onboarding without redirects.
        """
        try:
            # Prepare account session data with embedded onboarding configuration
            session_data = {
                "account": account_id,
                "components": {
                    "account_onboarding": {
                        "enabled": True,
                        "features": {
                            # Let Stripe handle user authentication and TOS acceptance
                            # This ensures proper TOS handling within Stripe's iframe
                            "disable_stripe_user_authentication": False,
                            # Still collect external account information
                            "external_account_collection": True
                        }
                    }
                }
            }
            
            logger.info(f"Creating account session with config: {session_data}")
            
            # Create the account session
            account_session = stripe.AccountSession.create(**session_data)
            
            logger.info(f"Created account session for Stripe account {account_id}")
            
            return {
                "client_secret": account_session.client_secret,
                "account_id": account_id,
                "expires_at": account_session.expires_at
            }
            
        except stripe.StripeError as e:
            logger.error(f"Stripe error creating account session: {str(e)}")
            raise Exception(f"Failed to create account session: {str(e)}")
        except Exception as e:
            logger.error(f"Error creating account session: {str(e)}")
            raise

    async def accept_tos(
        self,
        account_id: str,
        user_ip: str,
        user_agent: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Accept Terms of Service for a Stripe Connect account via API.
        This sends the TOS acceptance directly to Stripe when user clicks "Agree and Submit".
        """
        try:
            import time
            
            # Prepare TOS acceptance data
            tos_data = {
                "tos_acceptance": {
                    "date": int(time.time()),  # Current timestamp
                    "ip": user_ip
                }
            }
            
            # Add user agent if provided
            if user_agent:
                tos_data["tos_acceptance"]["user_agent"] = user_agent
            
            logger.info(f"Accepting TOS via API for account {account_id} from IP {user_ip}")
            
            # Update the account with TOS acceptance
            account = stripe.Account.modify(account_id, **tos_data)
            
            logger.info(f"TOS accepted successfully for account {account_id}")
            
            return {
                "tos_accepted": account.tos_acceptance.date is not None,
                "tos_date": account.tos_acceptance.date,
                "tos_ip": account.tos_acceptance.ip,
                "account_id": account_id
            }
            
        except stripe.StripeError as e:
            logger.error(f"Stripe error accepting TOS: {str(e)}")
            raise Exception(f"Failed to accept TOS: {str(e)}")
        except Exception as e:
            logger.error(f"Error accepting TOS: {str(e)}")
            raise

    async def _handle_account_updated(self, event_data: Dict[str, Any]) -> None:
        """Handle account.updated webhook."""
        # Implementation for account updates
        pass
    
    async def _handle_payment_succeeded(self, event_data: Dict[str, Any]) -> None:
        """Handle payment_intent.succeeded webhook."""
        # Implementation for successful payments
        pass
    
    async def _handle_subscription_payment(self, event_data: Dict[str, Any]) -> None:
        """Handle invoice.payment_succeeded webhook."""
        # Implementation for subscription payments
        pass
    
    async def _handle_subscription_cancelled(self, event_data: Dict[str, Any]) -> None:
        """Handle customer.subscription.deleted webhook."""
        # Implementation for subscription cancellations
        pass
    
    # ===== PHASE 3: Dynamic Stripe Integration Methods =====
    
    async def create_strategy_product(
        self,
        strategy_name: str,
        strategy_description: str,
        stripe_account_id: str,
        metadata: Dict[str, str] = None
    ) -> Dict[str, Any]:
        """
        Create a Stripe Product for a strategy automatically.
        This replaces manual product creation in Stripe dashboard.
        """
        try:
            product_data = {
                "name": f"Strategy: {strategy_name}",
                "description": strategy_description or f"Access to {strategy_name} trading strategy",
                "type": "service",
                "metadata": {
                    "strategy_name": strategy_name,
                    "product_type": "strategy_access",
                    **(metadata or {})
                }
            }
            
            product = stripe.Product.create(
                **product_data,
                stripe_account=stripe_account_id
            )
            
            logger.info(f"Created Stripe product {product.id} for strategy '{strategy_name}' on account {stripe_account_id}")
            return product
            
        except stripe.StripeError as e:
            logger.error(f"Stripe error creating strategy product: {str(e)}")
            raise Exception(f"Failed to create strategy product: {str(e)}")
        except Exception as e:
            logger.error(f"Error creating strategy product: {str(e)}")
            raise
    
    async def create_strategy_price(
        self,
        product_id: str,
        amount: float,
        currency: str = 'usd',
        billing_interval: Optional[str] = None,
        trial_period_days: int = 0,
        stripe_account_id: str = None,
        metadata: Dict[str, str] = None
    ) -> Dict[str, Any]:
        """
        Create a Stripe Price for a strategy product.
        Supports both subscription and one-time pricing.
        """
        try:
            # Convert billing_interval enum to string value if needed
            if hasattr(billing_interval, 'value'):
                billing_interval_str = billing_interval.value
            else:
                billing_interval_str = str(billing_interval) if billing_interval else None
            
            # Convert amount to cents for Stripe
            amount_cents = int(float(amount) * 100)
            
            price_data = {
                "unit_amount": amount_cents,
                "currency": currency.lower(),
                "product": product_id,
                "metadata": {
                    "price_type": billing_interval_str or "one_time",
                    "trial_days": str(trial_period_days),
                    **(metadata or {})
                }
            }
            
            # Add recurring configuration for subscriptions
            if billing_interval_str in ['month', 'year']:
                price_data["recurring"] = {
                    "interval": billing_interval_str,
                    "trial_period_days": trial_period_days if trial_period_days > 0 else None
                }
                
                # Remove None values from recurring config
                price_data["recurring"] = {k: v for k, v in price_data["recurring"].items() if v is not None}
            
            price = stripe.Price.create(
                **price_data,
                stripe_account=stripe_account_id
            )
            
            logger.info(f"Created Stripe price {price.id} for ${amount} {billing_interval_str or 'one-time'} on account {stripe_account_id}")
            return price
            
        except stripe.StripeError as e:
            logger.error(f"Stripe error creating strategy price: {str(e)}")
            raise Exception(f"Failed to create strategy price: {str(e)}")
        except Exception as e:
            logger.error(f"Error creating strategy price: {str(e)}")
            raise
    
    async def create_subscription_price(
        self,
        product_id: str,
        amount: float,
        interval: str,
        currency: str = 'usd',
        trial_period_days: int = 0,
        stripe_account_id: str = None
    ) -> Dict[str, Any]:
        """
        Create a subscription price with trial support.
        """
        return await self.create_strategy_price(
            product_id=product_id,
            amount=amount,
            currency=currency,
            billing_interval=interval,
            trial_period_days=trial_period_days,
            stripe_account_id=stripe_account_id,
            metadata={"price_category": "subscription"}
        )
    
    async def create_one_time_price(
        self,
        product_id: str,
        amount: float,
        currency: str = 'usd',
        stripe_account_id: str = None,
        price_type: str = 'lifetime'
    ) -> Dict[str, Any]:
        """
        Create a one-time payment price (lifetime access, setup fee, etc.).
        """
        return await self.create_strategy_price(
            product_id=product_id,
            amount=amount,
            currency=currency,
            billing_interval=None,
            trial_period_days=0,
            stripe_account_id=stripe_account_id,
            metadata={"price_category": "one_time", "price_type": price_type}
        )
    
    async def update_strategy_pricing(
        self,
        old_price_id: str,
        product_id: str,
        new_amount: float,
        billing_interval: Optional[str] = None,
        trial_period_days: int = 0,
        stripe_account_id: str = None
    ) -> Dict[str, Any]:
        """
        Update strategy pricing by creating new price and deactivating old one.
        Stripe doesn't allow price updates, so we create new and deactivate old.
        """
        try:
            # Create new price
            new_price = await self.create_strategy_price(
                product_id=product_id,
                amount=new_amount,
                billing_interval=billing_interval,
                trial_period_days=trial_period_days,
                stripe_account_id=stripe_account_id
            )
            
            # Deactivate old price
            await self.deactivate_price(old_price_id, stripe_account_id)
            
            logger.info(f"Updated pricing: new price {new_price.id}, deactivated {old_price_id}")
            return new_price
            
        except Exception as e:
            logger.error(f"Error updating strategy pricing: {str(e)}")
            raise
    
    async def deactivate_price(
        self,
        price_id: str,
        stripe_account_id: str = None
    ) -> Dict[str, Any]:
        """
        Deactivate a Stripe price (set active=False).
        """
        try:
            price = stripe.Price.modify(
                price_id,
                active=False,
                stripe_account=stripe_account_id
            )
            
            logger.info(f"Deactivated Stripe price {price_id}")
            return price
            
        except stripe.StripeError as e:
            logger.error(f"Stripe error deactivating price: {str(e)}")
            raise Exception(f"Failed to deactivate price: {str(e)}")
        except Exception as e:
            logger.error(f"Error deactivating price: {str(e)}")
            raise
    
    async def delete_product(
        self,
        product_id: str,
        stripe_account_id: str = None
    ) -> Dict[str, Any]:
        """
        Delete a Stripe product (used for cleanup on failed monetization setup).
        """
        try:
            product = stripe.Product.modify(
                product_id,
                active=False,
                stripe_account=stripe_account_id
            )
            
            logger.info(f"Deleted Stripe product {product_id}")
            return product
            
        except stripe.StripeError as e:
            logger.error(f"Stripe error deleting product: {str(e)}")
            raise Exception(f"Failed to delete product: {str(e)}")
        except Exception as e:
            logger.error(f"Error deleting product: {str(e)}")
            raise
    
    async def get_product_prices(
        self,
        product_id: str,
        stripe_account_id: str = None,
        active_only: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Get all prices for a product.
        """
        try:
            params = {
                "product": product_id,
                "limit": 100
            }
            
            if active_only:
                params["active"] = True
            
            prices = stripe.Price.list(
                **params,
                stripe_account=stripe_account_id
            )
            
            return prices.data
            
        except stripe.StripeError as e:
            logger.error(f"Stripe error getting product prices: {str(e)}")
            raise Exception(f"Failed to get product prices: {str(e)}")
        except Exception as e:
            logger.error(f"Error getting product prices: {str(e)}")
            raise
    
    def calculate_application_fee(
        self,
        amount: float,
        fee_percentage: float = 15.0
    ) -> float:
        """
        Calculate application fee for platform revenue.
        Default 15% platform fee.
        """
        return round(amount * (fee_percentage / 100.0), 2)
    
    async def create_checkout_session(
        self,
        price_id: str,
        success_url: str,
        cancel_url: str,
        customer_email: str = None,
        stripe_account_id: str = None,
        metadata: Dict[str, str] = None,
        application_fee_percent: float = 15.0
    ) -> Dict[str, Any]:
        """
        Create a Stripe Checkout session for strategy purchase.
        """
        try:
            session_data = {
                "payment_method_types": ["card"],
                "line_items": [{
                    "price": price_id,
                    "quantity": 1,
                }],
                "mode": "subscription" if "recurring" in price_id else "payment",
                "success_url": success_url,
                "cancel_url": cancel_url,
                "application_fee_percent": application_fee_percent,
                "metadata": metadata or {}
            }
            
            if customer_email:
                session_data["customer_email"] = customer_email
            
            session = stripe.checkout.Session.create(
                **session_data,
                stripe_account=stripe_account_id
            )
            
            logger.info(f"Created checkout session {session.id} for price {price_id}")
            return session
            
        except stripe.StripeError as e:
            logger.error(f"Stripe error creating checkout session: {str(e)}")
            raise Exception(f"Failed to create checkout session: {str(e)}")
        except Exception as e:
            logger.error(f"Error creating checkout session: {str(e)}")
            raise
    
    async def get_subscription(
        self,
        subscription_id: str,
        stripe_account: str = None
    ) -> Dict[str, Any]:
        """
        Get Stripe subscription details.

        Args:
            subscription_id: The Stripe subscription ID
            stripe_account: Optional connected account ID for Stripe Connect subscriptions
        """
        try:
            retrieve_params = {}
            if stripe_account:
                retrieve_params["stripe_account"] = stripe_account

            subscription = stripe.Subscription.retrieve(subscription_id, **retrieve_params)
            logger.info(f"Retrieved subscription {subscription_id}" + (f" from account {stripe_account}" if stripe_account else ""))
            return subscription

        except stripe.StripeError as e:
            logger.error(f"Stripe error retrieving subscription: {str(e)}")
            raise Exception(f"Failed to retrieve subscription: {str(e)}")
        except Exception as e:
            logger.error(f"Error retrieving subscription: {str(e)}")
            raise
    
    async def reactivate_subscription(
        self,
        subscription_id: str,
        stripe_account: str = None
    ) -> Dict[str, Any]:
        """
        Reactivate a cancelled subscription.

        Args:
            subscription_id: The Stripe subscription ID
            stripe_account: Optional connected account ID for Stripe Connect subscriptions
        """
        try:
            modify_params = {"cancel_at_period_end": False}
            if stripe_account:
                modify_params["stripe_account"] = stripe_account

            subscription = stripe.Subscription.modify(
                subscription_id,
                **modify_params
            )

            logger.info(f"Reactivated subscription {subscription_id}" + (f" on account {stripe_account}" if stripe_account else ""))
            return subscription

        except stripe.StripeError as e:
            logger.error(f"Stripe error reactivating subscription: {str(e)}")
            raise Exception(f"Failed to reactivate subscription: {str(e)}")
        except Exception as e:
            logger.error(f"Error reactivating subscription: {str(e)}")
            raise
    
    async def upgrade_subscription(self, subscription_id: str, new_price_id: str) -> Dict[str, Any]:
        """
        Upgrade a subscription to a new price.
        """
        try:
            # Get current subscription
            subscription = stripe.Subscription.retrieve(subscription_id)
            
            # Update subscription with new price
            updated_subscription = stripe.Subscription.modify(
                subscription_id,
                items=[{
                    'id': subscription['items']['data'][0]['id'],
                    'price': new_price_id,
                }],
                proration_behavior='always_invoice'
            )
            
            logger.info(f"Upgraded subscription {subscription_id} to price {new_price_id}")
            return updated_subscription
            
        except stripe.StripeError as e:
            logger.error(f"Stripe error upgrading subscription: {str(e)}")
            raise Exception(f"Failed to upgrade subscription: {str(e)}")
        except Exception as e:
            logger.error(f"Error upgrading subscription: {str(e)}")
            raise
    
    async def get_subscription_invoices(self, subscription_id: str) -> List[Dict[str, Any]]:
        """
        Get invoices for a subscription.
        """
        try:
            invoices = stripe.Invoice.list(
                subscription=subscription_id,
                limit=100
            )
            
            logger.info(f"Retrieved {len(invoices.data)} invoices for subscription {subscription_id}")
            return invoices.data
            
        except stripe.StripeError as e:
            logger.error(f"Stripe error retrieving invoices: {str(e)}")
            raise Exception(f"Failed to retrieve invoices: {str(e)}")
        except Exception as e:
            logger.error(f"Error retrieving invoices: {str(e)}")
            raise
    
    async def create_strategy_checkout_session(
        self,
        strategy_name: str,
        strategy_description: str,
        pricing: "StrategyPricing",
        billing_interval: str,
        connected_account_id: str,
        customer_email: str,
        success_url: str,
        cancel_url: str,
        metadata: dict
    ) -> str:
        """
        Create a Stripe Checkout session for strategy purchases using Stripe Connect.
        """
        try:
            # Determine the amount and price ID based on billing interval
            if billing_interval == "yearly" and pricing.yearly_amount:
                amount = pricing.yearly_amount
                stripe_price_id = pricing.stripe_yearly_price_id
            elif billing_interval == "monthly" and pricing.base_amount:
                amount = pricing.base_amount  
                stripe_price_id = pricing.stripe_price_id
            elif billing_interval == "lifetime" and pricing.base_amount:
                amount = pricing.base_amount
                stripe_price_id = pricing.stripe_price_id
            else:
                raise ValueError(f"Invalid billing interval or missing pricing: {billing_interval}")
            
            if not stripe_price_id:
                raise ValueError(f"Stripe price ID not configured for billing interval: {billing_interval}")
            
            # Calculate platform fee (this should match the creator's fee percentage)
            from app.models.creator_profile import CreatorProfile
            from app.db.session import SessionLocal
            
            db = SessionLocal()
            try:
                creator_profile = db.query(CreatorProfile).filter(
                    CreatorProfile.stripe_connect_account_id == connected_account_id
                ).first()
                
                if creator_profile:
                    platform_fee_percentage = float(creator_profile.platform_fee) * 100  # Convert to percentage
                else:
                    platform_fee_percentage = 20.0  # Default 20% fee
            finally:
                db.close()
            
            # Create checkout session parameters
            mode = "subscription" if pricing.pricing_type == "subscription" else "payment"
            
            session_params = {
                'payment_method_types': ['card'],
                'line_items': [
                    {
                        'price': stripe_price_id,
                        'quantity': 1,
                    }
                ],
                'mode': mode,
                'success_url': success_url,
                'cancel_url': cancel_url,
                'customer_email': customer_email,
                'metadata': metadata,
                'allow_promotion_codes': True,  # Enable coupon/promo codes
            }
            
            # For one-time payments, use payment_intent_data for application fees
            if mode == "payment":
                session_params['payment_intent_data'] = {
                    'application_fee_amount': int((amount * platform_fee_percentage / 100) * 100),  # Convert to cents
                }
            else:
                # For subscriptions, use subscription_data
                session_params['subscription_data'] = {
                    'application_fee_percent': platform_fee_percentage,
                }
                # Add trial period if enabled
                if pricing.is_trial_enabled and pricing.trial_days > 0:
                    session_params['subscription_data']['trial_period_days'] = pricing.trial_days
            
            # Create the checkout session on the connected account
            session = stripe.checkout.Session.create(**session_params, stripe_account=connected_account_id)
            
            logger.info(f"Created strategy checkout session {session.id} for connected account {connected_account_id}")
            return session.url
            
        except Exception as e:
            logger.error(f"Error creating strategy checkout session: {str(e)}")
            raise