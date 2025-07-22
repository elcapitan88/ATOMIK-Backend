#!/usr/bin/env python3
"""
Database Schema Checker Script
Connects to Railway PostgreSQL and checks current schema
"""
import os
import sys
import asyncio
import asyncpg
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Use DEV_DATABASE_URL which connects via external proxy
DATABASE_URL = os.getenv("DEV_DATABASE_URL")

if not DATABASE_URL:
    print("❌ DATABASE_URL not found in environment")
    sys.exit(1)

async def check_database_schema():
    """Check the current database schema"""
    try:
        print(f"🔌 Connecting to database...")
        print(f"📡 URL: {DATABASE_URL[:50]}...")
        
        conn = await asyncpg.connect(DATABASE_URL)
        print("✅ Connected to database successfully!")
        
        print("\n" + "="*60)
        print("🔍 CHECKING TABLES")
        print("="*60)
        
        # Check if main tables exist
        tables_to_check = [
            'users',
            'creator_profiles', 
            'strategy_pricing',
            'strategy_purchases', 
            'creator_earnings',
            'webhooks'
        ]
        
        existing_tables = []
        for table in tables_to_check:
            result = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = $1
                )
            """, table)
            
            status = "✅ EXISTS" if result else "❌ MISSING"
            print(f"{table:<20} {status}")
            if result:
                existing_tables.append(table)
        
        print("\n" + "="*60)
        print("🔍 CHECKING USER TABLE COLUMNS")
        print("="*60)
        
        if 'users' in existing_tables:
            # Get users table columns
            columns = await conn.fetch("""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_name = 'users'
                ORDER BY ordinal_position
            """)
            
            print("Column Name          | Data Type           | Nullable")
            print("-" * 60)
            
            has_creator_profile_id = False
            for col in columns:
                nullable = "YES" if col['is_nullable'] == 'YES' else "NO"
                print(f"{col['column_name']:<20} | {col['data_type']:<18} | {nullable}")
                if col['column_name'] == 'creator_profile_id':
                    has_creator_profile_id = True
            
            print(f"\n📋 creator_profile_id column: {'✅ EXISTS' if has_creator_profile_id else '❌ MISSING'}")
        
        print("\n" + "="*60)
        print("🔍 CHECKING MIGRATION STATUS")
        print("="*60)
        
        # Check alembic_version table
        has_alembic = await conn.fetchval("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = 'alembic_version'
            )
        """)
        
        if has_alembic:
            current_version = await conn.fetchval("SELECT version_num FROM alembic_version")
            print(f"Current migration: {current_version}")
            
            # Check if this is the creator marketplace migration
            if current_version and 'mno678pqr901' in current_version:
                print("✅ Creator marketplace migration is applied!")
            else:
                print(f"⚠️  Current migration: {current_version}")
                print("   Expected: mno678pqr901 (creator marketplace)")
        else:
            print("❌ alembic_version table not found - migrations not set up")
        
        print("\n" + "="*60)
        print("🔍 CHECKING FOREIGN KEYS")
        print("="*60)
        
        # Check foreign key constraints
        fk_constraints = await conn.fetch("""
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
            AND tc.table_name IN ('users', 'creator_profiles')
        """)
        
        for fk in fk_constraints:
            print(f"{fk['table_name']}.{fk['column_name']} -> {fk['foreign_table_name']}.{fk['foreign_column_name']}")
        
        if not fk_constraints:
            print("⚠️  No foreign key constraints found for users/creator_profiles")
        
        print("\n" + "="*60)
        print("📊 SAMPLE DATA CHECK")
        print("="*60)
        
        # Check user count
        if 'users' in existing_tables:
            user_count = await conn.fetchval("SELECT COUNT(*) FROM users")
            print(f"Total users: {user_count}")
            
            # Check if any users have creator_profile_id set
            if has_creator_profile_id:
                creators_count = await conn.fetchval("""
                    SELECT COUNT(*) FROM users 
                    WHERE creator_profile_id IS NOT NULL
                """)
                print(f"Users with creator_profile_id: {creators_count}")
            
        if 'creator_profiles' in existing_tables:
            creator_profiles_count = await conn.fetchval("SELECT COUNT(*) FROM creator_profiles")
            print(f"Total creator profiles: {creator_profiles_count}")
        
        await conn.close()
        print("\n✅ Database schema check completed!")
        
    except Exception as e:
        print(f"❌ Error checking database: {str(e)}")
        print(f"Error type: {type(e).__name__}")
        if hasattr(e, 'pgcode'):
            print(f"PostgreSQL error code: {e.pgcode}")
        return False
    
    return True

if __name__ == "__main__":
    print("🚀 Database Schema Checker")
    print("=" * 60)
    
    # Run the async function
    success = asyncio.run(check_database_schema())
    
    if success:
        print("\n🎉 Schema check completed successfully!")
    else:
        print("\n💥 Schema check failed!")
        sys.exit(1)