# Travel Booking Prototype — Implementation & Architecture Guide

## Overview

This project is a clean, isolated **Travel Booking Prototype** built in Python across modular steps:

- **Step 1 — Supplier Integration Layer**: Abstract adapter layer (`SupplierAdapter`), normalized `UnifiedOffer` Pydantic model, exception hierarchy (`SupplierError`), mock APIs (`MockAtlasAPI` & `MockNovaAPI`), and dynamic `AdapterRegistry`.
- **Step 2 — Hotel Search API Layer**: FastAPI search application exposing `POST /search/hotels` and `GET /health`. Executes concurrent supplier queries, enforces timeout protection, deduplicates overlapping properties, ranks offers via a weighted composite formula, and degrades gracefully on partial or total supplier failures.
- **Step 3 — Temporal Booking Workflow & Lifecycle Layer**: Orchestrates the complete booking lifecycle via `BookingWorkflow` (offer revalidation, price drift checks, supplier reservation creation, PostgreSQL persistence, polling, Saga pattern compensation, and manual review fallbacks). Supported by deterministic Workflow ID idempotency and REST endpoints (`POST /bookings`, `GET /bookings/{id}`, `POST /bookings/{id}/cancel`).

---

## Directory Structure

```
/Users/sahebsandhu/prodt-task/
├── pyproject.toml              # Build, dependencies, & pytest config
├── IMPLEMENTATION.md           # Implementation document & architectural guide
├── README.md                   # Quickstart guide
├── docker-compose.yml          # PostgreSQL container orchestration
├── worker.py                   # Temporal worker process script
├── conftest.py                 # Root sys.path test environment configuration
├── schemas/
│   ├── offer.py                # Pydantic schema for UnifiedOffer & AvailabilityStatus (Step 1)
│   └── search.py               # SearchRequest & SearchResponse schemas (Step 2)
├── db/
│   ├── init.sql                # SQL schema initialization for PostgreSQL
│   ├── models.py               # SQLAlchemy ORM model (BookingRecord)
│   └── session.py              # Async database session & engine manager
├── mocks/
│   ├── mock_atlas_api.py       # Simulated Atlas Hotels API (idempotency token support)
│   └── mock_nova_api.py        # Simulated Nova Stays API (idempotency token support)
├── adapters/
│   ├── base.py                 # Abstract base class SupplierAdapter
│   ├── exceptions.py           # Standardized exception hierarchy (SupplierError base)
│   ├── atlas_adapter.py        # Adapter for Atlas Hotels API
│   ├── nova_adapter.py         # Adapter for Nova Stays API
│   └── registry.py             # Supplier adapter registry and factory functions
├── services/
│   ├── search_service.py       # Concurrent search aggregator, deduplication, & timeout handling
│   └── ranking.py              # Pure offer scoring & ranking engine
├── workflows/
│   └── booking_workflow.py     # Temporal BookingWorkflow orchestration
├── activities/
│   └── booking_activities.py   # Temporal Activities (revalidate, reserve, persist DB, poll, cancel)
├── client/
│   └── booking_client.py       # CLI client for triggering/querying/cancelling workflows
├── api/
│   ├── main.py                 # FastAPI application instance & router setup
│   └── routes/
│       ├── search.py           # Search endpoints: POST /search/hotels, GET /health
│       └── booking.py          # Booking endpoints: POST /bookings, GET /bookings/{id}, POST /bookings/{id}/cancel
└── tests/
    ├── conftest.py             # Pytest configuration
    ├── test_atlas_adapter.py   # Unit tests for AtlasAdapter & failure modes (Step 1)
    ├── test_nova_adapter.py    # Unit tests for NovaAdapter & failure modes (Step 1)
    ├── test_normalization.py   # Schema price math & cross-supplier normalization tests (Step 1)
    ├── test_ranking.py         # Pure ranking algorithm tests (Step 2)
    ├── test_search_service.py  # Concurrency, timeout, deduplication, & failure tests (Step 2)
    ├── test_search_endpoint.py # FastAPI search endpoint validation & response tests (Step 2)
    └── test_booking_workflow.py# Temporal workflow unit & time-skipping integration tests (Step 3)
```

---

## Step 3 Architecture & Specifications

