-- Add onboarding columns to users table
ALTER TABLE users 
ADD COLUMN onboarding_step INTEGER NULL,
ADD COLUMN onboarding_data JSON NULL;