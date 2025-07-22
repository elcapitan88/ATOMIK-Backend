-- Database Schema Check Script
-- Run this with: psql "postgresql://postgres:ljjqmjlQJdyBWjNzUglEQxKmfzmZRGfi@metro.proxy.rlwy.net:47089/railway" -f check_db.sql

\echo '====== CHECKING TABLES ======'

-- Check if main tables exist
SELECT 
    table_name,
    CASE 
        WHEN table_name IN (
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
        ) THEN 'EXISTS ✅'
        ELSE 'MISSING ❌'
    END as status
FROM (VALUES 
    ('users'),
    ('creator_profiles'), 
    ('strategy_pricing'),
    ('strategy_purchases'), 
    ('creator_earnings'),
    ('webhooks'),
    ('alembic_version')
) AS t(table_name);

\echo
\echo '====== CHECKING USER TABLE COLUMNS ======'

-- Get users table columns
SELECT 
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_name = 'users'
ORDER BY ordinal_position;

\echo
\echo '====== CHECKING FOR creator_profile_id COLUMN ======'

-- Specifically check for creator_profile_id column
SELECT 
    CASE 
        WHEN EXISTS (
            SELECT 1 
            FROM information_schema.columns
            WHERE table_name = 'users' 
            AND column_name = 'creator_profile_id'
        ) THEN 'creator_profile_id column EXISTS ✅'
        ELSE 'creator_profile_id column MISSING ❌'
    END as result;

\echo
\echo '====== CHECKING MIGRATION STATUS ======'

-- Check current migration version
SELECT 
    CASE 
        WHEN EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'alembic_version')
        THEN (SELECT 'Current migration: ' || version_num FROM alembic_version)
        ELSE 'No alembic_version table found'
    END as migration_status;

\echo
\echo '====== CHECKING FOREIGN KEY CONSTRAINTS ======'

-- Check foreign key constraints on users table
SELECT 
    tc.table_name, 
    kcu.column_name, 
    ccu.table_name AS foreign_table_name,
    ccu.column_name AS foreign_column_name,
    tc.constraint_name
FROM information_schema.table_constraints AS tc 
JOIN information_schema.key_column_usage AS kcu
    ON tc.constraint_name = kcu.constraint_name
    AND tc.table_schema = kcu.table_schema
JOIN information_schema.constraint_column_usage AS ccu
    ON ccu.constraint_name = tc.constraint_name
    AND ccu.table_schema = tc.table_schema
WHERE tc.constraint_type = 'FOREIGN KEY' 
AND tc.table_name = 'users'
AND kcu.column_name = 'creator_profile_id';

\echo
\echo '====== SAMPLE DATA CHECK ======'

-- Count users
SELECT 'Total users: ' || COUNT(*) FROM users;

-- Check if creator_profile_id column exists and has data
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'creator_profile_id') THEN
        PERFORM (SELECT 'Users with creator_profile_id: ' || COUNT(*) FROM users WHERE creator_profile_id IS NOT NULL);
    ELSE
        RAISE NOTICE 'creator_profile_id column does not exist';
    END IF;
END $$;

-- Count creator profiles if table exists
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'creator_profiles') THEN
        PERFORM (SELECT 'Total creator profiles: ' || COUNT(*) FROM creator_profiles);
    ELSE
        RAISE NOTICE 'creator_profiles table does not exist';
    END IF;
END $$;