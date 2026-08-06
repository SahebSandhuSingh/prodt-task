# Travel Booking Prototype — Implementation & Architecture Guide

## Overview

This project is a clean, isolated **Travel Booking Prototype** built in Python across modular steps:

- **Step 1 — Supplier Integration Layer**: Abstract adapter layer (`SupplierAdapter`), normalized `UnifiedOffer` Pydantic model, exception hierarchy (`SupplierError`), mock APIs (`MockAtlasAPI` & `MockNovaAPI`), and dynamic `AdapterRegistry`.
- **Step 2 — Hotel Search API Layer**: FastAPI search application exposing `POST /search/hotels` and `GET /health`. Executes concurrent supplier queries, enforces timeout protection, deduplicates overlapping properties, ranks offers via a weighted composite formula, and degrades gracefully on partial or total supplier failures.
- **Step 3 — Temporal Booking Workflow Layer**: Orchestrates the complete booking lifecycle via `BookingWorkflow` (offer revalidation, price drift checks, supplier reservation creation, PostgreSQL persistence, polling, Saga pattern compensation, and manual review fallbacks).
- **Step 4 — Full Persistence Schema & End-to-End Observability Layer**: Extends database schema across 5 tables (`bookings`, `search_requests`, `normalized_offers`, `supplier_references`, `booking_status_history`, `failure_log`). Implements Alembic migrations, fire-and-forget search audit writes via `asyncio.create_task`, structured single-line JSON logging without PII, and Admin read endpoints (`GET /bookings/{id}/history`, `GET /search-requests/{id}`, `GET /failures`).

---

## Directory Structure

```
/Users/sahebsandhu/prodt-task/
├── pyproject.toml              # Build, dependencies, & pytest config
├── IMPLEMENTATION.md           # Implementation document & architectural guide
├── README.md                   # Quickstart guide
├── alembic.ini                 # Alembic configuration
├── alembic/
│   ├── env.py                  # Alembic environment runner
│   └── versions/
│       └── 001_full_schema.py  # Initial Alembic database migration
├── docker-compose.yml          # PostgreSQL container orchestration
├── logging_config.py           # Structured JSON logging formatter & setup (No PII)
├── worker.py                   # Temporal worker process script
├── conftest.py                 # Root sys.path test environment configuration
├── schemas/
│   ├── offer.py                # Pydantic schema for UnifiedOffer & AvailabilityStatus (Step 1)
│   └── search.py               # SearchRequest & SearchResponse schemas (Step 2)
├── db/
│   ├── init.sql                # Static SQL reference for PostgreSQL container startup
│   ├── models.py               # SQLAlchemy ORM models (5 tables + deterministic offer_id hash generator)
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
│   ├── search_service.py       # Concurrent search aggregator & fire-and-forget search audit persistence
│   └── ranking.py              # Pure offer scoring & ranking engine
├── workflows/
│   └── booking_workflow.py     # Temporal BookingWorkflow orchestration & status history tracking
├── activities/
│   └── booking_activities.py   # Temporal Activities (revalidate, reserve, persist DB, poll, cancel, audit)
├── client/
│   └── booking_client.py       # CLI client for triggering/querying/cancelling workflows
├── api/
│   ├── main.py                 # FastAPI application instance & router setup
│   └── routes/
│       ├── search.py           # Search endpoints: POST /search/hotels, GET /health
│       ├── booking.py          # Booking endpoints: POST /bookings, GET /bookings/{id}, POST /bookings/{id}/cancel
│       └── admin.py            # Observability endpoints: GET /bookings/{id}/history, GET /search-requests/{id}, GET /failures
└── tests/
    ├── conftest.py             # Pytest configuration
    ├── test_atlas_adapter.py   # Unit tests for AtlasAdapter & failure modes (Step 1)
    ├── test_nova_adapter.py    # Unit tests for NovaAdapter & failure modes (Step 1)
    ├── test_normalization.py   # Schema price math & cross-supplier normalization tests (Step 1)
    ├── test_ranking.py         # Pure ranking algorithm tests (Step 2)
    ├── test_search_service.py  # Concurrency, timeout, deduplication, & failure tests (Step 2)
    ├── test_search_endpoint.py # FastAPI search endpoint validation & response tests (Step 2)
    ├── test_booking_workflow.py# Temporal workflow unit & time-skipping integration tests (Step 3)
    └── test_observability.py   # Search persistence, status history, admin API & PII audit tests (Step 4)
```

---

## Step 4 Architectural Explanations & Decisions

### 1. Fire-and-Forget vs. Awaited Persistence
- **Search Service (`search_service.py`)**: Uses **true fire-and-forget via `asyncio.create_task(_persist_search_audit_task(...))`**. The search endpoint returns `SearchResponse` immediately to the user without waiting for PostgreSQL disk I/O. Any database write failure in the background task is logged silently (`logger.error`) without affecting search API response latency or success status.
- **Booking Workflow (`booking_workflow.py`)**: Activity calls (`record_status_change_activity`, `persist_booking_record_activity`) are awaited inside workflow execution steps to ensure status transitions are persisted in sequence before moving to downstream polling or compensation steps.

### 2. Status History & Saga Compensation Tracking
- Every workflow state transition invokes `_transition_status(...)`, executing `record_status_change_activity`.
- This records a row in `booking_status_history` containing `previous_status`, `new_status`, and a human-readable `reason`.
- Transition sequence during Saga compensation: `PROCESSING` $\rightarrow$ `COMPENSATING` ("Persist DB record failed permanently after retries") $\rightarrow$ `FAILED` ("DB persist failed; supplier reservation successfully cancelled via Saga compensation").

### 3. Zero Guest PII Logging Policy
- **Definition of PII**: Guest names (`guest_name`), email addresses, phone numbers, contact details, and payment credentials.
- **Enforcement**: Log records format structural identifiers (`request_id`, `workflow_id`, `booking_id`, `supplier_id`, `supplier_reservation_id`) and status messages into JSON objects. `guest_details` is excluded from all `extra={...}` logging dicts.
- **Audit Verification**: `test_no_guest_pii_in_log_output` in `tests/test_observability.py` captures all Python `logging` stream output during workflow execution and asserts zero occurrences of guest PII strings.

---

## Running the Complete Test Suite

Run all 45 unit and integration tests across Steps 1, 2, 3, and 4:

```bash
/Users/sahebsandhu/prodt-task/.venv312/bin/pytest -v
```
