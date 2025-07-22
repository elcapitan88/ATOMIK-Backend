# app/api/v1/endpoints/creators.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
import logging

from app.api import deps
from app.core.security import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.creator_profile import CreatorProfile
from app.models.creator_earnings import CreatorEarnings
from app.schemas.creator import (
    CreatorProfileCreate,
    CreatorProfileUpdate,
    CreatorProfileResponse,
    CreatorEarningsResponse,
    CreatorAnalyticsResponse,
    StripeConnectSetupRequest,
    StripeConnectSetupResponse
)
from app.services.stripe_connect_service import StripeConnectService
from app.services.creator_service import CreatorService

logger = logging.getLogger(__name__)
router = APIRouter()

stripe_connect_service = StripeConnectService()
creator_service = CreatorService()


@router.post("/become-creator", response_model=CreatorProfileResponse)
async def become_creator(
    creator_data: CreatorProfileCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Creator onboarding - Convert user to creator.
    """
    try:
        # Check if user already has a creator profile
        existing_profile = db.query(CreatorProfile).filter(
            CreatorProfile.user_id == current_user.id
        ).first()
        
        if existing_profile:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User already has a creator profile"
            )
        
        # Create creator profile
        creator_profile = await creator_service.create_creator_profile(
            db=db,
            user_id=current_user.id,
            creator_data=creator_data
        )
        
        logger.info(f"User {current_user.id} became a creator with profile {creator_profile.id}")
        return creator_profile
        
    except Exception as e:
        logger.error(f"Error creating creator profile: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create creator profile"
        )


@router.get("/profile", response_model=CreatorProfileResponse)
async def get_creator_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get current user's creator profile.
    """
    creator_profile = db.query(CreatorProfile).filter(
        CreatorProfile.user_id == current_user.id
    ).first()
    
    if not creator_profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Creator profile not found"
        )
    
    return creator_profile


@router.put("/profile", response_model=CreatorProfileResponse)
async def update_creator_profile(
    profile_update: CreatorProfileUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Update creator profile information.
    """
    creator_profile = db.query(CreatorProfile).filter(
        CreatorProfile.user_id == current_user.id
    ).first()
    
    if not creator_profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Creator profile not found"
        )
    
    try:
        updated_profile = await creator_service.update_creator_profile(
            db=db,
            creator_profile=creator_profile,
            update_data=profile_update
        )
        
        logger.info(f"Creator profile {creator_profile.id} updated")
        return updated_profile
        
    except Exception as e:
        logger.error(f"Error updating creator profile: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update creator profile"
        )


@router.post("/setup-stripe-connect", response_model=StripeConnectSetupResponse)
async def setup_stripe_connect(
    setup_request: StripeConnectSetupRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Setup Stripe Connect account for creator.
    """
    creator_profile = db.query(CreatorProfile).filter(
        CreatorProfile.user_id == current_user.id
    ).first()
    
    if not creator_profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Creator profile not found"
        )
    
    try:
        # Create or get existing Stripe Connect account
        if not creator_profile.stripe_connect_account_id:
            account_id = await stripe_connect_service.create_express_account(
                creator_profile=creator_profile
            )
            creator_profile.stripe_connect_account_id = account_id
            db.commit()
        
        # Create account link for onboarding with prefilled user data
        account_link = await stripe_connect_service.create_account_link(
            account_id=creator_profile.stripe_connect_account_id,
            refresh_url=setup_request.refresh_url,
            return_url=setup_request.return_url,
            creator_profile=creator_profile
        )
        
        logger.info(f"Stripe Connect setup initiated for creator {creator_profile.id}")
        return StripeConnectSetupResponse(
            account_link_url=account_link["url"],
            account_id=creator_profile.stripe_connect_account_id
        )
        
    except Exception as e:
        logger.error(f"Error setting up Stripe Connect: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to setup Stripe Connect"
        )


