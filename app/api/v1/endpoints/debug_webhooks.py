"""
Temporary debug endpoint to check webhook ownership
REMOVE THIS FILE AFTER DEBUGGING
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Dict, Any

from app.db.session import get_db
from app.core.security import get_current_user
from app.models.user import User

router = APIRouter()

@router.get("/debug/webhook-owners", response_model=Dict[str, Any])
async def get_webhook_owners(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Debug endpoint to check webhook ownership
    Only accessible to authenticated users
    """
    
    try:
        # Query webhook information
        webhook_query = text("""
        SELECT 
            w.id as webhook_id,
            w.name as webhook_name,
            w.token as webhook_token,
            w.user_id,
            u.username,
            u.email,
            u.full_name,
            w.created_at,
            COUNT(DISTINCT s.id) as strategy_count
        FROM webhooks w
        JOIN users u ON w.user_id = u.id
        LEFT JOIN activated_strategies s ON s.webhook_id = w.token AND s.is_active = true
        WHERE w.id IN (120, 129, 130)
        GROUP BY w.id, w.name, w.token, w.user_id, u.username, u.email, u.full_name, w.created_at
        ORDER BY w.id
        """)
        
        webhooks = db.execute(webhook_query).fetchall()
        
        # Query strategy details
        strategy_query = text("""
        SELECT 
            w.id as webhook_id,
            s.id as strategy_id,
            s.ticker,
            s.quantity,
            s.is_active,
            s.account_id,
            ba.broker_id,
            ba.is_active as account_active
        FROM webhooks w
        LEFT JOIN activated_strategies s ON s.webhook_id = w.token
        LEFT JOIN broker_accounts ba ON s.account_id = ba.account_id
        WHERE w.id IN (120, 129, 130)
        ORDER BY w.id, s.id
        """)
        
        strategies = db.execute(strategy_query).fetchall()
        
        # Format results
        result = {
            "webhooks": [],
            "current_user": {
                "id": current_user.id,
                "username": current_user.username,
                "email": current_user.email
            }
        }
        
        for w in webhooks:
            webhook_data = {
                "id": w.webhook_id,
                "name": w.webhook_name,
                "token": w.webhook_token,
                "owner": {
                    "user_id": w.user_id,
                    "username": w.username,
                    "email": w.email,
                    "full_name": w.full_name,
                    "is_you": w.user_id == current_user.id
                },
                "created_at": str(w.created_at),
                "active_strategies": w.strategy_count,
                "strategies": []
            }
            
            # Add strategy details
            for s in strategies:
                if s.webhook_id == w.webhook_id and s.strategy_id:
                    webhook_data["strategies"].append({
                        "id": s.strategy_id,
                        "ticker": s.ticker,
                        "quantity": s.quantity,
                        "is_active": s.is_active,
                        "account_id": s.account_id,
                        "broker_id": s.broker_id,
                        "account_active": s.account_active
                    })
            
            result["webhooks"].append(webhook_data)
        
        # Add summary
        result["summary"] = {
            "webhook_120": "No active strategies - this is why it's not working" 
                          if any(w["id"] == 120 and w["active_strategies"] == 0 for w in result["webhooks"])
                          else "Has active strategies",
            "webhook_129": next((f"Owned by {w['owner']['username']} with {w['active_strategies']} strategies" 
                               for w in result["webhooks"] if w["id"] == 129), "Not found"),
            "webhook_130": next((f"Owned by {w['owner']['username']} with {w['active_strategies']} strategies" 
                               for w in result["webhooks"] if w["id"] == 130), "Not found")
        }
        
        return result
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching webhook information: {str(e)}"
        )