# Travel Booking Prototype

A production-grade travel booking system featuring multi-supplier offer aggregation, normalized ranking, PostgreSQL audit persistence, and durable workflow execution powered by Temporal.

---

## 🐳 Quick Start: Docker Compose (Primary Recommended Method)

### Prerequisite
- **Docker Desktop** (installed and running)

### One-Command Full Stack Startup
Clone the repository and bring up the complete containerized stack in a single command:

```bash
git clone https://github.com/SahebSandhuSingh/prodt-task.git
cd prodt-task
docker compose up --build
```

#### What `docker compose up --build` Launches:
- **`postgres`**: PostgreSQL 16 database container (`localhost:5433`, db: `travel_booking`).
- **`temporal`**: Temporal Server container (`localhost:7233`).
- **`temporal-ui`**: Temporal Web Dashboard (`http://localhost:8233`).
- **`api`**: FastAPI Web Server (`http://localhost:8000`, interactive OpenAPI docs at `/docs`).
- **`worker`**: Temporal Worker process listening on `booking-task-queue`.

---

## ⚡ Alternative Method: Local Script (`./run.sh`)

If you prefer running the Python services directly on your host machine:

```bash
./run.sh
```

---

## 🌐 Live Services & Verification URLs

- **FastAPI Interactive Docs (Swagger UI)**: `http://localhost:8000/docs`
- **Temporal Web Dashboard**: `http://localhost:8233`
- **PostgreSQL Connection**: `localhost:5433` (db: `travel_booking`, user: `postgres`, password: `postgres`)

### Example Usage Commands

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
    "offer_id": "OFFER-330001a322faaf48",
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

## 🧪 Running Automated Tests

```bash
python -m pytest -v tests/
```