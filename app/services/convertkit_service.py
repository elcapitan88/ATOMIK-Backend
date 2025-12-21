"""
ConvertKit API Service for email marketing automation.
Used for lead capture and email sequence management.
"""
import httpx
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


class ConvertKitService:
    """Service to interact with ConvertKit API for email marketing"""

    def __init__(self):
        self.api_key = os.getenv("CONVERTKIT_API_KEY")
        self.api_secret = os.getenv("CONVERTKIT_API_SECRET")
        self.base_url = "https://api.convertkit.com/v4"
        self.sequence_id = os.getenv("CONVERTKIT_BLUEPRINT_SEQUENCE_ID", "2594476")

        if not self.api_key:
            logger.warning("CONVERTKIT_API_KEY environment variable not set")

    async def add_subscriber_to_sequence(
        self,
        email: str,
        first_name: Optional[str] = None,
        sequence_id: Optional[str] = None,
        tags: Optional[list] = None
    ) -> dict:
        """
        Add a subscriber directly to a sequence in ConvertKit.

        Args:
            email: Subscriber's email address
            first_name: Subscriber's first name (optional)
            sequence_id: The sequence ID to add them to (defaults to blueprint sequence)
            tags: List of tag names to apply (optional)

        Returns:
            dict: Response with subscriber info or error
        """
        if not self.api_key:
            logger.error("ConvertKit API key not configured")
            return {"success": False, "error": "ConvertKit not configured"}

        target_sequence = sequence_id or self.sequence_id

        # Build subscriber data
        subscriber_data = {
            "email_address": email
        }

        if first_name:
            subscriber_data["first_name"] = first_name

        payload = {
            "subscriber": subscriber_data
        }

        async with httpx.AsyncClient() as client:
            try:
                # Add subscriber to sequence using v4 API
                response = await client.post(
                    f"{self.base_url}/sequences/{target_sequence}/subscribers",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    }
                )

                if response.status_code in [200, 201]:
                    data = response.json()
                    logger.info(f"Successfully added {email} to sequence {target_sequence}")
                    return {
                        "success": True,
                        "subscriber": data.get("subscriber", {}),
                        "message": "Subscriber added to sequence"
                    }
                elif response.status_code == 422:
                    # Subscriber might already exist - this is okay
                    logger.info(f"Subscriber {email} may already exist in sequence")
                    return {
                        "success": True,
                        "message": "Subscriber processed (may already exist)"
                    }
                else:
                    logger.error(f"ConvertKit API error: {response.status_code} - {response.text}")
                    return {
                        "success": False,
                        "error": f"API error: {response.status_code}"
                    }

            except httpx.HTTPStatusError as e:
                logger.error(f"ConvertKit HTTP error: {e.response.text}")
                return {
                    "success": False,
                    "error": f"HTTP error: {str(e)}"
                }
            except Exception as e:
                logger.error(f"Error adding subscriber to ConvertKit: {str(e)}")
                return {
                    "success": False,
                    "error": str(e)
                }

    async def add_subscriber(
        self,
        email: str,
        first_name: Optional[str] = None
    ) -> dict:
        """
        Add a subscriber to ConvertKit (without sequence).

        Args:
            email: Subscriber's email address
            first_name: Subscriber's first name (optional)

        Returns:
            dict: Response with subscriber info or error
        """
        if not self.api_key:
            logger.error("ConvertKit API key not configured")
            return {"success": False, "error": "ConvertKit not configured"}

        subscriber_data = {
            "email_address": email
        }

        if first_name:
            subscriber_data["first_name"] = first_name

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{self.base_url}/subscribers",
                    json=subscriber_data,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    }
                )

                if response.status_code in [200, 201]:
                    data = response.json()
                    logger.info(f"Successfully added subscriber {email}")
                    return {
                        "success": True,
                        "subscriber": data.get("subscriber", {}),
                        "message": "Subscriber added successfully"
                    }
                else:
                    logger.error(f"ConvertKit API error: {response.status_code} - {response.text}")
                    return {
                        "success": False,
                        "error": f"API error: {response.status_code}"
                    }

            except Exception as e:
                logger.error(f"Error adding subscriber to ConvertKit: {str(e)}")
                return {
                    "success": False,
                    "error": str(e)
                }

    async def get_subscriber(self, email: str) -> dict:
        """
        Check if a subscriber exists in ConvertKit.

        Args:
            email: Email address to look up

        Returns:
            dict: Subscriber info if found
        """
        if not self.api_key:
            return {"success": False, "error": "ConvertKit not configured"}

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    f"{self.base_url}/subscribers",
                    params={"email_address": email},
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    }
                )

                if response.status_code == 200:
                    data = response.json()
                    subscribers = data.get("subscribers", [])
                    if subscribers:
                        return {
                            "success": True,
                            "exists": True,
                            "subscriber": subscribers[0]
                        }
                    return {
                        "success": True,
                        "exists": False
                    }
                else:
                    return {
                        "success": False,
                        "error": f"API error: {response.status_code}"
                    }

            except Exception as e:
                logger.error(f"Error checking subscriber in ConvertKit: {str(e)}")
                return {
                    "success": False,
                    "error": str(e)
                }


# Singleton instance
convertkit_service = ConvertKitService()
