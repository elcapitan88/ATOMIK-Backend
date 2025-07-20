#!/usr/bin/env python3
"""
Simple script to apply only the social media migration that we need for login.
"""

import os
import sys

def main():
    try:
        from alembic.config import Config
        from alembic import command
        
        script_dir = os.path.dirname(os.path.abspath(__file__))
        alembic_cfg = Config(os.path.join(script_dir, "alembic.ini"))
        
        print("Current revision:")
        command.current(alembic_cfg)
        
        print("\nApplying social media migration (nop789qrs012)...")
        
        # First, let's try to get to the base of this branch
        try:
            # Apply the creator marketplace migration first
            command.upgrade(alembic_cfg, "mno678pqr901")
            print("✅ Creator marketplace migration applied")
        except Exception as e:
            print(f"⚠️  Creator marketplace migration issue: {e}")
        
        # Then apply the social media migration
        try:
            command.upgrade(alembic_cfg, "nop789qrs012")
            print("✅ Social media migration applied")
        except Exception as e:
            print(f"❌ Social media migration failed: {e}")
            return False
        
        print("\nFinal revision:")
        command.current(alembic_cfg)
        
        print("\n✅ Social media fields should now be available for login!")
        return True
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return False

if __name__ == "__main__":
    success = main()
    if not success:
        sys.exit(1)