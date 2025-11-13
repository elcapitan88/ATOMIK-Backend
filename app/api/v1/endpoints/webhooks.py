from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks, Body, Response
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from typing import List, Optional
from pydantic import BaseModel
import hmac
import hashlib
import secrets
from datetime import datetime
import logging
import os
import asyncio

from ....models.webhook import Webhook, WebhookLog, WebhookSubscription, WebhookRating
from ....core.security import get_current_user
from ....db.session import get_db
from ....models.user import User
from ....models.webhook import Webhook, WebhookLog
from ....models.subscription import Subscription
from ....schemas.webhook import (
    WebhookCreate,
    WebhookUpdate,
    WebhookOut,
    WebhookSecureOut,
    WebhookCreateResponse,
    WebhookLogOut,
    WebhookPayload
)
from ....services.webhook_service import WebhookProcessor, RailwayOptimizedWebhookProcessor
from ....core.config import settings
from ....core.upgrade_prompts import build_upgrade_response, UpgradeReason, add_upgrade_headers
from ....core.permissions import check_subscription, check_resource_limit, check_feature_access, require_tier


router = APIRouter()
logger = logging.getLogger(__name__)

def get_client_ip(request: Request) -> str:
    """Get client IP address from request"""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host

def generate_webhook_url(webhook: Webhook) -> str:
    """Generate complete webhook URL"""
    base_url = settings.SERVER_HOST.rstrip('/')
    return f"{base_url}/api/v1/webhooks/{webhook.token}"

def generate_complete_webhook_url(webhook: Webhook) -> str:
    """Generate complete webhook URL with secret for TradingView/third-party use"""
    base_url = settings.SERVER_HOST.rstrip('/')
    return f"{base_url}/api/v1/webhooks/{webhook.token}?secret={webhook.secret_key}"

