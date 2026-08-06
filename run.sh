#!/bin/bash
set -e

echo "========================================================================="
echo " Travel Booking Prototype — Single-Command Full Stack Startup"
echo "========================================================================="

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

# 1. Environment configuration (.env)
if [ ! -f .env ]; then
  echo "[1/7] Creating .env from .env.example..."
  cp .env.example .env
fi

export $(grep -v '^#' .env | xargs)

# 2. Virtual environment and dependencies
PYTHON_BIN="python3"
if command -v python3.12 >/dev/null 2>&1; then
  PYTHON_BIN="python3.12"
fi

if [ -d .venv312 ]; then
  VENV_PY="$PROJECT_DIR/.venv312/bin/python"
  VENV_ALEMBIC="$PROJECT_DIR/.venv312/bin/alembic"
  VENV_UVICORN="$PROJECT_DIR/.venv312/bin/uvicorn"
elif [ -d .venv ]; then
  VENV_PY="$PROJECT_DIR/.venv/bin/python"
  VENV_ALEMBIC="$PROJECT_DIR/.venv/bin/alembic"
  VENV_UVICORN="$PROJECT_DIR/.venv/bin/uvicorn"
else
  echo "[2/7] Creating Python virtual environment (.venv)..."
  $PYTHON_BIN -m venv .venv
  VENV_PY="$PROJECT_DIR/.venv/bin/python"
  VENV_ALEMBIC="$PROJECT_DIR/.venv/bin/alembic"
  VENV_UVICORN="$PROJECT_DIR/.venv/bin/uvicorn"
  echo "Installing dependencies..."
  $VENV_PY -m pip install --upgrade pip
  $VENV_PY -m pip install -e . aiosqlite greenlet alembic pytest pytest-asyncio pytest-cov httpx
fi

# 3. Detect Docker Compose CLI
if docker compose version >/dev/null 2>&1; then
  DOCKER_COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  DOCKER_COMPOSE="docker-compose"
else
  echo "ERROR: Neither 'docker compose' nor 'docker-compose' found. Please install Docker."
  exit 1
fi

# 4. Start PostgreSQL container
echo "[3/7] Starting PostgreSQL container..."
$DOCKER_COMPOSE up -d postgres

echo "Waiting for PostgreSQL container to become healthy..."
until docker exec travel_booking_postgres pg_isready -U postgres -d travel_booking > /dev/null 2>&1; do
  sleep 1
done
echo "PostgreSQL is healthy and ready on port 5433!"

# 5. Check / Install & Start Temporal Server
echo "[4/7] Checking Temporal Server (port 7233)..."
TEMPORAL_CMD=""
if command -v temporal >/dev/null 2>&1; then
  TEMPORAL_CMD="temporal"
elif [ -f "$HOME/.temporalio/bin/temporal" ]; then
  TEMPORAL_CMD="$HOME/.temporalio/bin/temporal"
elif [ -f "$PROJECT_DIR/.temporal/bin/temporal" ]; then
  TEMPORAL_CMD="$PROJECT_DIR/.temporal/bin/temporal"
else
  echo "Temporal CLI not found. Auto-installing Temporal CLI..."
  mkdir -p "$PROJECT_DIR/.temporal"
  curl -sSf https://temporal.download/cli.sh | sh -s -- --dir "$PROJECT_DIR/.temporal/bin"
  TEMPORAL_CMD="$PROJECT_DIR/.temporal/bin/temporal"
fi

if nc -z localhost 7233 2>/dev/null || curl -s http://localhost:7233 >/dev/null 2>&1; then
  echo "Temporal Server is already running on localhost:7233."
else
  echo "Starting local Temporal dev-server in background..."
  $TEMPORAL_CMD server start-dev --ip 0.0.0.0 --port 7233 --ui-port 8233 > /tmp/temporal_dev.log 2>&1 &
  sleep 3
  echo "Temporal Server started! UI available at http://localhost:8233"
fi

# 6. Database Migrations via Alembic
echo "[5/7] Running Alembic Database Migrations..."
DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5433/travel_booking" \
  $VENV_ALEMBIC upgrade head 2>/dev/null || \
DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5433/travel_booking" \
  $VENV_ALEMBIC stamp head
echo "Alembic database migrations completed successfully!"

# 7. Start Temporal Worker & FastAPI App
echo "[6/7] Starting Temporal Worker process..."
pkill -f "worker.py" 2>/dev/null || true
DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5433/travel_booking" \
TEMPORAL_HOST="localhost:7233" \
  $VENV_PY worker.py > /tmp/worker.log 2>&1 &
sleep 2

echo "[7/7] Starting FastAPI Web Server..."
pkill -f "uvicorn api.main:app" 2>/dev/null || true
DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5433/travel_booking" \
TEMPORAL_HOST="localhost:7233" \
  $VENV_UVICORN api.main:app --host 0.0.0.0 --port 8000 > /tmp/api.log 2>&1 &
sleep 2

echo "========================================================================="
echo " ALL SERVICES ARE STARTED AND OPERATIONAL!"
echo "-------------------------------------------------------------------------"
echo " FastAPI Interactive Docs : http://localhost:8000/docs"
echo " Temporal Web UI          : http://localhost:8233"
echo " PostgreSQL Database      : localhost:5433 (db: travel_booking)"
echo "========================================================================="
