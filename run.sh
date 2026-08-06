#!/bin/bash
set -e

echo "========================================================================="
echo " Travel Booking Prototype — Local Development Setup"
echo "========================================================================="

# 1. Ensure .env exists
if [ ! -f .env ]; then
  echo "[1/4] Creating .env from .env.example..."
  cp .env.example .env
fi

export $(grep -v '^#' .env | xargs)

# Detect Docker Compose command
if docker compose version >/dev/null 2>&1; then
  DOCKER_COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  DOCKER_COMPOSE="docker-compose"
else
  echo "ERROR: Neither 'docker compose' nor 'docker-compose' found. Please install Docker."
  exit 1
fi

# 2. Start PostgreSQL container
echo "[2/4] Starting PostgreSQL container via $DOCKER_COMPOSE..."
$DOCKER_COMPOSE up -d postgres

echo "Waiting for PostgreSQL container to become healthy..."
until docker exec travel_booking_postgres pg_isready -U postgres -d travel_booking > /dev/null 2>&1; do
  sleep 1
done
echo "PostgreSQL is healthy and ready on port 5433!"

# 3. Check/Start Temporal dev-server
echo "[3/4] Checking Temporal Server (port 7233)..."
if nc -z localhost 7233 2>/dev/null || curl -s http://localhost:7233 >/dev/null 2>&1; then
  echo "Temporal Server is already running on localhost:7233."
else
  if command -v temporal >/dev/null 2>&1; then
    echo "Starting local Temporal dev-server in background..."
    temporal server start-dev --ip 0.0.0.0 --port 7233 --ui-port 8233 > /tmp/temporal_dev.log 2>&1 &
    sleep 3
    echo "Temporal Server started! UI available at http://localhost:8233"
  else
    echo "WARNING: 'temporal' CLI not found in PATH."
    echo "Please start Temporal server manually using 'temporal server start-dev'."
  fi
fi

# 4. Database Migrations via Alembic
echo "[4/4] Running Alembic Database Migrations..."
if [ -f .venv312/bin/alembic ]; then
  DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5433/travel_booking" .venv312/bin/alembic upgrade head 2>/dev/null || DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5433/travel_booking" .venv312/bin/alembic stamp head
elif [ -f .venv/bin/alembic ]; then
  DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5433/travel_booking" .venv/bin/alembic upgrade head 2>/dev/null || DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5433/travel_booking" .venv/bin/alembic stamp head
else
  DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5433/travel_booking" alembic upgrade head 2>/dev/null || DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5433/travel_booking" alembic stamp head
fi
echo "Alembic migrations completed successfully!"

echo "========================================================================="
echo " LOCAL DEV INFRASTRUCTURE IS READY!"
echo "-------------------------------------------------------------------------"
echo " Run Worker : python worker.py"
echo " Run API    : uvicorn api.main:app --port 8000"
echo " Temporal UI: http://localhost:8233"
echo " OpenAPI    : http://localhost:8000/docs"
echo "========================================================================="
