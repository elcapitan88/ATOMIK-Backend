"""API dependencies."""

from fastapi import Depends, HTTPException, status, Header
from fastapi.security import HTTPBearer
from sqlalchemy.orm import Session
from typing import Generator, Optional
import logging

from app.db.base import get_db
from app.core.security import get_current_user, decode_access_token
from app.core.config import settings
from app.models.user import User

logger = logging.getLogger(__name__)
security = HTTPBearer(auto_error=False)

# Re-export for convenience
__all__ = ["get_db", "get_current_active_user", "get_current_user_optional", "verify_internal_api_key"]


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
        
        subject = payload.get("sub")
        if not subject:
            return None
        
        # Get user from database - subject could be email or user_id
        user = None
        try:
            # First try as user ID (integer)
            user_id = int(subject)
            user = db.query(User).filter(User.id == user_id).first()
        except ValueError:
            # If not an integer, treat as email
            user = db.query(User).filter(User.email == subject).first()
        
        return user
        
    except Exception as e:
        logger.debug(f"Optional auth failed: {str(e)}")
        return None


def verify_internal_api_key(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key")
) -> bool:
    """
    Verify internal API key for service-to-service authentication.
    Used by Discord bot and other internal services.
    """
    if not settings.INTERNAL_API_KEY:
        logger.warning("INTERNAL_API_KEY not configured - internal endpoints are unprotected!")
        return True  # Allow in development if not configured

    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key"
        )

    if x_api_key != settings.INTERNAL_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key"
        )

    return True