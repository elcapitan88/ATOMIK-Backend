# app/services/stripe_connect_service.py
import stripe
from typing import Dict, Any, Optional
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
                # Set requirement collection to application for embedded components
                controller={
                    "requirement_collection": "application",
                    "losses": {
                        "payments": "application"
                    },
                    "fees": {
                        "payer": "application"
                    },
                    "stripe_dashboard": {
                        "type": "none"
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
            
        except stripe.error.StripeError as e:
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
                    except stripe.error.StripeError as update_error:
                        logger.warning(f"Could not update account prefill data: {update_error}")
                        # Continue with account link creation even if prefill fails
            
            account_link = stripe.AccountLink.create(**account_link_data)
            
            logger.info(f"Created account link for account {account_id} with prefill data")
            return account_link
            
        except stripe.error.StripeError as e:
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
            
        except stripe.error.StripeError as e:
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
            
        except stripe.error.StripeError as e:
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
            
        except stripe.error.StripeError as e:
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
            
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error creating product: {str(e)}")
            raise Exception(f"Failed to create product: {str(e)}")
        except Exception as e:
            logger.error(f"Error creating product: {str(e)}")
            raise
    
    async def cancel_subscription(self, subscription_id: str) -> Dict[str, Any]:
        """
        Cancel a Stripe subscription.
        """
        try:
            subscription = stripe.Subscription.modify(
                subscription_id,
                cancel_at_period_end=True
            )
            
            logger.info(f"Cancelled subscription {subscription_id}")
            return subscription
            
        except stripe.error.StripeError as e:
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
                            # Disable Stripe user authentication to enable fully embedded onboarding
                            # Note: This means we take responsibility for account security
                            "disable_stripe_user_authentication": True,
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
            
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error creating account session: {str(e)}")
            raise Exception(f"Failed to create account session: {str(e)}")
        except Exception as e:
            logger.error(f"Error creating account session: {str(e)}")
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