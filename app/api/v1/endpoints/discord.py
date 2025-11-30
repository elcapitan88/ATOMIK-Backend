# app/api/v1/endpoints/discord.py
# Discord OAuth and integration endpoints

import secrets
import logging
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.api.deps import get_current_user, get_db, verify_internal_api_key
from app.models.user import User
from app.models.discord import DiscordLink, PendingDiscordLink
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


# ==================== Pydantic Models ====================

class DiscordLinkResponse(BaseModel):
    """Response for Discord link status."""
    is_linked: bool
    discord_username: Optional[str] = None
    discord_user_id: Optional[str] = None
    linked_at: Optional[datetime] = None


class MagicLinkRequest(BaseModel):
    """Request to create a magic link for Discord-first linking."""
    discord_user_id: str
    discord_username: Optional[str] = None


class MagicLinkResponse(BaseModel):
    """Response with magic link URL."""
    link: str
    expires_at: datetime


class UnlinkResponse(BaseModel):
    """Response for unlinking Discord."""
    success: bool
    message: str


# ==================== OAuth Configuration ====================

DISCORD_API_BASE = "https://discord.com/api/v10"
DISCORD_OAUTH_AUTHORIZE = "https://discord.com/oauth2/authorize"
DISCORD_OAUTH_TOKEN = f"{DISCORD_API_BASE}/oauth2/token"
DISCORD_OAUTH_SCOPES = ["identify"]


def get_discord_oauth_url(state: str, redirect_uri: str) -> str:
    """Generate Discord OAuth authorization URL."""
    params = {
        "client_id": settings.DISCORD_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(DISCORD_OAUTH_SCOPES),
        "state": state,
    }
    return f"{DISCORD_OAUTH_AUTHORIZE}?{urlencode(params)}"