@router.post("/generate", response_model=WebhookCreateResponse)
@check_subscription
@check_resource_limit("active_webhooks")
async def generate_webhook(
    webhook_in: WebhookCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    response: Response = None  # Added Response parameter
):
    try:
        logger.info(f"Received webhook creation request")
        logger.info(f"Webhook data: {webhook_in.dict()}")
        logger.info(f"Current user: {current_user.id}")
        
        # Resource limit check is already handled by @check_resource_limit decorator

        # Determine sharing settings based on usage intent
        usage_intent = webhook_in.usage_intent or 'personal'
        # Share both free and monetized strategies to marketplace
        is_shared = usage_intent in ['share_free', 'monetize']
        
        # Create webhook
        webhook = Webhook(
            user_id=current_user.id,
            token=secrets.token_urlsafe(32),
            secret_key=secrets.token_urlsafe(32),  # URL-safe secret for query parameters
            name=webhook_in.name if webhook_in.name else "New Webhook",
            source_type=webhook_in.source_type,
            details=webhook_in.details,
            allowed_ips=webhook_in.allowed_ips,
            max_triggers_per_minute=webhook_in.max_triggers_per_minute or 60,
            require_signature=webhook_in.require_signature if webhook_in.require_signature is not None else True,
            max_retries=webhook_in.max_retries or 3,
            strategy_type=webhook_in.strategy_type,
            usage_intent=usage_intent,
            is_shared=is_shared,
            sharing_enabled_at=datetime.utcnow() if is_shared else None,
            is_active=True,
            created_at=datetime.utcnow()
        )

        db.add(webhook)
        
        # Update webhook counter
        subscription = db.query(Subscription).filter(
            Subscription.user_id == current_user.id
        ).first()
        
        if subscription:
            subscription.active_webhooks_count = (subscription.active_webhooks_count or 0) + 1
        
        db.commit()
        db.refresh(webhook)
        
        # Log automatic sharing for share_free strategies
        if is_shared:
            logger.info(f"Strategy '{webhook.name}' (ID: {webhook.id}) automatically shared to marketplace due to 'share_free' intent")

        # Create webhook URLs
        webhook_url = generate_webhook_url(webhook)
        complete_webhook_url = generate_complete_webhook_url(webhook)

        # Return response with secret (ONLY during creation)
        return WebhookCreateResponse(
            id=webhook.id,
            token=webhook.token,
            user_id=webhook.user_id,
            name=webhook.name,
            source_type=webhook.source_type,
            details=webhook.details,
            secret_key=webhook.secret_key,  # Exposed only during creation
            allowed_ips=webhook.allowed_ips,
            max_triggers_per_minute=webhook.max_triggers_per_minute,
            require_signature=webhook.require_signature,
            max_retries=webhook.max_retries,
            strategy_type=webhook.strategy_type,
            usage_intent=webhook.usage_intent,
            is_shared=webhook.is_shared,
            is_active=webhook.is_active,
            created_at=webhook.created_at,
            last_triggered=webhook.last_triggered,
            webhook_url=webhook_url,
            complete_webhook_url=complete_webhook_url,  # Full URL with secret for TradingView
            subscriber_count=0,
            rating=0.0,
            username=current_user.username
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating webhook: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

@router.post("/{token}")
async def webhook_endpoint(
    token: str,
    request: Request,
    payload: WebhookPayload,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    secret: Optional[str] = None  # Add this to get the secret from query params
):
    """Handle incoming webhook requests"""
    try:
        # Get webhook
        webhook = db.query(Webhook).filter(
            Webhook.token == token,
            Webhook.is_active == True
        ).first()
        
        if not webhook:
            raise HTTPException(status_code=404, detail="Webhook not found")

        # Verify secret if required
        if webhook.require_signature:
            if not secret:
                raise HTTPException(
                    status_code=401,
                    detail="Secret parameter required"
                )
            
            if secret != webhook.secret_key:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid secret"
                )

        # Check IP allowlist if configured
        client_ip = get_client_ip(request)
        if webhook.allowed_ips:
            allowed_ips = [ip.strip() for ip in webhook.allowed_ips.split(',')]
            if client_ip not in allowed_ips:
                raise HTTPException(
                    status_code=403,
                    detail="IP not allowed"
                )

        # Detect Railway environment for optimizations
        use_railway_optimization = os.getenv("RAILWAY_ENVIRONMENT") is not None
        
        # Choose processor based on environment
        if use_railway_optimization:
            webhook_processor = RailwayOptimizedWebhookProcessor(db)
            logger.info("Using Railway-optimized webhook processor")
        else:
            webhook_processor = WebhookProcessor(db)
            logger.info("Using standard webhook processor")
        
        # Check rate limiting (10 requests per second for HFT support)
        # Use optimized pipeline version for Railway-optimized processing
        if hasattr(webhook_processor, 'check_rate_limit'):
            if use_railway_optimization and hasattr(webhook_processor, 'check_rate_limit_pipeline'):
                rate_check = webhook_processor.check_rate_limit_pipeline(webhook, client_ip)
            else:
                rate_check = webhook_processor.check_rate_limit(webhook, client_ip)
                
            if not rate_check:
                raise HTTPException(
                    status_code=429,
                    detail="Rate limit exceeded. Please wait before sending another request."
                )
        
        # Convert the Pydantic model to a plain dictionary and ensure action is properly formatted
        processed_payload = payload.dict()
        
        # Ensure action is a simple string value
        if 'action' in processed_payload:
            # Handle case where it's still the Enum string representation
            if isinstance(processed_payload['action'], str):
                if '.' in processed_payload['action'] and 'WEBHOOKACTION' in processed_payload['action']:
                    processed_payload['action'] = processed_payload['action'].split('.')[-1]
            # Always ensure it's uppercase
            processed_payload['action'] = str(processed_payload['action']).upper()

        if use_railway_optimization:
            # Use Railway-optimized direct processing (faster response)
            try:
                result = await webhook_processor.process_webhook_fast(
                    webhook=webhook,
                    payload=processed_payload,
                    client_ip=client_ip
                )
                logger.info(f"Railway-optimized webhook processed in {result.get('processing_time_ms', 'N/A')}ms")
                return result
            except Exception as e:
                logger.error(f"Railway-optimized processing failed, falling back to standard: {str(e)}")
                # Fallback to standard processing - create new processor
                use_railway_optimization = False
                webhook_processor = WebhookProcessor(db)
                logger.info("Switched to standard webhook processor for fallback")
        
        # Standard processing with background tasks
        idempotency_key = webhook_processor._generate_idempotency_key(webhook.id, processed_payload)
        
        response_data = {
            "status": "accepted", 
            "message": "Webhook received and being processed",
            "webhook_id": webhook.id,
            "timestamp": datetime.utcnow().isoformat(),
            "railway_optimized": use_railway_optimization
        }
        
        # Check if this is a duplicate request (1 second TTL for HFT support)
        # Use optimized pipeline version when available
        if hasattr(webhook_processor, '_check_and_set_idempotency_pipeline'):
            cached_response = webhook_processor._check_and_set_idempotency_pipeline(idempotency_key, response_data, ttl=1)
        else:
            cached_response = webhook_processor._check_and_set_idempotency(idempotency_key, response_data, ttl=1)
            
        if cached_response:
            logger.info(f"Duplicate webhook request detected, returning cached response")
            return cached_response

        # Pass the processed payload to the background task
        background_tasks.add_task(
            webhook_processor.process_webhook,
            webhook=webhook,
            payload=processed_payload,
            client_ip=client_ip
        )

        return response_data

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Webhook processing failed: {str(e)}"
        )

