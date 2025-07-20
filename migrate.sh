#!/bin/bash
# Simple script to run Alembic migrations

echo "Running Alembic migrations..."
cd "$(dirname "$0")"

# Show current revision
echo "Current database revision:"
alembic current

# Run migrations
echo -e "\nApplying migrations..."
alembic upgrade head

echo -e "\nMigrations completed!"

# Show new revision
echo -e "\nNew database revision:"
alembic current