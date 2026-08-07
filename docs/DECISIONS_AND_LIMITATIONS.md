# Key Engineering Decisions & System Limitations

This document outlines the primary engineering decisions made during the design and implementation of the travel booking engine, followed by an explicit breakdown of current system assumptions and limitations.

---

## Key Engineering Decisions

### 1. Adapter Pattern for Supplier Integration
We chose the **Adapter Pattern** to encapsulate vendor-specific API interactions behind a unified interface (`SupplierAdapter`). External hotel suppliers differ significantly in date formats (`YYYY-MM-DD` vs `DD-MM-YYYY`), pricing breakdowns (`net_amount` + `tax_and_service` vs `nightlyBase` + `surcharges`), and field naming (`dest_city` vs `locationName`).

Translating vendor data into a single `UnifiedOffer` schema at the edge ensures that internal search logic, deduplication, composite ranking, and booking workflows operate on clean, standardized entities. Adding a new supplier requires writing a new adapter class in `adapters/` and registering it in `adapters/registry.py` without modifying core business services.

### 2. Concurrent Search & Partial-Failure Isolation
Supplier search calls are executed concurrently using `asyncio.gather(*tasks, return_exceptions=True)`. Each supplier search is wrapped in an `asyncio.wait_for` timeout enforcing a strict 5.0-second limit.

If a supplier times out, throws a 500 error, or returns malformed JSON, `return_exceptions=True` catches the exception as an object rather than letting it crash the entire search request. The failed supplier is appended to `suppliers_failed`, a failure log is queued, and available results from healthy suppliers are returned to the user.

### 3. Property Deduplication Heuristic
When multiple suppliers list the same physical hotel property, we deduplicate offers using a composite key: `(normalized_property_name, normalized_location)`. String normalization strips punctuation, lowercases characters, and compresses whitespace (`_normalize_string()`).

When duplicate properties are detected, we retain the offer with the lowest `total_price` to ensure optimal value for the customer.

*Known Imprecision*: This heuristic relies on exact normalized string matching. If Atlas names a hotel `"Atlas Grand Hotel Paris"` while Nova lists it as `"Grand Atlas Hotel Le Marais"`, the heuristic will treat them as distinct properties. A production system would use geo-coordinates (latitude/longitude) or standard GIS property IDs (e.g. GIATA codes) for matching.

### 4. Ranking Formula Weights
Search offers are ranked using a normalized composite score calculated in `services/ranking.py`:

$$\text{Final Score} = (0.50 \times \text{Price Score}) + (0.30 \times \text{Availability Score}) + (0.20 \times \text{Supplier Confidence Score})$$

- **Price Score (50%)**: Calculated via inverted min-max normalization ($1.0 - \frac{\text{price} - \text{min}}{\text{max} - \text{min}}$) so that cheaper offers score closer to 1.0.
- **Availability Score (30%)**: Assigns 1.0 to immediately `AVAILABLE` rooms, 0.7 to `ON_REQUEST` rooms, and 0.0 to `UNAVAILABLE`/`SOLD_OUT` rooms.
- **Supplier Confidence Score (20%)**: Uses static historical confidence weights derived from vendor reliability metrics (Atlas: 0.90, Nova: 0.85, default: 0.80).

These weights prioritize lower consumer prices while accounting for room confirmation certainty and supplier reliability.

### 5. Temporal Workflow Orchestration over Custom Try/Except Loops
Hotel bookings require multi-step stateful execution: price revalidation, supplier reservation, internal database persistence, and polling for confirmation. Hand-rolled retry loops in application code suffer from catastrophic failure modes: if the application process restarts or crashes mid-booking, the state is lost, leading to orphaned supplier reservations or un-billed bookings.

Temporal provides durable execution. Every activity result and state transition is recorded to Temporal's event history. If a worker process crashes, another worker picks up the workflow at the exact point of failure. Temporal also natively handles Saga compensations (automatic rollback of completed steps on failure) and async signals (cancellations).

### 6. Workflow ID & Idempotency Strategy
Client booking requests must include an `idempotency_key` (e.g. `b-m5v8ikm`). We construct the Temporal workflow ID directly from this key:

