"""Run the webhook fields migration."""
import os
os.environ['DATABASE_URL'] = 'postgresql://postgres:K2Q71c2OIVd1ZIXm8Ad1BFk5jF03Kj33@metro.proxy.rlwy.net:47089/railway'

from alembic.config import Config
from alembic import command

alembic_cfg = Config("alembic.ini")
print("Running migration: add_webhook_fields_to_creator_profiles")
command.upgrade(alembic_cfg, "head")
print("✅ Migration completed successfully!")
