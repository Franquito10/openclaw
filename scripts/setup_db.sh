#!/bin/bash
# Setup PostgreSQL for OpenClaw Ops Engine.
#
# Option A: Docker (if Docker Desktop WSL integration is enabled)
#   bash scripts/setup_db.sh docker
#
# Option B: Native PostgreSQL on WSL2
#   bash scripts/setup_db.sh native
#
# Option C: Just run migrations against existing DB
#   bash scripts/setup_db.sh migrate

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DATABASE_URL="${DATABASE_URL:-postgresql://openclaw:openclaw@127.0.0.1:5432/openclaw}"

case "${1:-help}" in
  docker)
    echo "=== Starting PostgreSQL via Docker ==="
    cd "$REPO_DIR"
    docker compose up -d
    echo "Waiting for PostgreSQL..."
    sleep 3
    echo "Running migrations..."
    psql "$DATABASE_URL" -f "$REPO_DIR/ops/schema.sql"
    echo "Running seed..."
    psql "$DATABASE_URL" -f "$REPO_DIR/ops/seed.sql"
    echo "Done! PostgreSQL running on port 5432."
    ;;

  native)
    echo "=== Installing PostgreSQL natively ==="
    sudo apt-get update -qq
    sudo apt-get install -y -qq postgresql postgresql-client

    echo "Starting PostgreSQL..."
    sudo service postgresql start

    echo "Creating user and database..."
    sudo -u postgres psql -c "CREATE USER openclaw WITH PASSWORD 'openclaw';" 2>/dev/null || true
    sudo -u postgres psql -c "CREATE DATABASE openclaw OWNER openclaw;" 2>/dev/null || true
    sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE openclaw TO openclaw;" 2>/dev/null || true

    echo "Running migrations..."
    PGPASSWORD=openclaw psql -h 127.0.0.1 -U openclaw -d openclaw -f "$REPO_DIR/ops/schema.sql"
    echo "Running seed..."
    PGPASSWORD=openclaw psql -h 127.0.0.1 -U openclaw -d openclaw -f "$REPO_DIR/ops/seed.sql"
    echo "Done! PostgreSQL running natively."
    ;;

  migrate)
    echo "=== Running migrations ==="
    psql "$DATABASE_URL" -f "$REPO_DIR/ops/schema.sql"
    echo "=== Running seed ==="
    psql "$DATABASE_URL" -f "$REPO_DIR/ops/seed.sql"
    echo "Done!"
    ;;

  *)
    echo "Usage: bash scripts/setup_db.sh {docker|native|migrate}"
    echo ""
    echo "  docker  — Start PostgreSQL in Docker and run migrations"
    echo "  native  — Install PostgreSQL via apt, create DB, run migrations"
    echo "  migrate — Just run schema.sql + seed.sql against DATABASE_URL"
    exit 1
    ;;
esac