$$\text{workflow\_id} = \text{\`booking-\$\{idempotency\_key\}\`}$$

Temporal guarantees that a workflow ID is unique per namespace. If a client submits a duplicate request (e.g. due to a network retry), Temporal raises a `WorkflowAlreadyStartedError`. FastAPI catches this error and returns a `202 Accepted` response containing the existing handle's status without re-executing any workflow steps or creating duplicate supplier bookings.

The internal database primary key uses `booking_id = f"BK-{idempotency_key[:12]}"` to remain compatible with strict string length constraints across audit log tables.

### 7. Saga Compensation Design & `REQUIRES_MANUAL_REVIEW`
The `BookingWorkflow` implements the Saga pattern to handle multi-step rollbacks:

1. If `persist_booking_record_activity` (Step 3) fails permanently after 3 retry attempts, the workflow enters the compensation phase and executes `cancel_supplier_reservation_activity`.
2. If cancellation succeeds, the booking status transitions to `FAILED` with reason *"DB persist failed; supplier reservation successfully cancelled via Saga compensation"*.
3. If supplier cancellation **also fails**, the workflow transitions to `REQUIRES_MANUAL_REVIEW`. This state flags an inconsistent condition (supplier room reserved, but internal DB or cancellation failed) for human operator triage.

### 8. Fire-and-Forget vs. Awaited Persistence
We deliberately applied two different persistence strategies based on service requirements:

- **Search Service (Fire-and-Forget)**: Search latency is critical. Persisting search request logs and normalized offers to PostgreSQL is performed via a background task (`asyncio.create_task()`). To prevent Python's garbage collector from destroying unreferenced tasks mid-execution, we store strong references in a module-level `_background_tasks` set.
- **Booking Workflow (Awaited In-Saga)**: Booking records require transactional guarantee. Persistence is executed as an explicit workflow activity (`persist_booking_record_activity`) with retries and compensation.

### 9. Price Representation (`float` vs. `Decimal`)
Prices are represented using Python `float` types in models and Pydantic schemas for prototype simplicity.

*Production Limitation*: Floating-point arithmetic introduces rounding inaccuracies (e.g. `0.1 + 0.2 = 0.30000000000000004`). In a production financial or booking system, prices must be stored as `Decimal` types or as integer amounts in the smallest currency unit (e.g., cents/pence).

### 10. `run.sh` vs. `docker-compose.yml` Environment Tradeoff
The codebase provides two startup mechanisms:
- **`run.sh`**: Runs PostgreSQL and Temporal server inside Docker containers while executing FastAPI and the Temporal Worker locally inside a Virtualenv (`.venv312`). This accelerates development iteration.
- **`docker-compose.yml`**: Containerizes all services (PostgreSQL, Temporal, API, and Worker). In `docker-compose.yml`, the Temporal service uses `temporalio/auto-setup:latest`, which automatically initializes the Temporal default namespace (`default`) upon startup.

---

## Assumptions & Known Limitations

### 1. Mock Supplier City Coverage
The mock supplier implementations hardcode specific cities in their internal inventories:
- **Mock Atlas API**:
  - `ATL-PAR-01`: Paris ("Atlas Grand Hotel Paris")
  - `ATL-NYC-02`: New York ("Atlas Manhattan Suites")
  - `ATL-TYO-03`: Tokyo ("Atlas Tokyo Bay Resort")
- **Mock Nova API**:
  - `NOV-PAR-101`: Paris ("Nova Boutique Stay Le Marais")
  - `NOV-LON-202`: London ("Nova Covent Garden Apartments")
  - `NOV-SYD-303`: Sydney ("Nova Harbour View Villas")

Searching for `"Paris"` queries both suppliers. Searching for `"London"` returns only Nova results, while searching for `"Tokyo"` returns only Atlas results. Searching for an unlisted city (e.g. `"Rome"`) returns an empty result set.

### 2. Lack of Authentication & Authorization
All API endpoints (`/search/hotels`, `/bookings`, `/bookings/{id}/history`, `/failures`) are public. There is no user authentication, JWT verification, or role-based access control (RBAC). Admin and audit endpoints are exposed without restriction.

### 3. Simulated Payment Processing
The booking workflow assumes payment authorization is handled downstream or out-of-band. The workflow validates offer prices and reserves rooms with suppliers, but does not interact with a payment gateway (e.g. Stripe).

### 4. Deduplication String Matching Limits
As noted in Decision #3, deduplication uses string normalization (`normalized_property_name`, `normalized_location`). Variations in hotel names or locations across suppliers (e.g. `"Hilton Paris"` vs `"Hilton Paris Charles de Gaulle"`) will bypass deduplication and render as two separate property cards.

### 5. Single-Session Frontend Demo Layer
The web interface served at `http://localhost:8000/` is a functional single-page application built using vanilla HTML/CSS/JavaScript without a front-end framework or build bundler. Booking history in the "My Bookings" tab is persisted in the browser's `localStorage`. Clearing browser data clears the client-side booking list (though records remain in PostgreSQL).
