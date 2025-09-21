"""Engine strategy subscription endpoints."""
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import and_
from datetime import datetime

from ....db.session import get_db
from ....core.security import get_current_user
from ....models.user import User
from ....models.strategy_code import StrategyCode
from ....models.webhook import WebhookSubscription  # Using extended table
from ....core.permissions import check_subscription

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/engine/{strategy_id}/subscribe")
@check_subscription
async def subscribe_to_engine_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Subscribe to an engine strategy."""
    try:
        # Find the engine strategy
        strategy = db.query(StrategyCode).filter(
            StrategyCode.id == strategy_id,
            StrategyCode.is_active == True,
            StrategyCode.is_validated == True
        ).first()
        
        if not strategy:
            raise HTTPException(
                status_code=404, 
                detail="Engine strategy not found or not available"
            )
        
        # Check if already subscribed
        existing_sub = db.query(WebhookSubscription).filter(
            and_(
                WebhookSubscription.user_id == current_user.id,
                WebhookSubscription.strategy_type == 'engine',
                WebhookSubscription.strategy_code_id == strategy_id
            )
        ).first()
        
        if existing_sub:
            return {
                "message": "Already subscribed to this strategy",
                "strategy_name": strategy.name,
                "subscription_id": existing_sub.id
            }
        
        # Create new subscription
        new_subscription = WebhookSubscription(
            user_id=current_user.id,
            strategy_type='engine',
            strategy_id=str(strategy_id),
            strategy_code_id=strategy_id,
            subscribed_at=datetime.utcnow()
        )
        
        db.add(new_subscription)
        db.commit()
        db.refresh(new_subscription)
        
        logger.info(f"User {current_user.id} subscribed to engine strategy {strategy_id}")
        
        return {
            "message": "Successfully subscribed to engine strategy",
            "strategy_name": strategy.name,
            "subscription_id": new_subscription.id,
            "can_activate": True,
            "activation_url": f"/dashboard/strategies/activate/{strategy_id}"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error subscribing to engine strategy: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to subscribe to strategy: {str(e)}"
        )


@router.post("/engine/{strategy_id}/unsubscribe")
async def unsubscribe_from_engine_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Unsubscribe from an engine strategy."""
    try:
        # Find the subscription
        subscription = db.query(WebhookSubscription).filter(
            and_(
                WebhookSubscription.user_id == current_user.id,
                WebhookSubscription.strategy_type == 'engine',
                WebhookSubscription.strategy_code_id == strategy_id
            )
        ).first()
        
        if not subscription:
            raise HTTPException(
                status_code=404,
                detail="Subscription not found"
            )
        
        # Check if there are active activations
        from ....models.strategy import ActivatedStrategy
        active_count = db.query(ActivatedStrategy).filter(
            ActivatedStrategy.user_id == current_user.id,
            ActivatedStrategy.strategy_code_id == strategy_id,
            ActivatedStrategy.is_active == True
        ).count()
        
        if active_count > 0:
            return {
                "message": "Please deactivate the strategy before unsubscribing",
                "active_activations": active_count,
                "deactivate_url": "/dashboard/strategies"
            }
        
        # Delete subscription
        db.delete(subscription)
        db.commit()
        
        logger.info(f"User {current_user.id} unsubscribed from engine strategy {strategy_id}")
        
        return {
            "message": "Successfully unsubscribed from engine strategy"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error unsubscribing from engine strategy: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to unsubscribe from strategy: {str(e)}"
        )


@router.get("/engine/subscriptions")
async def get_engine_subscriptions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get user's engine strategy subscriptions."""
    try:
        subscriptions = db.query(WebhookSubscription).filter(
            WebhookSubscription.user_id == current_user.id,
            WebhookSubscription.strategy_type == 'engine'
        ).all()
        
        result = []
        for sub in subscriptions:
            strategy = db.query(StrategyCode).filter(
                StrategyCode.id == sub.strategy_code_id
            ).first()
            
            if strategy:
                result.append({
                    "subscription_id": sub.id,
                    "strategy_id": strategy.id,
                    "strategy_name": strategy.name,
                    "description": strategy.description,
                    "subscribed_at": sub.subscribed_at.isoformat() if sub.subscribed_at else None,
                    "is_active": strategy.is_active,
                    "can_activate": True
                })
        
        return {
            "subscriptions": result,
            "total": len(result)
        }
        
    except Exception as e:
        logger.error(f"Error fetching engine subscriptions: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch subscriptions: {str(e)}"
        )