@router.get("/", response_model=List[WebhookSecureOut])
@check_subscription
async def get_webhooks_root(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    response: Response = None
):
    """
    Get all webhooks for the current user (root endpoint).
    This is the primary endpoint for listing webhooks, matching frontend expectations.
    """
    webhooks = db.query(Webhook).filter(
        Webhook.user_id == current_user.id
    ).all()

    # Add upgrade suggestion if approaching limits
    if not settings.SKIP_SUBSCRIPTION_CHECK:
        subscription = db.query(Subscription).filter(
            Subscription.user_id == current_user.id
        ).first()

        if subscription:
            user_tier = subscription.tier
            max_webhooks = float('inf')

            if user_tier == "starter":
                max_webhooks = 1
            elif user_tier == "pro":
                max_webhooks = 5

            # Add upgrade headers if approaching limit
            if len(webhooks) >= max_webhooks - 1 and user_tier != "elite":
                next_tier = "pro" if user_tier == "starter" else "elite"

                if response:
                    add_upgrade_headers(response, user_tier, UpgradeReason.WEBHOOK_LIMIT)

    return [
        WebhookSecureOut(
            id=webhook.id,
            token=webhook.token,
            user_id=webhook.user_id,
            name=webhook.name,
            source_type=webhook.source_type,
            details=webhook.details,
            allowed_ips=webhook.allowed_ips,
            max_triggers_per_minute=webhook.max_triggers_per_minute,
            require_signature=webhook.require_signature,
            max_retries=webhook.max_retries,
            is_active=webhook.is_active,
            is_shared=webhook.is_shared,
            created_at=webhook.created_at,
            last_triggered=webhook.last_triggered,
            # secret_key=webhook.secret_key,  # REMOVED - No longer exposed!
            webhook_url=generate_webhook_url(webhook),
            subscriber_count=0,  # Default for now
            rating=0.0,  # Default for now
            username=current_user.username
        ) for webhook in webhooks
    ]


@router.get("/list", response_model=List[WebhookSecureOut])
@check_subscription
async def list_webhooks(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    response: Response = None  # Added Response parameter
):
    """
    List all webhooks for the current user (legacy endpoint).
    Kept for backward compatibility. Use GET / instead.
    """
    # Call the root endpoint to avoid duplication
    return await get_webhooks_root(db=db, current_user=current_user, response=response)



