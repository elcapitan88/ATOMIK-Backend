"""
Service to properly set up monetization records for strategies that have purchases
but are missing monetization configuration.
"""

from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime
import logging

from app.models.strategy_monetization import StrategyMonetization
from app.models.strategy_purchases import StrategyPurchase
from app.models.webhook import Webhook
from app.models.user import User

logger = logging.getLogger(__name__)

class MonetizationSetupService:
    """Service for setting up strategy monetization records"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def create_missing_monetization_records(self) -> int:
        """
        Create monetization records for strategies that have purchases but no monetization setup.
        Returns the number of records created.
        """
        try:
            # Find strategies with purchases but no monetization records
            query = text("""
                SELECT DISTINCT sp.webhook_id, w.name, w.user_id as creator_id, 
                       COUNT(sp.id) as purchase_count,
                       SUM(CASE WHEN sp.stripe_subscription_id IS NOT NULL THEN 1 ELSE 0 END) as active_subscriptions
                FROM strategy_purchases sp
                LEFT JOIN webhooks w ON sp.webhook_id = w.id
                LEFT JOIN strategy_monetization sm ON sm.webhook_id = sp.webhook_id
                WHERE sm.id IS NULL  -- No monetization record exists
                AND w.id IS NOT NULL  -- Webhook exists
                AND w.user_id IS NOT NULL  -- Has a creator
                GROUP BY sp.webhook_id, w.name, w.user_id
                ORDER BY purchase_count DESC
            """)
            
            result = self.db.execute(query)
            strategies_to_fix = result.fetchall()
            
            records_created = 0
            
            for strategy in strategies_to_fix:
                webhook_id = strategy[0]
                name = strategy[1]
                creator_id = strategy[2]
                purchase_count = strategy[3]
                active_subscriptions = strategy[4]
                
                logger.info(f"Creating monetization record for strategy '{name}' (webhook {webhook_id})")
                
                # Create the monetization record
                monetization = StrategyMonetization(
                    webhook_id=webhook_id,
                    stripe_product_id=f"prod_strategy_{webhook_id}",  # Placeholder, should be updated with real Stripe product ID
                    creator_user_id=creator_id,
                    is_active=True,
                    total_subscribers=active_subscriptions,
                    estimated_monthly_revenue=0.00,  # Will be calculated later
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                
                self.db.add(monetization)
                records_created += 1
                
                logger.info(f"Created monetization record for webhook {webhook_id} with {active_subscriptions} subscribers")
            
            if records_created > 0:
                self.db.commit()
                logger.info(f"Successfully created {records_created} monetization records")
            
            return records_created
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error creating monetization records: {str(e)}")
            raise
    
    def ensure_monetization_for_webhook(self, webhook_id: int) -> bool:
        """
        Ensure a specific webhook has a monetization record.
        Returns True if record exists or was created, False otherwise.
        """
        try:
            # Check if monetization record already exists
            existing = self.db.query(StrategyMonetization).filter(
                StrategyMonetization.webhook_id == webhook_id
            ).first()
            
            if existing:
                return True
            
            # Get webhook and verify it exists
            webhook = self.db.query(Webhook).filter(Webhook.id == webhook_id).first()
            if not webhook or not webhook.user_id:
                logger.error(f"Webhook {webhook_id} not found or has no owner")
                return False
            
            # Count existing purchases for this webhook
            purchase_count = self.db.query(StrategyPurchase).filter(
                StrategyPurchase.webhook_id == webhook_id
            ).count()
            
            active_subscriptions = self.db.query(StrategyPurchase).filter(
                StrategyPurchase.webhook_id == webhook_id,
                StrategyPurchase.stripe_subscription_id.isnot(None)
            ).count()
            
            # Create monetization record
            monetization = StrategyMonetization(
                webhook_id=webhook_id,
                stripe_product_id=f"prod_strategy_{webhook_id}",
                creator_user_id=webhook.user_id,
                is_active=True,
                total_subscribers=active_subscriptions,
                estimated_monthly_revenue=0.00,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            
            self.db.add(monetization)
            self.db.commit()
            
            logger.info(f"Created monetization record for webhook {webhook_id} ({webhook.name})")
            return True
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error ensuring monetization for webhook {webhook_id}: {str(e)}")
            return False