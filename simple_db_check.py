#!/usr/bin/env python3
"""
Simple Database Schema Checker - Uses psycopg2 which should be available
"""
import os
import sys

# Add the app directory to Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("dotenv not available, using os.environ directly")

try:
    import psycopg2
    from psycopg2.extras import DictCursor
except ImportError:
    print("❌ psycopg2 not available. Please install with: pip install psycopg2-binary")
    sys.exit(1)

def check_database():
    """Check database schema using psycopg2"""
    
    # Get database URL
    DATABASE_URL = os.getenv("DEV_DATABASE_URL") or os.getenv("DATABASE_URL")
    
    if not DATABASE_URL:
        print("❌ No database URL found in environment")
        return False
    
    print(f"🔌 Connecting to database...")
    print(f"📡 URL: {DATABASE_URL[:50]}...")
    
    try:
        # Connect to database
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor(cursor_factory=DictCursor)
        
        print("✅ Connected to database successfully!")
        
        print("\n" + "="*60)
        print("🔍 CHECKING TABLES")
        print("="*60)
        
        # Check if tables exist
        tables_to_check = [
            'users', 'creator_profiles', 'strategy_pricing', 
            'strategy_purchases', 'creator_earnings', 'webhooks', 'alembic_version'
        ]
        
        for table in tables_to_check:
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = %s
                )
            """, (table,))
            
            exists = cursor.fetchone()[0]
            status = "✅ EXISTS" if exists else "❌ MISSING"
            print(f"{table:<20} {status}")
        
        print("\n" + "="*60)
        print("🔍 CHECKING USER TABLE COLUMNS") 
        print("="*60)
        
        # Check users table columns
        cursor.execute("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_name = 'users'
            ORDER BY ordinal_position
        """)
        
        columns = cursor.fetchall()
        if columns:
            print(f"{'Column':<25} {'Type':<15} {'Nullable':<8} {'Default'}")
            print("-" * 70)
            
            has_creator_profile_id = False
            for col in columns:
                nullable = "YES" if col['is_nullable'] == 'YES' else "NO"
                default = str(col['column_default']) if col['column_default'] else ""
                print(f"{col['column_name']:<25} {col['data_type']:<15} {nullable:<8} {default}")
                
                if col['column_name'] == 'creator_profile_id':
                    has_creator_profile_id = True
            
            print(f"\n📋 creator_profile_id column: {'✅ EXISTS' if has_creator_profile_id else '❌ MISSING'}")
        else:
            print("⚠️  Users table not found or no columns")
        
        print("\n" + "="*60)
        print("🔍 CHECKING MIGRATION STATUS")
        print("="*60)
        
        # Check alembic version
        try:
            cursor.execute("SELECT version_num FROM alembic_version")
            version = cursor.fetchone()
            if version:
                current_version = version[0]
                print(f"Current migration: {current_version}")
                
                if 'mno678pqr901' in current_version:
                    print("✅ Creator marketplace migration is applied!")
                else:
                    print(f"⚠️  Expected creator marketplace migration: mno678pqr901")
            else:
                print("❌ No migration version found")
        except psycopg2.ProgrammingError as e:
            print(f"❌ Error checking migration: {e}")
        
        print("\n" + "="*60)
        print("📊 DATA COUNTS")
        print("="*60)
        
        # Count users
        cursor.execute("SELECT COUNT(*) FROM users")
        user_count = cursor.fetchone()[0]
        print(f"Total users: {user_count}")
        
        # Count users with creator_profile_id (if column exists)
        if has_creator_profile_id:
            cursor.execute("SELECT COUNT(*) FROM users WHERE creator_profile_id IS NOT NULL")
            creator_users = cursor.fetchone()[0]
            print(f"Users with creator_profile_id: {creator_users}")
        
        # Count creator profiles (if table exists)
        try:
            cursor.execute("SELECT COUNT(*) FROM creator_profiles")
            profile_count = cursor.fetchone()[0]
            print(f"Total creator profiles: {profile_count}")
        except psycopg2.ProgrammingError:
            print("creator_profiles table does not exist")
        
        cursor.close()
        conn.close()
        
        print("\n✅ Database check completed!")
        return True
        
    except Exception as e:
        print(f"❌ Database connection error: {e}")
        return False

if __name__ == "__main__":
    print("🚀 Simple Database Schema Checker")
    print("=" * 60)
    
    success = check_database()
    
    if not success:
        print("\n💥 Database check failed!")
        sys.exit(1)
    else:
        print("\n🎉 Database check completed!")