@router.patch("/{token}", response_model=WebhookSecureOut)
async def update_webhook(
    token: str,
    webhook_update: WebhookUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update webhook settings"""
    webhook = db.query(Webhook).filter(
        Webhook.token == token,
        Webhook.user_id == current_user.id
    ).first()

    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")

    # Update fields
    for key, value in webhook_update.dict(exclude_unset=True).items():
        setattr(webhook, key, value)

    db.commit()
    db.refresh(webhook)

    # Return secure response without secret_key
    return WebhookSecureOut(
        id=webhook.id,
        token=webhook.token,
        user_id=webhook.user_id,
        name=webhook.name,
        source_type=webhook.source_type,
        details=webhook.details,
        allowed_ips=webhook.allowed_ips,
        max_triggers_per_minute=webhook.max_triggers_per_minute,
        require_signature=webhook.require_signature,
        max_retries=webhook.max_retries,
        is_active=webhook.is_active,
        is_shared=webhook.is_shared,
        created_at=webhook.created_at,
        last_triggered=webhook.last_triggered,
        webhook_url=generate_webhook_url(webhook),
        subscriber_count=webhook.subscriber_count or 0,
        rating=webhook.rating or 0.0,
        username=current_user.username
    )

@router.delete("/{token}")
async def delete_webhook(
    token: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a webhook"""
    webhook = db.query(Webhook).filter(
        Webhook.token == token,
        Webhook.user_id == current_user.id
    ).first()

    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")

    try:
        # Get subscription before deleting webhook
        subscription = db.query(Subscription).filter(
            Subscription.user_id == current_user.id
        ).first()
        
        # Delete webhook
        db.delete(webhook)
        
        # Update counter
        if subscription and subscription.active_webhooks_count > 0:
            subscription.active_webhooks_count -= 1
            
        db.commit()

        return {
            "status": "success",
            "message": "Webhook deleted successfully"
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting webhook: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error deleting webhook: {str(e)}"
        )

@router.get("/{token}/logs", response_model=List[WebhookLogOut])
async def get_webhook_logs(
    token: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    limit: int = 50,
    skip: int = 0
):
    """Get logs for a specific webhook"""
    webhook = db.query(Webhook).filter(
        Webhook.token == token,
        Webhook.user_id == current_user.id
    ).first()

    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")

    logs = db.query(WebhookLog).filter(
        WebhookLog.webhook_id == webhook.id
    ).order_by(
        WebhookLog.triggered_at.desc()
    ).offset(skip).limit(limit).all()

    return logs

@router.post("/{token}/test")
async def test_webhook(
    token: str,
    test_type: str = "entry",  # entry, exit_half, exit_final, full_cycle
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Test webhook with different exit scenarios"""
    webhook = db.query(Webhook).filter(
        Webhook.token == token,
        Webhook.user_id == current_user.id
    ).first()

    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")

    # Define test payload templates
    test_payloads = {
        "entry": {
            "action": "BUY",
            "comment": "ENTRY"
        },
        "exit_half": {
            "action": "SELL",
            "comment": "EXIT_50"
        },
        "exit_25": {
            "action": "SELL",
            "comment": "EXIT_25"
        },
        "exit_75": {
            "action": "SELL",
            "comment": "EXIT_75"
        },
        "exit_final": {
            "action": "SELL",
            "comment": "EXIT_FINAL"
        },
        "exit_all": {
            "action": "SELL",
            "comment": "EXIT_ALL"
        }
    }

    try:
        webhook_processor = WebhookProcessor(db)
        
        if test_type == "full_cycle":
            # Test complete entry -> partial exit -> final exit cycle
            results = []
            cycle_payloads = ["entry", "exit_half", "exit_final"]
            
            for payload_type in cycle_payloads:
                payload = test_payloads[payload_type].copy()
                payload["test"] = True
                payload["timestamp"] = datetime.utcnow().isoformat()
                
                result = await webhook_processor.process_webhook(
                    webhook=webhook,
                    payload=payload,
                    client_ip="127.0.0.1"
                )
                
                results.append({
                    "step": payload_type,
                    "payload": payload,
                    "result": result
                })
                
                # Brief delay between orders to allow processing
                await asyncio.sleep(0.5)
            
            return {
                "status": "success",
                "message": "Full cycle test completed",
                "webhook_url": generate_webhook_url(webhook),
                "cycle_results": results
            }
        
        else:
            # Test single payload type
            if test_type not in test_payloads:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid test_type. Options: {list(test_payloads.keys()) + ['full_cycle']}"
                )
            
            test_payload = test_payloads[test_type].copy()
            test_payload["test"] = True
            test_payload["timestamp"] = datetime.utcnow().isoformat()
            
            result = await webhook_processor.process_webhook(
                webhook=webhook,
                payload=test_payload,
                client_ip="127.0.0.1"
            )

            return {
                "status": "success",
                "message": f"Test webhook triggered successfully with {test_type}",
                "webhook_url": generate_webhook_url(webhook),
                "test_payload": test_payload,
                "result": result
            }

    except Exception as e:
        logger.error(f"Error testing webhook: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Webhook test failed: {str(e)}"
        )
    
@router.post("/{token}/share", response_model=WebhookSecureOut)
@check_subscription
@check_feature_access("can_share_webhooks")
async def toggle_share_webhook(
    token: str,
    data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    response: Response = None  # Added Response parameter
):
    try:
        webhook = db.query(Webhook).filter(
            Webhook.token == token,
            Webhook.user_id == current_user.id
        ).first()

        if not webhook:
            raise HTTPException(status_code=404, detail="Webhook not found")
            
        # Check sharing feature access with detailed upgrade information
        if not settings.SKIP_SUBSCRIPTION_CHECK:
            subscription = db.query(Subscription).filter(
                Subscription.user_id == current_user.id
            ).first()
            
            if subscription and subscription.tier == "starter" and data.get("isActive", False):
                # Provide detailed upgrade information for webhook sharing
                upgrade_info = build_upgrade_response(
                    reason=UpgradeReason.WEBHOOK_SHARING,
                    current_tier="starter",
                    status_code=403
                )
                
                if response:
                    add_upgrade_headers(response, "starter", UpgradeReason.WEBHOOK_SHARING)
                
                raise HTTPException(
                    status_code=403,
                    detail=upgrade_info
                )

        try:
            new_shared_state = data.get("isActive", False)
            webhook.is_shared = new_shared_state
            webhook.details = data.get("description", webhook.details)
            
            # Only update strategy_type if it's provided and valid
            if strategy_type := data.get("strategyType"):
                webhook.strategy_type = strategy_type
            elif new_shared_state:
                # If activating sharing, strategy type is required
                raise HTTPException(
                    status_code=400,
                    detail="Update Strategy Type before sharing"
                )

            webhook.sharing_enabled_at = datetime.utcnow() if new_shared_state else None

            db.commit()
            db.refresh(webhook)

            # Create a properly formatted response using the secure model
            return WebhookSecureOut(
                id=webhook.id,
                user_id=webhook.user_id,
                token=webhook.token,
                name=webhook.name,
                source_type=webhook.source_type,
                details=webhook.details,
                allowed_ips=webhook.allowed_ips,
                max_triggers_per_minute=webhook.max_triggers_per_minute,
                require_signature=webhook.require_signature,
                max_retries=webhook.max_retries,
                is_active=webhook.is_active,
                is_shared=webhook.is_shared,
                created_at=webhook.created_at,
                last_triggered=webhook.last_triggered,
                webhook_url=generate_webhook_url(webhook),
                # secret_key=webhook.secret_key,  # REMOVED - No longer exposed!
                strategy_type=webhook.strategy_type,
                subscriber_count=webhook.subscriber_count,
                rating=webhook.rating,
                username=current_user.username
            )

        except SQLAlchemyError as db_error:
            db.rollback()
            logger.error(f"Database error while updating webhook: {str(db_error)}")
            raise HTTPException(
                status_code=500,
                detail="Database error occurred while updating webhook"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating webhook sharing status: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update webhook sharing status: {str(e)}"
        )

@router.get("/shared", response_model=List[WebhookOut])
@check_subscription
async def list_shared_strategies(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all shared strategies with monetization information"""
    try:
        webhooks = (
            db.query(Webhook)
            .join(User)
            .filter(Webhook.is_shared == True)
            .all()
        )

        # Generate response with webhook URLs and monetization info
        response = []
        for webhook in webhooks:
            webhook_data = webhook.__dict__.copy()
            
            # Generate webhook URL
            base_url = settings.SERVER_HOST.rstrip('/')
            webhook_data["webhook_url"] = f"{base_url}/api/v1/webhooks/{webhook.token}"
            
            # Add username from relationship
            webhook_data["username"] = webhook.user.username
            
            # Add monetization information for frontend routing
            webhook_data["is_monetized"] = webhook.is_monetized or False
            webhook_data["usage_intent"] = webhook.usage_intent or 'personal'
            
            # Add marketplace URLs for monetized strategies
            if webhook.is_monetized or webhook.usage_intent == 'monetize':
                webhook_data["marketplace_purchase_url"] = f"/marketplace/strategy/{webhook.token}/purchase"
                webhook_data["pricing_endpoint"] = f"/api/v1/marketplace/strategies/{webhook.token}/pricing"
            
            # Remove SQLAlchemy state
            webhook_data.pop('_sa_instance_state', None)
            # Remove user object as we already have username
            webhook_data.pop('user', None)
            
            response.append(webhook_data)

        logger.info(f"Listed {len(response)} shared strategies ({sum(1 for s in response if s['is_monetized'])} monetized)")
        return response

    except Exception as e:
        logger.error(f"Error fetching shared strategies: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch shared strategies: {str(e)}"
        )
    
# app/api/v1/endpoints/webhooks.py

@router.get("/subscribed", response_model=List[WebhookOut])
async def get_subscribed_strategies(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all strategies the current user is subscribed to"""
    try:
        subscriptions = (
            db.query(Webhook)
            .join(WebhookSubscription)
            .filter(
                WebhookSubscription.user_id == current_user.id,
                Webhook.is_shared == True
            )
            .all()
        )

        return [
            WebhookOut(
                **webhook.__dict__,
                webhook_url=generate_webhook_url(webhook),
                username=webhook.user.username
            ) 
            for webhook in subscriptions
        ]
    except Exception as e:
        logger.error(f"Error fetching subscribed strategies: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch subscribed strategies: {str(e)}"
        )

@router.post("/{token}/subscribe")
@check_subscription
async def subscribe_to_strategy(
    token: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Subscribe to a strategy - redirects monetized strategies to payment flow"""
    try:
        webhook = db.query(Webhook).filter(
            Webhook.token == token,
            Webhook.is_shared == True
        ).first()

        if not webhook:
            raise HTTPException(status_code=404, detail="Strategy not found")

        # SECURITY FIX: Check if this is a monetized strategy
        if webhook.is_monetized or webhook.usage_intent == 'monetize':
            # Check if strategy has monetization setup (NEW system)
            from ....models.strategy_pricing import StrategyPricing
            pricing = db.query(StrategyPricing).filter(
                StrategyPricing.webhook_id == webhook.id,
                StrategyPricing.is_active == True
            ).first()
            
            if pricing and pricing.pricing_type != "free":
                # This is a monetized strategy - require payment
                # Include pricing details to help frontend display them immediately
                pricing_info = {
                    "type": pricing.pricing_type,
                    "monthly_price": float(pricing.base_amount) if pricing.base_amount else None,
                    "yearly_price": float(pricing.yearly_amount) if pricing.yearly_amount else None,
                    "currency": "USD",
                    "has_trial": pricing.is_trial_enabled,
                    "trial_days": pricing.trial_days if pricing.is_trial_enabled else 0
                }

                raise HTTPException(
                    status_code=402,  # Payment Required
                    detail={
                        "error_code": "PAYMENT_REQUIRED",
                        "message": "This strategy requires a paid subscription.",
                        "strategy_name": webhook.name,
                        "strategy_token": token,
                        "is_monetized": True,
                        "pricing": pricing_info,
                        "checkout_endpoint": f"/api/v1/marketplace/strategies/{token}/create-checkout",
                        "pricing_endpoint": f"/api/v1/marketplace/strategies/{token}/pricing",
                        "marketplace_url": f"/marketplace/strategy/{token}"
                    }
                )

        # Only allow subscriptions to shared strategies (personal strategies blocked by is_shared check above)
        # For shared strategies: non-monetized ones allow free subscription, monetized ones redirect to payment
        if not webhook.is_shared:
            # This should already be caught above, but double-check for safety
            raise HTTPException(
                status_code=400,
                detail="This strategy is not shared and cannot be subscribed to"
            )

        # Check if already subscribed
        existing_subscription = db.query(WebhookSubscription).filter(
            WebhookSubscription.webhook_id == webhook.id,
            WebhookSubscription.user_id == current_user.id
        ).first()

        if existing_subscription:
            raise HTTPException(
                status_code=400,
                detail="Already subscribed to this strategy"
            )

        # Create subscription for free strategies only
        subscription = WebhookSubscription(
            webhook_id=webhook.id,
            user_id=current_user.id
        )
        db.add(subscription)
        
        # Update subscriber count
        webhook.subscriber_count = (webhook.subscriber_count or 0) + 1

        db.commit()

        logger.info(f"Free subscription created for strategy {webhook.name} (ID: {webhook.id}) by user {current_user.id}")

        return {
            "status": "success",
            "message": "Successfully subscribed to free strategy"
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error subscribing to strategy: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to subscribe to strategy: {str(e)}"
        )

@router.get("/{token}/access-info")
async def get_strategy_access_info(
    token: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Check user's access to a strategy and get monetization info.
    Returns whether user has access and how (owner/subscriber/purchaser).
    For monetized strategies, includes pricing information.
    """
    try:
        webhook = db.query(Webhook).filter(
            Webhook.token == token
        ).first()

        if not webhook:
            raise HTTPException(status_code=404, detail="Strategy not found")

        # Check user's access
        is_owner = webhook.user_id == current_user.id

        # Check for free subscription
        has_subscription = db.query(WebhookSubscription).filter(
            WebhookSubscription.webhook_id == webhook.id,
            WebhookSubscription.user_id == current_user.id
        ).first() is not None

        # Check for paid purchase
        from ....models.strategy_purchase import StrategyPurchase
        has_purchase = db.query(StrategyPurchase).filter(
            StrategyPurchase.webhook_id == webhook.id,
            StrategyPurchase.user_id == current_user.id,
            StrategyPurchase.status.in_(["pending", "completed"])
        ).first() is not None

        # Get pricing info if monetized
        pricing_info = None
        if webhook.is_monetized or webhook.usage_intent == 'monetize':
            from ....models.strategy_pricing import StrategyPricing
            pricing = db.query(StrategyPricing).filter(
                StrategyPricing.webhook_id == webhook.id,
                StrategyPricing.is_active == True
            ).first()

            if pricing:
                pricing_info = {
                    "type": pricing.pricing_type,
                    "monthly_price": float(pricing.base_amount) if pricing.base_amount else None,
                    "yearly_price": float(pricing.yearly_amount) if pricing.yearly_amount else None,
                    "currency": "USD",
                    "has_trial": pricing.is_trial_enabled,
                    "trial_days": pricing.trial_days if pricing.is_trial_enabled else 0,
                    "checkout_endpoint": f"/api/v1/marketplace/strategies/{token}/create-checkout"
                }

        # Determine access method
        access_method = None
        has_access = False

        if is_owner:
            access_method = "owner"
            has_access = True
        elif has_purchase:
            access_method = "purchased"
            has_access = True
        elif has_subscription:
            access_method = "subscribed"
            has_access = True

        # Special handling for Break N Enter
        is_hybrid_strategy = webhook.id == 117  # Break N Enter

        return {
            "strategy_name": webhook.name,
            "strategy_token": token,
            "is_monetized": webhook.is_monetized,
            "has_access": has_access,
            "access_method": access_method,
            "is_owner": is_owner,
            "is_hybrid_strategy": is_hybrid_strategy,
            "pricing": pricing_info,
            "can_subscribe_free": not webhook.is_monetized and webhook.is_shared,
            "requires_purchase": webhook.is_monetized and not has_access
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting strategy access info: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get strategy access info: {str(e)}"
        )

@router.post("/{token}/unsubscribe")
async def unsubscribe_from_strategy(
    token: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Unsubscribe from a strategy"""
    try:
        webhook = db.query(Webhook).filter(
            Webhook.token == token
        ).first()

        if not webhook:
            raise HTTPException(status_code=404, detail="Strategy not found")

        subscription = db.query(WebhookSubscription).filter(
            WebhookSubscription.webhook_id == webhook.id,
            WebhookSubscription.user_id == current_user.id
        ).first()

        if not subscription:
            raise HTTPException(
                status_code=400,
                detail="Not subscribed to this strategy"
            )

        # Delete subscription
        db.delete(subscription)
        
        # Update subscriber count
        if webhook.subscriber_count:
            webhook.subscriber_count = max(0, webhook.subscriber_count - 1)

        db.commit()

        return {
            "status": "success",
            "message": "Successfully unsubscribed from strategy"
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error unsubscribing from strategy: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to unsubscribe from strategy: {str(e)}"
        )
    
# app/api/v1/endpoints/webhooks.py
class RatingRequest(BaseModel):
    rating: int


@router.post("/{token}/rate")
async def rate_strategy(
    token: str,
    rating: int = Body(..., embed=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    
    print(f"Received rating request - Token: {token}, Rating: {rating}")

    """Rate a strategy"""
    try:
        # Get the webhook
        webhook = db.query(Webhook).filter(
            Webhook.token == token,
            Webhook.is_shared == True
        ).first()

        if not webhook:
            raise HTTPException(status_code=404, detail="Strategy not found")

        # Check if user is subscribed
        subscription = db.query(WebhookSubscription).filter(
            WebhookSubscription.webhook_id == webhook.id,
            WebhookSubscription.user_id == current_user.id
        ).first()

        if not subscription:
            raise HTTPException(
                status_code=403,
                detail="You must be subscribed to rate this strategy"
            )

        # Get existing rating if any
        existing_rating = db.query(WebhookRating).filter(
            WebhookRating.webhook_id == webhook.id,
            WebhookRating.user_id == current_user.id
        ).first()

        if existing_rating:
            # Update existing rating
            existing_rating.rating = rating
            existing_rating.rated_at = datetime.utcnow()
        else:
            # Create new rating
            new_rating = WebhookRating(
                webhook_id=webhook.id,
                user_id=current_user.id,
                rating=rating
            )
            db.add(new_rating)

        # Update webhook's average rating
        all_ratings = db.query(WebhookRating).filter(
            WebhookRating.webhook_id == webhook.id
        ).all()
        
        total_ratings = len(all_ratings) + (1 if not existing_rating else 0)
        rating_sum = sum(r.rating for r in all_ratings) + (rating if not existing_rating else 0)
        
        webhook.rating = rating_sum / total_ratings
        webhook.total_ratings = total_ratings

        db.commit()

        return {
            "status": "success",
            "message": "Rating updated successfully",
            "new_rating": webhook.rating,
            "total_ratings": webhook.total_ratings
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error rating strategy: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update rating: {str(e)}"
        )