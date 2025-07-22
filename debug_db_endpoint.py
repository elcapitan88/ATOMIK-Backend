# Add this temporarily to your main.py file to create a debug endpoint

from sqlalchemy import text
from app.db.session import SessionLocal

@app.get("/debug/check-schema")
async def check_database_schema():
    """Debug endpoint to check database schema"""
    db = SessionLocal()
    try:
        results = {}
        
        # Check if creator_profile_id column exists
        result = db.execute(text("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'users' 
                AND column_name = 'creator_profile_id'
            )
        """)).fetchone()
        results['has_creator_profile_id_column'] = result[0] if result else False
        
        # Check if creator_profiles table exists
        result = db.execute(text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = 'creator_profiles'
            )
        """)).fetchone()
        results['has_creator_profiles_table'] = result[0] if result else False
        
        # Check migration version
        try:
            result = db.execute(text("SELECT version_num FROM alembic_version")).fetchone()
            results['current_migration'] = result[0] if result else None
        except:
            results['current_migration'] = "No alembic_version table"
        
        # Count users
        result = db.execute(text("SELECT COUNT(*) FROM users")).fetchone()
        results['total_users'] = result[0] if result else 0
        
        # If creator_profile_id column exists, count users with it set
        if results['has_creator_profile_id_column']:
            result = db.execute(text("""
                SELECT COUNT(*) FROM users 
                WHERE creator_profile_id IS NOT NULL
            """)).fetchone()
            results['users_with_creator_profile_id'] = result[0] if result else 0
        
        return {
            "status": "success",
            "database_schema": results
        }
        
    except Exception as e:
        return {
            "status": "error", 
            "error": str(e),
            "error_type": type(e).__name__
        }
    finally:
        db.close()