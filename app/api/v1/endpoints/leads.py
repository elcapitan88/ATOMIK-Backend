"""
Lead capture endpoints for marketing funnels.
Handles email collection for lead magnets and marketing sequences.
"""
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, EmailStr
from typing import Optional
import logging

from app.services.convertkit_service import convertkit_service

logger = logging.getLogger(__name__)

router = APIRouter()


class BlueprintLeadRequest(BaseModel):
    """Request model for blueprint lead magnet signup"""
    email: EmailStr
    first_name: Optional[str] = None
    utm_source: Optional[str] = None
    utm_medium: Optional[str] = None
    utm_campaign: Optional[str] = None


class LeadResponse(BaseModel):
    """Response model for lead capture"""
    success: bool
    message: str


@router.post("/blueprint", response_model=LeadResponse)
async def capture_blueprint_lead(
    lead_data: BlueprintLeadRequest,
    background_tasks: BackgroundTasks
):
    """
    Capture a lead for the Strategy Automation Blueprint lead magnet.

    This endpoint:
    1. Validates the email
    2. Adds the subscriber to ConvertKit
    3. Triggers the 7-email nurture sequence

    No authentication required - this is a public endpoint.
    """
    try:
        logger.info(f"Capturing blueprint lead: {lead_data.email}")

        # Add subscriber to ConvertKit sequence
        result = await convertkit_service.add_subscriber_to_sequence(
            email=lead_data.email,
            first_name=lead_data.first_name
        )

        if result.get("success"):
            logger.info(f"Successfully captured lead: {lead_data.email}")
            return LeadResponse(
                success=True,
                message="Success! Check your email for the blueprint."
            )
        else:
            # Log the error but still return success to user
            # (they might already be subscribed)
            logger.warning(f"ConvertKit issue for {lead_data.email}: {result.get('error')}")
            return LeadResponse(
                success=True,
                message="Success! Check your email for the blueprint."
            )

    except Exception as e:
        logger.error(f"Error capturing lead {lead_data.email}: {str(e)}")
        # Don't expose internal errors to users
        raise HTTPException(
            status_code=500,
            detail="Something went wrong. Please try again."
        )


@router.post("/creator-playbook", response_model=LeadResponse)
async def capture_creator_lead(
    lead_data: BlueprintLeadRequest,
    background_tasks: BackgroundTasks
):
    """
    Capture a lead for the Creator Playbook lead magnet.
    (Future use - separate sequence for creator-focused leads)
    """
    # For now, use the same sequence
    # Later we can create a separate sequence for creator leads
    return await capture_blueprint_lead(lead_data, background_tasks)


@router.get("/health")
async def leads_health():
    """Health check for leads endpoint"""
    return {"status": "healthy", "service": "leads"}
