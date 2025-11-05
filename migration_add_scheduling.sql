-- Strategy Scheduler Migration
-- Adds scheduling fields to activated_strategies table
-- Run this SQL directly on your PostgreSQL database

-- Add market_schedule column
ALTER TABLE activated_strategies
ADD COLUMN IF NOT EXISTS market_schedule VARCHAR(50);

-- Add schedule_active_state column
ALTER TABLE activated_strategies
ADD COLUMN IF NOT EXISTS schedule_active_state BOOLEAN;

-- Add last_scheduled_toggle column
ALTER TABLE activated_strategies
ADD COLUMN IF NOT EXISTS last_scheduled_toggle TIMESTAMP;

-- Verify columns were added
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'activated_strategies'
  AND column_name IN ('market_schedule', 'schedule_active_state', 'last_scheduled_toggle')
ORDER BY column_name;

-- Insert into alembic_version to track this migration
-- (Adjust the revision ID if needed to match your migration file)
INSERT INTO alembic_version (version_num)
VALUES ('add_strategy_scheduling')
ON CONFLICT (version_num) DO NOTHING;

-- Success message
SELECT 'Migration completed successfully! Strategy scheduling fields added.' AS status;