@router.get("/earnings", response_model=List[CreatorEarningsResponse])
async def get_creator_earnings(
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get creator earnings history.
    """
    creator_profile = db.query(CreatorProfile).filter(
        CreatorProfile.user_id == current_user.id
    ).first()
    
    if not creator_profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Creator profile not found"
        )
    
    earnings = db.query(CreatorEarnings).filter(
        CreatorEarnings.creator_id == creator_profile.id
    ).order_by(CreatorEarnings.created_at.desc()).offset(offset).limit(limit).all()
    
    return earnings


@router.get("/analytics", response_model=CreatorAnalyticsResponse)
async def get_creator_analytics(
    period: str = "30d",  # 7d, 30d, 90d, 1y
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get creator analytics dashboard data.
    """
    creator_profile = db.query(CreatorProfile).filter(
        CreatorProfile.user_id == current_user.id
    ).first()
    
    if not creator_profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Creator profile not found"
        )
    
    try:
        analytics = await creator_service.get_creator_analytics(
            db=db,
            creator_profile=creator_profile,
            period=period
        )
        
        return analytics
        
    except Exception as e:
        logger.error(f"Error fetching creator analytics: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch analytics"
        )


@router.get("/tier-progress")
async def get_tier_progress(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get creator's current tier and progress to next tier.
    """
    creator_profile = db.query(CreatorProfile).filter(
        CreatorProfile.user_id == current_user.id
    ).first()
    
    if not creator_profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Creator profile not found"
        )
    
    try:
        tier_info = await creator_service.get_tier_progress(
            creator_profile=creator_profile
        )
        
        return tier_info
        
    except Exception as e:
        logger.error(f"Error fetching tier progress: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch tier progress"
        )


@router.post("/create-account-session")
async def create_account_session(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Create an Account Session for Stripe Embedded Components.
    This enables in-app Stripe onboarding without redirects.
    """
    creator_profile = db.query(CreatorProfile).filter(
        CreatorProfile.user_id == current_user.id
    ).first()
    
    if not creator_profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Creator profile not found"
        )
    
    try:
        # Create or get existing Stripe Connect account
        if not creator_profile.stripe_connect_account_id:
            account_id = await stripe_connect_service.create_express_account(
                creator_profile=creator_profile
            )
            creator_profile.stripe_connect_account_id = account_id
            db.commit()
        
        # Create account session for embedded components
        account_session = await stripe_connect_service.create_account_session(
            account_id=creator_profile.stripe_connect_account_id,
            creator_profile=creator_profile
        )
        
        logger.info(f"Account session created for creator {creator_profile.id}")
        return account_session
        
    except Exception as e:
        logger.error(f"Error creating account session: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create account session"
        )


@router.get("/stripe-status")
async def get_stripe_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Check Stripe Connect account status and onboarding completion.
    """
    creator_profile = db.query(CreatorProfile).filter(
        CreatorProfile.user_id == current_user.id
    ).first()
    
    if not creator_profile or not creator_profile.stripe_connect_account_id:
        return {
            "connected": False,
            "onboarding_complete": False,
            "account_id": None
        }
    
    try:
        # Check account status with Stripe
        import stripe
        account = stripe.Account.retrieve(creator_profile.stripe_connect_account_id)
        
        return {
            "connected": True,
            "onboarding_complete": account.details_submitted and account.charges_enabled,
            "account_id": creator_profile.stripe_connect_account_id,
            "charges_enabled": account.charges_enabled,
            "details_submitted": account.details_submitted,
            "requirements": account.requirements
        }
        
    except Exception as e:
        logger.error(f"Error checking Stripe status: {str(e)}")
        return {
            "connected": False,
            "onboarding_complete": False,
            "account_id": creator_profile.stripe_connect_account_id,
            "error": str(e)
        }


# Add alias endpoint for frontend compatibility
@router.post("/stripe/connect")
async def stripe_connect_alias(
    request_data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Alias endpoint for Stripe Connect setup (frontend compatibility).
    """
    from app.schemas.creator import StripeConnectSetupRequest
    
    # Convert request data to proper schema
    setup_request = StripeConnectSetupRequest(
        business_type=request_data.get('businessType', 'individual'),
        country=request_data.get('country', 'US'),
        refresh_url=request_data.get('refreshUrl', f"{request_data.get('baseUrl', '')}/creator-hub?stripe=refresh"),
        return_url=request_data.get('returnUrl', f"{request_data.get('baseUrl', '')}/creator-hub?stripe=success")
    )
    
    # Call the main setup endpoint
    result = await setup_stripe_connect(setup_request, db, current_user)
    
    # Return in format expected by frontend
    return {
        "onboardingUrl": result.account_link_url,
        "accountId": result.account_id,
        "success": True
    }