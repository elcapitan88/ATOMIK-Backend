#!/usr/bin/env python3
"""
Script to run Alembic migrations for the Atomik backend.
This script can be run locally or in production to apply database migrations.
"""

import os
import sys
from alembic.config import Config
from alembic import command
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_migrations():
    """Run all pending Alembic migrations."""
    try:
        # Get the directory containing this script
        script_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Create Alembic configuration
        alembic_cfg = Config(os.path.join(script_dir, "alembic.ini"))
        
        # Show current revision
        logger.info("Current database revision:")
        command.current(alembic_cfg)
        
        # Show pending migrations
        logger.info("\nChecking for pending migrations...")
        
        # Run the migrations
        logger.info("\nRunning migrations...")
        command.upgrade(alembic_cfg, "head")
        
        logger.info("\nMigrations completed successfully!")
        
        # Show new current revision
        logger.info("\nNew database revision:")
        command.current(alembic_cfg)
        
    except Exception as e:
        logger.error(f"Error running migrations: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    run_migrations()