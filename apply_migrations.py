#!/usr/bin/env python3
"""
Simple script to apply all pending Alembic migrations.
"""

import os
import sys

def main():
    try:
        # Import after setting up the path
        from alembic.config import Config
        from alembic import command
        
        # Get the directory containing this script
        script_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Create Alembic configuration
        alembic_cfg = Config(os.path.join(script_dir, "alembic.ini"))
        
        print("Applying migrations...")
        command.upgrade(alembic_cfg, "head")
        print("✅ Migrations completed successfully!")
        
        print("\nCurrent revision:")
        command.current(alembic_cfg)
        
    except Exception as e:
        print(f"❌ Error applying migrations: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()