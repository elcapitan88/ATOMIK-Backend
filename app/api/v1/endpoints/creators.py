# app/api/v1/endpoints/creators.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
import logging
from datetime import datetime

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


@router.get("/onboarding-status")
async def get_onboarding_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get current user's onboarding status and progress.
    """
    return {
        "onboarding_step": current_user.onboarding_step,
        "onboarding_data": current_user.onboarding_data,
        "is_creator": current_user.creator_profile_id is not None,
        "creator_profile_id": str(current_user.creator_profile_id) if current_user.creator_profile_id else None
    }


@router.post("/update-onboarding-step")
async def update_onboarding_step(
    request_data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Update user's onboarding step and data.
    """
    try:
        step = request_data.get("step")
        data = request_data.get("data")
        
        # Re-query the user to ensure it's attached to this session
        user = db.query(User).filter(User.id == current_user.id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        logger.info(f"[DEBUG] Updating onboarding for user {user.id}")
        logger.info(f"[DEBUG] Current values - step: {user.onboarding_step}, data: {user.onboarding_data}")
        logger.info(f"[DEBUG] New values - step: {step}, data: {data}")
        
        user.onboarding_step = step
        user.onboarding_data = data
        
        # Force flush to ensure changes are written
        db.flush()
        db.commit()
        
        # Re-query instead of refresh to ensure we get the updated values
        user = db.query(User).filter(User.id == user.id).first()
        
        logger.info(f"[DEBUG] After update - step: {user.onboarding_step}, data: {user.onboarding_data}")
        logger.info(f"Updated onboarding step to {step} for user {user.id}")
        
        return {
            "success": True,
            "onboarding_step": user.onboarding_step,
            "onboarding_data": user.onboarding_data
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating onboarding step: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update onboarding step"
        )


@router.get("/debug-onboarding-test")
async def debug_onboarding_test(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Debug endpoint to test onboarding step updates
    """
    try:
        # Re-query the user to ensure it's attached to this session
        user = db.query(User).filter(User.id == current_user.id).first()
        if not user:
            return {"error": "User not found in database"}
        
        # Get current state
        current_step = user.onboarding_step
        current_data = user.onboarding_data
        
        logger.info(f"[DEBUG TEST] Testing onboarding update for user {user.id}")
        logger.info(f"[DEBUG TEST] Current values - step: {current_step}, data: {current_data}")
        
        # Try to update to step 2
        test_step = 2
        test_data = {"test": "debug_endpoint", "timestamp": str(datetime.utcnow())}
        
        user.onboarding_step = test_step
        user.onboarding_data = test_data
        
        # Force flush and commit
        db.flush()
        db.commit()
        
        # Re-query instead of refresh to ensure we get the updated values
        user = db.query(User).filter(User.id == user.id).first()
        
        # Check if it actually updated
        logger.info(f"[DEBUG TEST] After update - step: {user.onboarding_step}, data: {user.onboarding_data}")
        
        # Query the database directly to double-check
        from sqlalchemy import text
        result = db.execute(text("""
            SELECT onboarding_step, onboarding_data 
            FROM users 
            WHERE id = :user_id
        """), {"user_id": current_user.id})
        
        row = result.fetchone()
        db_step = row[0] if row else None
        db_data = row[1] if row else None
        
        logger.info(f"[DEBUG TEST] Direct DB query - step: {db_step}, data: {db_data}")
        
        success = db_step == test_step
        
        return {
            "debug_test": True,
            "user_id": current_user.id,
            "before": {
                "step": current_step,
                "data": current_data
            },
            "attempted_update": {
                "step": test_step,
                "data": test_data
            },
            "after_orm": {
                "step": current_user.onboarding_step,
                "data": current_user.onboarding_data
            },
            "after_direct_query": {
                "step": db_step,
                "data": db_data
            },
            "success": success,
            "message": "Update successful!" if success else "Update failed - database not persisting changes"
        }
        
    except Exception as e:
        logger.error(f"[DEBUG TEST] Error: {str(e)}")
        import traceback
        logger.error(f"[DEBUG TEST] Traceback: {traceback.format_exc()}")
        return {
            "error": str(e),
            "traceback": traceback.format_exc()
        }


@router.post("/complete-onboarding")
async def complete_onboarding(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Mark onboarding as complete and clear progress data.
    """
    try:
        current_user.onboarding_step = None
        current_user.onboarding_data = None
        db.commit()
        
        logger.info(f"Completed onboarding for user {current_user.id}")
        
        return {"success": True, "message": "Onboarding completed successfully"}
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error completing onboarding: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to complete onboarding"
        )


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
        return CreatorProfileResponse.from_orm(creator_profile)
        
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
    
    return CreatorProfileResponse.from_orm(creator_profile)


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
    try:
        # Use database row-level locking to prevent race condition
        creator_profile = db.query(CreatorProfile).filter(
            CreatorProfile.user_id == current_user.id
        ).with_for_update().first()
        
        if not creator_profile:
            # Auto-create a basic creator profile if it doesn't exist
            # This handles cases where onboarding_step was set manually
            logger.info(f"Creator profile not found for user {current_user.id}, creating one...")
            from app.services.creator_service import CreatorService
            from app.schemas.creator import CreatorProfileCreate
            
            creator_service = CreatorService()
            creator_data = CreatorProfileCreate(
                bio="Trading enthusiast",
                trading_experience="intermediate"
            )
            
            creator_profile = await creator_service.create_creator_profile(
                db=db,
                user_id=current_user.id,
                creator_data=creator_data
            )
            logger.info(f"Auto-created creator profile {creator_profile.id} for user {current_user.id}")
        
        # Create or get existing Stripe Connect account (with transaction safety)
        if not creator_profile.stripe_connect_account_id:
            logger.info(f"Creating new Stripe account for creator {creator_profile.id}")
            account_id = await stripe_connect_service.create_express_account(
                creator_profile=creator_profile
            )
            creator_profile.stripe_connect_account_id = account_id
            db.commit()
            logger.info(f"Stripe account {account_id} saved for creator {creator_profile.id}")
        else:
            # Check if existing account has correct requirement_collection setting
            try:
                import stripe
                existing_account = stripe.Account.retrieve(creator_profile.stripe_connect_account_id)
                requirement_collection = existing_account.controller.requirement_collection
                
                if requirement_collection != "application":
                    logger.info(f"Existing account has requirement_collection={requirement_collection}, need to recreate for embedded components")
                    # Delete old account and create new one
                    try:
                        stripe.Account.delete(creator_profile.stripe_connect_account_id)
                        logger.info(f"Deleted old Stripe account {creator_profile.stripe_connect_account_id}")
                    except Exception as delete_error:
                        logger.warning(f"Could not delete old account: {delete_error}")
                    
                    # Create new account with correct settings
                    account_id = await stripe_connect_service.create_express_account(
                        creator_profile=creator_profile
                    )
                    creator_profile.stripe_connect_account_id = account_id
                    db.commit()
                    logger.info(f"Created new Stripe account {account_id} with embedded support")
                else:
                    logger.info(f"Using existing Stripe account {creator_profile.stripe_connect_account_id} for creator {creator_profile.id}")
                    
            except Exception as check_error:
                logger.warning(f"Could not check existing account settings: {check_error}")
                logger.info(f"Using existing Stripe account {creator_profile.stripe_connect_account_id} for creator {creator_profile.id}")
        
        # Create account session for embedded components
        account_session = await stripe_connect_service.create_account_session(
            account_id=creator_profile.stripe_connect_account_id,
            creator_profile=creator_profile
        )
        
        logger.info(f"Account session created for creator {creator_profile.id}")
        return account_session
        
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        logger.error(f"Error creating account session: {str(e)}")
        db.rollback()  # Rollback on any error
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create account session"
        )


@router.post("/cleanup-duplicate-accounts")
async def cleanup_duplicate_accounts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Clean up duplicate Stripe accounts for a creator.
    This should only be called in development/testing.
    """
    try:
        creator_profile = db.query(CreatorProfile).filter(
            CreatorProfile.user_id == current_user.id
        ).first()
        
        if not creator_profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Creator profile not found"
            )
        
        # If no Stripe account is set, we can't clean up
        if not creator_profile.stripe_connect_account_id:
            return {"message": "No Stripe account to clean up"}
        
        # Use the first account that was created
        account_to_keep = creator_profile.stripe_connect_account_id
        
        logger.info(f"Keeping Stripe account {account_to_keep} for creator {creator_profile.id}")
        logger.warning("Note: Any duplicate accounts must be manually deleted from Stripe dashboard")
        
        return {
            "message": "Cleanup completed",
            "stripe_account_id": account_to_keep,
            "note": "Duplicate accounts (if any) should be manually removed from Stripe dashboard"
        }
        
    except Exception as e:
        logger.error(f"Error during cleanup: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to cleanup duplicate accounts"
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