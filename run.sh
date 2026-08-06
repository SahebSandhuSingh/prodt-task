#!/bin/bash
set -e

echo "========================================================================="
echo " Travel Booking Prototype — Full System Startup"
echo " Primary Startup Method: Docker Compose"
echo "========================================================================="

# 1. Create .env if not present
if [ ! -f .env ]; then
  echo "[1/3] Creating .env from .env.example..."
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
  echo "Please install Docker Desktop (https://www.docker.com/products/docker-desktop/)."
  exit 1
fi

# 2. Launch full stack via Docker Compose
echo "[2/3] Launching containerized stack (Postgres, Temporal Server, Temporal UI, API, Worker)..."
$DOCKER_COMPOSE up --build -d

# 3. Wait for PostgreSQL container health check
echo "[3/3] Waiting for database container readiness..."
until docker exec travel_booking_postgres pg_isready -U postgres -d travel_booking > /dev/null 2>&1; do
  sleep 1
done
echo "All services are up and healthy!"

echo "========================================================================="
echo " SYSTEM IS UP AND READY!"
echo "-------------------------------------------------------------------------"
echo " FastAPI Interactive Docs : http://localhost:8000/docs"
echo " Temporal Web UI          : http://localhost:8233"
echo " PostgreSQL Connection    : localhost:5433 (db: travel_booking)"
echo "========================================================================="
