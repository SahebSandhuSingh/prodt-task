# Supplier Integration & Search API Layer — Architecture & Implementation Guide

## Overview

This project is a clean, isolated **Travel Booking Prototype** built in Python.

- **Step 1 — Supplier Integration Layer**: Abstract adapter layer (`SupplierAdapter`), normalized `UnifiedOffer` Pydantic model, exception hierarchy (`SupplierError`), mock APIs (`MockAtlasAPI` & `MockNovaAPI`), and dynamic `AdapterRegistry`.
- **Step 2 — Hotel Search API Layer**: FastAPI search application exposing `POST /search/hotels` and `GET /health`. Executes concurrent supplier queries, enforces timeout protection, deduplicates overlapping properties, ranks offers via a weighted composite formula, and degrades gracefully on partial or total supplier failures.

---

## Directory Structure

```
/Users/sahebsandhu/prodt-task/
├── pyproject.toml              # Build, dependencies, & pytest config
├── IMPLEMENTATION.md           # Implementation document & architectural guide
├── README.md                   # Quickstart guide
├── conftest.py                 # Root sys.path test environment configuration
├── schemas/
│   ├── offer.py                # Pydantic schema for UnifiedOffer & AvailabilityStatus (Step 1)
│   └── search.py               # SearchRequest & SearchResponse schemas (Step 2)
├── mocks/
│   ├── mock_atlas_api.py       # Simulated Atlas Hotels API (ISO dates, net/gross price)
│   └── mock_nova_api.py        # Simulated Nova Stays API (DD-MM-YYYY dates, per-night price)
├── adapters/
│   ├── base.py                 # Abstract base class SupplierAdapter
│   ├── exceptions.py           # Standardized exception hierarchy (SupplierError base)
│   ├── atlas_adapter.py        # Adapter for Atlas Hotels API
│   ├── nova_adapter.py         # Adapter for Nova Stays API
│   └── registry.py             # Supplier adapter registry and factory functions
├── services/
│   ├── search_service.py       # Concurrent search aggregator, deduplication, & timeout handling
│   └── ranking.py              # Pure offer scoring & ranking engine
├── api/
│   ├── main.py                 # FastAPI application instance & logging setup
│   └── routes/
│       └── search.py           # REST endpoints: POST /search/hotels, GET /health
└── tests/
    ├── conftest.py             # Pytest configuration
    ├── test_atlas_adapter.py   # Unit tests for AtlasAdapter & failure modes (Step 1)
    ├── test_nova_adapter.py    # Unit tests for NovaAdapter & failure modes (Step 1)
    ├── test_normalization.py   # Schema price math & cross-supplier normalization tests (Step 1)
    ├── test_ranking.py         # Pure ranking algorithm tests (Step 2)
    ├── test_search_service.py  # Concurrency, timeout, deduplication, & failure tests (Step 2)
    └── test_search_endpoint.py # FastAPI endpoint validation & response tests (Step 2)
```

---

## Step 2 Architecture & Specifications

### 1. API Schemas (`schemas/search.py`)

- **`SearchRequest`**:
  - `destination: str` (non-empty string)
  - `check_in: date`
  - `check_out: date`
  - `guests: int` ($> 0$)
  - `rooms: int` ($> 0$)
  - Model validator: Enforces `check_out > check_in` (raises HTTP 422 if invalid).

- **`SearchResponse`**:
  - `results: List[UnifiedOffer]` (ranked offers list)
  - `suppliers_queried: List[str]`
  - `suppliers_failed: List[str]`
  - `request_id: str` (UUID4 tracing identifier)

---

### 2. Search Service & Concurrency (`services/search_service.py`)

- **Concurrent Execution**: `asyncio.gather(*tasks, return_exceptions=True)` queries all registered supplier adapters concurrently.
- **Timeout Protection**: Each adapter query is bounded by `asyncio.wait_for(..., timeout=5.0)` to guarantee that hanging supplier calls never stall the request indefinitely.
- **Graceful Failure Handling**: If an adapter raises a `SupplierError`, `asyncio.TimeoutError`, or unexpected runtime exception, the error is logged using Python's standard `logging` module, the supplier ID is added to `suppliers_failed`, and execution continues with remaining suppliers. If all suppliers fail, the endpoint returns a HTTP 200 response with `results: []` and `suppliers_failed` populated.

---

### 3. Deduplication Heuristic (`services/search_service.py`)

- **Matching Heuristic**: Properties are matched using a normalized composite key:
  $$\text{Key} = (\text{normalize\_string}(\text{property\_name}), \text{normalize\_string}(\text{location}))$$
- **Selection Decision**: When duplicate properties are identified across suppliers, the **cheaper offer** (lowest `total_price`) is retained to ensure maximum value for the user.

---

### 4. Ranking Engine (`services/ranking.py`)

The ranking engine scores offers using a weighted composite formula:

$$\text{Final Score} = (0.50 \times \text{Price Score}) + (0.30 \times \text{Availability Score}) + (0.20 \times \text{Supplier Weight})$$

#### Sub-score Computation:
1. **Price Score [0.0 - 1.0]**:
   - Inverse min-max normalization:
     $$\text{Price Score} = 1.0 - \frac{\text{total\_price} - \text{min\_price}}{\text{max\_price} - \text{min\_price}}$$
   - If all prices in the result set are identical or only 1 offer exists, $\text{Price Score} = 1.0$.
2. **Availability Score [0.0 - 1.0]**:
   - `AVAILABLE` $\rightarrow 1.0$
   - `ON_REQUEST` $\rightarrow 0.7$
   - Others $\rightarrow 0.0$
3. **Supplier Weight [0.0 - 1.0]**:
   - Configurable weight lookup dictionary: Atlas ($0.90$), Nova ($0.85$), Default ($0.80$).

Results are returned sorted descending by `Final Score`.

---

### 5. Structured Logging (`api/routes/search.py` & `services/search_service.py`)

Requests and supplier errors are logged using standard Python `logging.getLogger("search_service")`.
Log entries record: `request_id`, `destination`, `check_in`, `check_out`, `suppliers_queried`, `suppliers_failed`, `raw_offers_count`, and `final_results_count`. No PII is logged.

---

## Running the Complete Test Suite

Run all Step 1 and Step 2 tests together:

```bash
/Users/sahebsandhu/prodt-task/.venv312/bin/pytest -v
```

### Coverage:
- Step 1: Normalization, adapter errors, mock failure injection, price math validation.
- Step 2: Ranking formula, search service concurrency, deduplication logic, timeout handling, FastAPI request validation (`check_out > check_in`, `guests > 0`), and HTTP response verification.
