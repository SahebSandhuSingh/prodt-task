#!/bin/bash
set -e

echo "========================================================================="
echo " Travel Booking Prototype — Full System Startup"
echo "========================================================================="

# Create .env if not exists
if [ ! -f .env ]; then
  echo "[1/4] Creating .env from .env.example..."
  cp .env.example .env
fi

# Export environment variables
export $(grep -v '^#' .env | xargs)

# Detect Docker Compose command
if docker compose version >/dev/null 2>&1; then
  DOCKER_COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  DOCKER_COMPOSE="docker-compose"
else
  echo "ERROR: Neither 'docker compose' nor 'docker-compose' found."
  exit 1
fi

# 1. Bring up complete stack
echo "[2/4] Launching Docker Compose stack (Postgres, Temporal, UI, API, Worker)..."
$DOCKER_COMPOSE up --build -d

# 2. Wait for PostgreSQL container health check
echo "[3/4] Waiting for PostgreSQL database container..."
until docker exec travel_booking_postgres pg_isready -U postgres -d travel_booking > /dev/null 2>&1; do
  sleep 1
done
echo "PostgreSQL is healthy and ready!"

# 3. Print Ready Summary
echo "========================================================================="
echo " SYSTEM IS UP AND READY!"
echo "-------------------------------------------------------------------------"
echo " FastAPI Interactive Docs : http://localhost:8000/docs"
echo " Temporal Web UI          : http://localhost:8233"
echo " PostgreSQL Connection    : localhost:5433 (db: travel_booking)"
echo "========================================================================="
