"""
Special activation service for Break and Enter strategy migration.
Handles the hybrid approach: webhook subscriptions + engine execution.
"""

import logging
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from fastapi import HTTPException

from ..models.webhook import Webhook, WebhookSubscription
from ..models.strategy_purchase import StrategyPurchase
from ..models.strategy_code import StrategyCode
from ..models.strategy import ActivatedStrategy
from ..models.user import User

logger = logging.getLogger(__name__)

# Constants for Break and Enter strategy
BREAK_ENTER_WEBHOOK_ID = 117
BREAK_ENTER_WEBHOOK_TOKEN = 'OGgxOp0wOd60YGb4kc4CEh8oSz2ZCscKVVZtfwbCbHg'
BREAK_ENTER_STRATEGY_NAME = 'break_and_enter'


class BreakEnterActivationService:
    """Service to handle Break and Enter strategy activation during migration."""
    
    def __init__(self, db: Session):
        self.db = db
        
    def check_user_access(self, user_id: int) -> Dict[str, Any]:
        """
        Check if user has access to Break and Enter strategy.
        Checks both webhook subscriptions and purchases.
        """
        # Check if user owns the webhook
        webhook = self.db.query(Webhook).filter(Webhook.id == BREAK_ENTER_WEBHOOK_ID).first()
        if not webhook:
            raise HTTPException(status_code=404, detail="Break and Enter strategy not found")
        
        is_owner = webhook.user_id == user_id
        
        # Check free subscription
        is_subscriber = self.db.query(WebhookSubscription).filter(
            WebhookSubscription.webhook_id == BREAK_ENTER_WEBHOOK_ID,
            WebhookSubscription.user_id == user_id
        ).first() is not None
        
        # Check paid purchase
        has_purchase = self.db.query(StrategyPurchase).filter(
            StrategyPurchase.webhook_id == BREAK_ENTER_WEBHOOK_ID,
            StrategyPurchase.user_id == user_id,
            StrategyPurchase.status == "COMPLETED"
        ).first() is not None
        
        has_access = is_owner or is_subscriber or has_purchase
        
        access_method = None
        if is_owner:
            access_method = "owner"
        elif has_purchase:
            access_method = "paid_subscription"
        elif is_subscriber:
            access_method = "free_subscription"
        
        return {
            "has_access": has_access,
            "access_method": access_method,
            "webhook_id": webhook.id,
            "webhook_token": webhook.token,
            "webhook_name": webhook.name
        }
    
    def get_strategy_code_id(self) -> Optional[int]:
        """Get the strategy_code ID for Break and Enter engine strategy."""
        strategy_code = self.db.query(StrategyCode).filter(
            StrategyCode.name == BREAK_ENTER_STRATEGY_NAME,
            StrategyCode.is_active == True,
            StrategyCode.is_validated == True
        ).first()
        
        if not strategy_code:
            logger.error(f"Break and Enter strategy code not found: {BREAK_ENTER_STRATEGY_NAME}")
            return None
        
        return strategy_code.id
    
    def create_activation(
        self, 
        user_id: int, 
        account_id: str, 
        quantity: int,
        ticker: str = "MNQ"
    ) -> ActivatedStrategy:
        """
        Create a Break and Enter strategy activation using engine execution
        but maintaining webhook subscription validation.
        """
        # Check user access
        access_info = self.check_user_access(user_id)
        if not access_info["has_access"]:
            raise HTTPException(
                status_code=403,
                detail="You don't have access to Break and Enter strategy. Please subscribe first."
            )
        
        # Get strategy code ID
        strategy_code_id = self.get_strategy_code_id()
        if not strategy_code_id:
            raise HTTPException(
                status_code=500,
                detail="Break and Enter strategy engine not configured. Please contact support."
            )
        
        # Check if user already has this strategy activated
        existing = self.db.query(ActivatedStrategy).filter(
            ActivatedStrategy.user_id == user_id,
            ActivatedStrategy.strategy_code_id == strategy_code_id,
            ActivatedStrategy.is_active == True
        ).first()
        
        if existing:
            raise HTTPException(
                status_code=400,
                detail="Break and Enter strategy is already activated for this user"
            )
        
        # Create the hybrid activation
        activation = ActivatedStrategy(
            user_id=user_id,
            strategy_type='single',
            execution_type='engine',  # Use engine execution
            webhook_id=BREAK_ENTER_WEBHOOK_TOKEN,  # Keep webhook reference for billing/history
            strategy_code_id=strategy_code_id,  # Link to engine strategy
            ticker=ticker,
            account_id=account_id,
            quantity=quantity,
            is_active=True
        )
        
        self.db.add(activation)
        self.db.commit()
        self.db.refresh(activation)
        
        logger.info(
            f"Created Break and Enter activation for user {user_id}: "
            f"ID={activation.id}, access_method={access_info['access_method']}, "
            f"execution_type=engine, webhook_reference={BREAK_ENTER_WEBHOOK_TOKEN}"
        )
        
        return activation
    
    def is_break_enter_strategy(self, webhook_id: str = None, strategy_name: str = None) -> bool:
        """Check if this is a Break and Enter strategy activation request."""
        if webhook_id == BREAK_ENTER_WEBHOOK_TOKEN:
            return True
        if strategy_name and strategy_name.lower() in ['break_and_enter', 'break n enter', 'break and enter']:
            return True
        return False
    
    def get_activation_summary(self, user_id: int) -> Dict[str, Any]:
        """Get summary of user's Break and Enter strategy status."""
        access_info = self.check_user_access(user_id)
        
        # Check current activations
        strategy_code_id = self.get_strategy_code_id()
        activations = []
        
        if strategy_code_id:
            activations = self.db.query(ActivatedStrategy).filter(
                ActivatedStrategy.user_id == user_id,
                ActivatedStrategy.strategy_code_id == strategy_code_id,
                ActivatedStrategy.is_active == True
            ).all()
        
        return {
            "strategy_name": "Break and Enter",
            "has_access": access_info["has_access"],
            "access_method": access_info["access_method"],
            "execution_type": "engine",
            "active_activations": len(activations),
            "can_activate": access_info["has_access"] and strategy_code_id is not None,
            "migration_status": "completed" if activations else "ready"
        }