### 1. Workflow ID & Idempotency Strategy
- **Workflow ID Formula**: `booking-{idempotency_key}`
- **Duplicate Request Handling**: Starting a workflow with an idempotency key that is already running or completed triggers Temporal's `WorkflowAlreadyStartedError` on the client. The client/endpoint handles this error by attaching to the existing workflow handle and querying its status rather than creating a second reservation.

### 2. Per-Activity Retry Policies & Timeouts
- **`revalidate_offer_activity`**: `start_to_close_timeout=10s`, `max_attempts=5`, `initial_interval=1s`, `backoff=2.0`.
  - *Justification*: Read-only idempotent call; liberal retries handle transient network blips safely.
- **`create_supplier_reservation_activity`**: `start_to_close_timeout=15s`, `max_attempts=2`, `initial_interval=2s`, `backoff=2.0`.
  - *Justification*: State-changing financial operation; conservative retries minimize duplicate supplier booking risks.
- **`persist_booking_record_activity`**: `start_to_close_timeout=10s`, `max_attempts=3`, `initial_interval=1s`, `backoff=2.0`.
  - *Justification*: Writes to PostgreSQL using unique constraints.
- **`poll_supplier_confirmation_activity`**: `start_to_close_timeout=10s`, `max_attempts=3`, `initial_interval=1s`, `backoff=2.0`.
- **`cancel_supplier_reservation_activity`**: `start_to_close_timeout=15s`, `max_attempts=3`, `initial_interval=1s`, `backoff=2.0`.
  - *Justification*: Saga compensation activity. If 3 retries fail, workflow transitions to `REQUIRES_MANUAL_REVIEW`.

### 3. Polling Constants & Unconfirmed Resolution Rule
- **`POLL_INTERVAL`**: `timedelta(seconds=2)` (workflow sleeps 2 seconds between polls via `workflow.sleep`).
- **`MAX_POLL_ATTEMPTS`**: `5` attempts ($10\text{s}$ total polling timeout).
- **Strict Resolution Rule**: If `poll_supplier_confirmation_activity` exhausts `MAX_POLL_ATTEMPTS` without receiving an explicit `CONFIRMED` or `FAILED` status from the supplier, the workflow resolves to **`REQUIRES_MANUAL_REVIEW`** (never `CONFIRMED`).

### 4. Saga Pattern Compensation & Fallbacks
1. If `create_supplier_reservation_activity` succeeds but `persist_booking_record_activity` fails after retries are exhausted, the workflow triggers `cancel_supplier_reservation_activity`.
2. If `cancel_supplier_reservation_activity` succeeds $\rightarrow$ workflow resolves to `FAILED` (supplier booking undone).
3. If `cancel_supplier_reservation_activity` ALSO fails $\rightarrow$ workflow resolves to `REQUIRES_MANUAL_REVIEW`.

### 5. Mid-Polling Cancellation Signal
An explicit `if self._cancel_requested:` check is evaluated inside the polling loop. If a `cancel_booking` signal arrives while sleeping between poll attempts, the workflow invokes `cancel_supplier_reservation_activity` and resolves to `CANCELLED`.

---

## Manual Verification Steps (Worker Restart & End-to-End Flow)

1. **Start Infrastructure**:
   ```bash
   docker-compose up -d postgres
   temporal server start-dev
   ```
2. **Start Worker Process**:
   ```bash
   python worker.py
   ```
3. **Trigger Booking via CLI or API**:
   ```bash
   python client/booking_client.py
   # Or POST http://localhost:8000/bookings
   ```
4. **Simulate Worker Crash During Polling**:
   - Kill `worker.py` (`Ctrl+C` or `kill -9`) while workflow is in `POLLING_SUPPLIER_CONFIRMATION` step.
5. **Relaunch Worker & Verify UI**:
   - Relaunch `python worker.py`.
   - Open Temporal Web UI (`http://localhost:8233`). Verify the workflow resumed execution from the exact polling state and completed to `CONFIRMED` without duplicating supplier calls.

---

## Running the Complete Test Suite

Run all 40 unit and integration tests across Steps 1, 2, and 3:

```bash
/Users/sahebsandhu/prodt-task/.venv312/bin/pytest -v
```
