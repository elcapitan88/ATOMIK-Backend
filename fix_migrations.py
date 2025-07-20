#!/usr/bin/env python3
"""
Script to fix multiple heads issue and apply migrations.
"""

import os
import sys

def main():
    try:
        from alembic.config import Config
        from alembic import command
        
        script_dir = os.path.dirname(os.path.abspath(__file__))
        alembic_cfg = Config(os.path.join(script_dir, "alembic.ini"))
        
        print("Checking migration heads...")
        command.heads(alembic_cfg)
        
        print("\nCurrent revision:")
        command.current(alembic_cfg)
        
        print("\nApplying migrations to all heads...")
        # Apply to all heads specifically
        command.upgrade(alembic_cfg, "heads")
        
        print("✅ Migrations completed successfully!")
        
        print("\nNew current revision:")
        command.current(alembic_cfg)
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        print("\nTrying alternative approach...")
        
        # Alternative: try to apply specific migrations
        try:
            from alembic.config import Config
            from alembic import command
            
            script_dir = os.path.dirname(os.path.abspath(__file__))
            alembic_cfg = Config(os.path.join(script_dir, "alembic.ini"))
            
            # Try to apply the specific social media migration
            print("Applying social media fields migration...")
            command.upgrade(alembic_cfg, "nop789qrs012")
            
            print("✅ Social media migration completed!")
            
        except Exception as e2:
            print(f"❌ Alternative approach failed: {str(e2)}")
            
            # Last resort: show what we can do manually
            print("\n📋 Manual steps needed:")
            print("1. You may need to create a merge migration to resolve multiple heads")
            print("2. Or apply migrations to specific branches")
            
            sys.exit(1)

if __name__ == "__main__":
    main()