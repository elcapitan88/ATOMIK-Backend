#!/usr/bin/env python3
"""
Automatically create webhooks for existing creators who already have Stripe Connect.
Run this ONCE after deploying the webhook creation code.

This script:
1. Finds all creators with stripe_connect_account_id but no stripe_webhook_id
2. Creates a webhook endpoint on each creator's Stripe Connect account
3. Stores the webhook ID and secret in the database

Usage:
    cd fastapi_backend
    python scripts/create_webhooks_for_existing_creators.py
"""
import asyncio
import sys
import os
from pathlib import Path
from datetime import datetime

# Add parent directory to path so we can import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

# Set database URL from environment or use default
if 'DATABASE_URL' not in os.environ:
    print("WARNING: DATABASE_URL not set in environment")
    print("Please set it before running this script:")
    print('  export DATABASE_URL="postgresql://..."')
    print('or provide it via command line')
    sys.exit(1)

from app.db.session import SessionLocal
from app.models.creator_profile import CreatorProfile
from app.services.stripe_connect_service import StripeConnectService
from app.core.config import settings
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def create_webhooks_for_existing_creators():
    """Create webhooks for all existing creators who need them."""
    db = SessionLocal()
    stripe_service = StripeConnectService()

    try:
        # Find creators with Stripe Connect but no webhook
        creators = db.query(CreatorProfile).filter(
            CreatorProfile.stripe_connect_account_id.isnot(None),
            CreatorProfile.stripe_webhook_id.is_(None)
        ).all()

        logger.info("=" * 70)
        logger.info("CREATING WEBHOOKS FOR EXISTING CREATORS")
        logger.info("=" * 70)
        logger.info(f"Found {len(creators)} creators needing webhooks\n")

        if len(creators) == 0:
            logger.info("No creators need webhooks - all are already configured!")
            return

        success_count = 0
        fail_count = 0
        failed_creators = []

        for i, creator in enumerate(creators, 1):
            try:
                logger.info(f"[{i}/{len(creators)}] Processing creator {creator.id}...")
                logger.info(f"  Account: {creator.stripe_connect_account_id[:12]}...")

                # Create webhook on their Stripe Connect account
                webhook_info = await stripe_service.create_connected_account_webhook(
                    connected_account_id=creator.stripe_connect_account_id,
                    webhook_url=f"{settings.SERVER_HOST}/api/v1/marketplace/webhook"
                )

                # Store webhook credentials in database
                creator.stripe_webhook_id = webhook_info['webhook_id']
                creator.stripe_webhook_secret = webhook_info['webhook_secret']
                creator.webhook_created_at = datetime.utcnow()

                db.commit()

                logger.info(f"  SUCCESS! Webhook {webhook_info['webhook_id'][:12]}... created")
                logger.info("")
                success_count += 1

            except Exception as e:
                logger.error(f"  FAILED: {e}")
                logger.error("")
                db.rollback()
                fail_count += 1
                failed_creators.append({
                    'creator_id': creator.id,
                    'account_id': creator.stripe_connect_account_id,
                    'error': str(e)
                })
                continue

        # Print summary
        logger.info("=" * 70)
        logger.info("MIGRATION COMPLETE")
        logger.info("=" * 70)
        logger.info(f"Total creators processed: {len(creators)}")
        logger.info(f"✅ Success: {success_count}")
        logger.info(f"❌ Failed: {fail_count}")

        if failed_creators:
            logger.info("\nFailed creators:")
            for failed in failed_creators:
                logger.info(f"  - Creator {failed['creator_id']} ({failed['account_id'][:12]}...): {failed['error']}")

        logger.info("=" * 70)

        # Exit with error code if any failed
        if fail_count > 0:
            sys.exit(1)

    except Exception as e:
        logger.error(f"CRITICAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    finally:
        db.close()


def main():
    """Main entry point."""
    logger.info("Starting webhook creation for existing creators...")
    logger.info(f"Server host: {settings.SERVER_HOST}")
    logger.info(f"Webhook URL: {settings.SERVER_HOST}/api/v1/marketplace/webhook\n")

    # Run the async function
    asyncio.run(create_webhooks_for_existing_creators())

    logger.info("\nDone! All existing creators now have webhooks configured.")
    logger.info("New creators will automatically get webhooks when they complete onboarding.")


if __name__ == "__main__":
    main()