async def exchange_discord_code(code: str, redirect_uri: str) -> dict:
    """Exchange OAuth code for access token and user info."""
    async with httpx.AsyncClient() as client:
        # Exchange code for token
        token_response = await client.post(
            DISCORD_OAUTH_TOKEN,
            data={
                "client_id": settings.DISCORD_CLIENT_ID,
                "client_secret": settings.DISCORD_CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if token_response.status_code != 200:
            logger.error(f"Discord token exchange failed: {token_response.text}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to authenticate with Discord"
            )

        token_data = token_response.json()

        # Get user info
        user_response = await client.get(
            f"{DISCORD_API_BASE}/users/@me",
            headers={"Authorization": f"Bearer {token_data['access_token']}"},
        )

        if user_response.status_code != 200:
            logger.error(f"Discord user fetch failed: {user_response.text}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to get Discord user info"
            )

        user_data = user_response.json()
        return {
            "access_token": token_data.get("access_token"),
            "refresh_token": token_data.get("refresh_token"),
            "expires_in": token_data.get("expires_in"),
            "user": user_data,
        }


# ==================== Endpoints ====================

@router.get("/status", response_model=DiscordLinkResponse)
async def get_discord_link_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get current Discord link status for the authenticated user."""
    link = db.query(DiscordLink).filter(
        DiscordLink.user_id == current_user.id,
        DiscordLink.is_active == True
    ).first()

    if link:
        return DiscordLinkResponse(
            is_linked=True,
            discord_username=link.discord_username,
            discord_user_id=link.discord_user_id,
            linked_at=link.linked_at
        )

    return DiscordLinkResponse(is_linked=False)


class ConnectURLResponse(BaseModel):
    """Response with Discord OAuth URL."""
    auth_url: str


@router.get("/connect-url", response_model=ConnectURLResponse)
async def get_discord_connect_url(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get Discord OAuth URL for connecting account.

    Returns the OAuth URL for the frontend to redirect to.
    """
    # Check if already linked
    existing = db.query(DiscordLink).filter(
        DiscordLink.user_id == current_user.id,
        DiscordLink.is_active == True
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Discord account already linked. Unlink first to connect a different account."
        )

    # Generate state token (includes user ID for verification)
    state = f"{current_user.id}:{secrets.token_urlsafe(32)}"

    # Store state in session/cache (in production, use Redis)
    # For now, we'll encode user_id in state and verify on callback

    redirect_uri = f"{settings.API_BASE_URL}/api/v1/discord/callback"
    auth_url = get_discord_oauth_url(state, redirect_uri)

    return ConnectURLResponse(auth_url=auth_url)


@router.get("/connect")
async def initiate_discord_connect(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Initiate Discord OAuth flow (redirect version).

    Redirects user to Discord to authorize the connection.
    This is an alternative to /connect-url for direct browser navigation.
    """
    # Check if already linked
    existing = db.query(DiscordLink).filter(
        DiscordLink.user_id == current_user.id,
        DiscordLink.is_active == True
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Discord account already linked. Unlink first to connect a different account."
        )

    # Generate state token (includes user ID for verification)
    state = f"{current_user.id}:{secrets.token_urlsafe(32)}"

    # Store state in session/cache (in production, use Redis)
    # For now, we'll encode user_id in state and verify on callback

    redirect_uri = f"{settings.API_BASE_URL}/api/v1/discord/callback"
    auth_url = get_discord_oauth_url(state, redirect_uri)

    return RedirectResponse(url=auth_url)


@router.get("/callback")
async def discord_oauth_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: Session = Depends(get_db)
):
    """
    Handle Discord OAuth callback.

    Completes the link between Discord and Atomik accounts.
    """
    # Parse state to get user_id
    try:
        user_id_str, _ = state.split(":", 1)
        user_id = int(user_id_str)
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid state parameter"
        )

    # Verify user exists
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Exchange code for Discord user info
    redirect_uri = f"{settings.API_BASE_URL}/api/v1/discord/callback"
    discord_data = await exchange_discord_code(code, redirect_uri)
    discord_user = discord_data["user"]

    # Check if this Discord account is already linked to another user
    existing_link = db.query(DiscordLink).filter(
        DiscordLink.discord_user_id == str(discord_user["id"]),
        DiscordLink.is_active == True
    ).first()

    if existing_link and existing_link.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This Discord account is already linked to another Atomik account"
        )

    # Create or update link
    if existing_link:
        # Update existing link
        existing_link.discord_username = discord_user.get("username")
        existing_link.discord_avatar = discord_user.get("avatar")
        existing_link.access_token = discord_data.get("access_token")
        existing_link.refresh_token = discord_data.get("refresh_token")
        existing_link.last_used_at = datetime.utcnow()
    else:
        # Deactivate any old links for this user
        db.query(DiscordLink).filter(
            DiscordLink.user_id == user_id
        ).update({"is_active": False})

        # Create new link
        new_link = DiscordLink(
            user_id=user_id,
            discord_user_id=str(discord_user["id"]),
            discord_username=discord_user.get("username"),
            discord_avatar=discord_user.get("avatar"),
            access_token=discord_data.get("access_token"),
            refresh_token=discord_data.get("refresh_token"),
            token_expires_at=datetime.utcnow() + timedelta(seconds=discord_data.get("expires_in", 604800))
        )
        db.add(new_link)

    db.commit()
    logger.info(f"Discord linked: user_id={user_id}, discord_id={discord_user['id']}")

    # Redirect to frontend success page
    return RedirectResponse(
        url=f"{settings.active_frontend_url}/settings?discord=success"
    )


@router.delete("/unlink", response_model=UnlinkResponse)
async def unlink_discord(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Unlink Discord account from Atomik account."""
    link = db.query(DiscordLink).filter(
        DiscordLink.user_id == current_user.id,
        DiscordLink.is_active == True
    ).first()

    if not link:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No Discord account linked"
        )

    link.is_active = False
    db.commit()

    logger.info(f"Discord unlinked: user_id={current_user.id}")

    return UnlinkResponse(
        success=True,
        message="Discord account unlinked successfully"
    )


# ==================== Magic Link Endpoints (for Discord Bot) ====================

@router.post("/magic-link", response_model=MagicLinkResponse)
async def create_magic_link(
    request: MagicLinkRequest,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_internal_api_key)
):
    """
    Create a magic link for Discord-first account linking.

    Called by the Discord bot when a user wants to link their account.
    Requires internal API key authentication via X-API-Key header.
    """
    # Generate unique token
    token = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(minutes=15)

    # Create pending link
    pending = PendingDiscordLink(
        token=token,
        discord_user_id=request.discord_user_id,
        discord_username=request.discord_username,
        expires_at=expires_at
    )
    db.add(pending)
    db.commit()

    link = f"{settings.active_frontend_url}/connect-discord?token={token}"

    return MagicLinkResponse(link=link, expires_at=expires_at)


@router.get("/magic-link/complete")
async def complete_magic_link(
    token: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Complete the magic link flow.

    Called when user clicks the magic link and is logged in.
    """
    # Find pending link
    pending = db.query(PendingDiscordLink).filter(
        PendingDiscordLink.token == token,
        PendingDiscordLink.is_used == False
    ).first()

    if not pending:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid or expired link"
        )

    if pending.expires_at < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This link has expired"
        )

    # Check if Discord is already linked to another account
    existing = db.query(DiscordLink).filter(
        DiscordLink.discord_user_id == pending.discord_user_id,
        DiscordLink.is_active == True
    ).first()

    if existing and existing.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This Discord account is already linked to another Atomik account"
        )

    # Deactivate any old links for this user
    db.query(DiscordLink).filter(
        DiscordLink.user_id == current_user.id
    ).update({"is_active": False})

    # Create the link
    new_link = DiscordLink(
        user_id=current_user.id,
        discord_user_id=pending.discord_user_id,
        discord_username=pending.discord_username
    )
    db.add(new_link)

    # Mark pending link as used
    pending.is_used = True
    pending.used_by_user_id = current_user.id
    pending.used_at = datetime.utcnow()

    db.commit()

    logger.info(f"Magic link completed: user_id={current_user.id}, discord_id={pending.discord_user_id}")

    return RedirectResponse(
        url=f"{settings.active_frontend_url}/settings?discord=success"
    )


# ==================== Internal Bot Endpoints ====================

@router.get("/internal/user-by-discord/{discord_user_id}")
async def get_user_by_discord_id(
    discord_user_id: str,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_internal_api_key)
):
    """
    Get Atomik user ID by Discord user ID.

    Internal endpoint for Discord bot to resolve users.
    Requires internal API key authentication via X-API-Key header.
    """
    link = db.query(DiscordLink).filter(
        DiscordLink.discord_user_id == discord_user_id,
        DiscordLink.is_active == True
    ).first()

    if not link:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Discord account not linked"
        )

    # Update last used
    link.last_used_at = datetime.utcnow()
    db.commit()

    return {
        "user_id": link.user_id,
        "discord_username": link.discord_username,
        "linked_at": link.linked_at
    }
