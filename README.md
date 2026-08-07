# Travel Supplier Search & Booking Engine

A travel booking system featuring multi-supplier offer aggregation, normalized composite ranking, PostgreSQL audit persistence, and durable workflow orchestration powered by Temporal.

---

## Documentation Index

Comprehensive project documentation is available in the `docs/` directory:

- [System Architecture](docs/ARCHITECTURE.md): Architecture overview, system sequence diagram, search & saga booking flow walkthroughs.
- [Database Schema](docs/DATABASE_SCHEMA.md): Complete reference for all 6 database tables, ER diagram, deterministic offer hash rationale, and Alembic migrations.
- [API Reference](docs/API.md): Endpoint manual with real request/response payloads and error response schemas.
- [Engineering Decisions & Limitations](docs/DECISIONS_AND_LIMITATIONS.md): Technical decision rationale and explicit system assumptions.
- [AI Usage Documentation](docs/AI_USAGE.md): Narrative documenting AI coding assistant usage, plan reviews, and engineering choices.

---

## Quick Start: Docker Compose (Primary Deployment Method)

### Prerequisite
- **Docker Desktop** (installed and running)

### Full Stack Startup
Clone the repository and bring up the complete containerized stack:

```bash
git clone https://github.com/SahebSandhuSingh/prodt-task.git
cd prodt-task
docker compose up --build
```

#### Services Launched:
- **`postgres`**: PostgreSQL 16 database (`localhost:5433`, database: `travel_booking`).
- **`temporal`**: Temporal Server (`localhost:7233`).
- **`temporal-ui`**: Temporal Web Dashboard (`http://localhost:8233`).
- **`api`**: FastAPI Web Server (`http://localhost:8000`, interactive Swagger UI at `/docs`, web SPA at `/`).
- **`worker`**: Temporal Worker process executing booking workflow activities.

---

## Live Services & Endpoints

- **Web Dashboard**: `http://localhost:8000/`
- **FastAPI OpenAPI Documentation**: `http://localhost:8000/docs`
- **Temporal Web Dashboard**: `http://localhost:8233`
- **PostgreSQL Connection**: `localhost:5433` (db: `travel_booking`, user: `postgres`, password: `postgres`)

### Example Terminal Commands

#### 1. Search Hotels (Aggregated & Ranked)
```bash
curl -s -X POST http://localhost:8000/search/hotels \
  -H "Content-Type: application/json" \
  -d '{"destination": "Paris", "check_in": "2026-09-01", "check_out": "2026-09-05", "guests": 2, "rooms": 1}'
```

#### 2. Query Persisted Search Request
```bash
curl -s http://localhost:8000/search-requests/<request_id>
```

#### 3. Create Hotel Booking Workflow
```bash
curl -s -X POST http://localhost:8000/bookings \
  -H "Content-Type: application/json" \
  -d '{
    "offer_id": "OFFER-atlas-ATL-PAR-01",
    "supplier_id": "atlas",
    "property_id": "ATL-PAR-01",
    "check_in_date": "2026-09-01",
    "check_out_date": "2026-09-05",
    "quoted_price": 240.0,
    "currency": "EUR",
    "guest_name": "Alice Smith",
    "idempotency_key": "demo-booking-key-1"
  }'
```

#### 4. Query Booking State & Audit History
```bash
curl -s http://localhost:8000/bookings/booking-demo-booking-key-1
curl -s http://localhost:8000/bookings/BK-demo-booking/history
```

---

## Running Automated Tests

To execute the test suite:

```bash
.venv312/bin/pytest -v tests/
```
