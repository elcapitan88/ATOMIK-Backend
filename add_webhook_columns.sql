-- Add webhook fields to creator_profiles table
-- Run this directly in your Railway PostgreSQL database

-- Add the new columns
ALTER TABLE creator_profiles
ADD COLUMN IF NOT EXISTS stripe_webhook_id VARCHAR(255),
ADD COLUMN IF NOT EXISTS stripe_webhook_secret VARCHAR(255),
ADD COLUMN IF NOT EXISTS webhook_created_at TIMESTAMP WITH TIME ZONE;

-- Add index for faster lookups
CREATE INDEX IF NOT EXISTS ix_creator_profiles_stripe_connect_account_id
ON creator_profiles(stripe_connect_account_id);

-- Add comments for documentation
COMMENT ON COLUMN creator_profiles.stripe_webhook_id IS 'Stripe webhook endpoint ID (e.g., we_xxx) created on the connected account';
COMMENT ON COLUMN creator_profiles.stripe_webhook_secret IS 'Signing secret for verifying webhook events from this creator';
COMMENT ON COLUMN creator_profiles.webhook_created_at IS 'When the webhook endpoint was created';

-- Update the alembic version table to mark this migration as complete
INSERT INTO alembic_version (version_num) VALUES ('add_webhook_fields_creator')
ON CONFLICT (version_num) DO NOTHING;

-- Verify the changes
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'creator_profiles'
AND column_name IN ('stripe_webhook_id', 'stripe_webhook_secret', 'webhook_created_at')
ORDER BY column_name;

SELECT 'Migration completed successfully!' as status;
