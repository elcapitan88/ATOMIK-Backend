"""API dependencies."""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer
from sqlalchemy.orm import Session
from typing import Generator, Optional
import logging

from app.db.base import get_db
from app.core.security import get_current_user, decode_access_token
from app.models.user import User

logger = logging.getLogger(__name__)
security = HTTPBearer(auto_error=False)

# Re-export for convenience
__all__ = ["get_db", "get_current_active_user", "get_current_user_optional"]


def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Get current active user."""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user"
        )
    return current_user


def get_current_user_optional(
    db: Session = Depends(get_db),
    token: Optional[str] = Depends(security)
) -> Optional[User]:
    """
    Get current user from token, but don't require authentication.
    Returns None if no token or invalid token.
    """
    if not token:
        return None
    
    try:
        # Extract token from Bearer scheme
        if hasattr(token, 'credentials'):
            token_str = token.credentials
        else:
            token_str = str(token)
        
        # Decode token
        payload = decode_access_token(token_str)
        if not payload:
            return None
        
        user_id = payload.get("sub")
        if not user_id:
            return None
        
        # Get user from database
        user = db.query(User).filter(User.id == int(user_id)).first()
        return user
        
    except Exception as e:
        logger.debug(f"Optional auth failed: {str(e)}")
        return None