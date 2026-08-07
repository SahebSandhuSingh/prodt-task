# API Reference

This document provides complete documentation for all HTTP endpoints exposed by the Travel Search and Booking API, categorized by domain.

---

## Health Check

Service operational health monitoring endpoint.

### `GET /health`
Returns service health status.

- **Status Code**: `200 OK`
- **Request Body**: None

#### Example Response
```json
{
  "status": "healthy"
}
```

---

## Search Endpoints

Endpoints for querying, normalizing, and ranking hotel offers across integrated suppliers.

### `POST /search/hotels`
Executes a real-time, multi-supplier hotel search for a destination and date range.

- **Status Code**: `200 OK`
- **Request Schema**:
  - `destination` (string, required): City or region name (minimum length 1).
  - `check_in` (date string, required): Check-in date (`YYYY-MM-DD`).
  - `check_out` (date string, required): Check-out date (`YYYY-MM-DD`, must be strictly after `check_in`).
  - `guests` (integer, default `1`): Number of adult guests (greater than 0).
  - `rooms` (integer, default `1`): Number of rooms requested (greater than 0).

#### Real Request Example
```json
{
  "destination": "Paris",
  "check_in": "2026-09-01",
  "check_out": "2026-09-05",
  "guests": 2,
  "rooms": 1
}
```

#### Real Response Example
```json
{
  "results": [
    {
      "supplier_id": "nova",
      "property_id": "NOV-PAR-101",
      "property_name": "Nova Boutique Stay Le Marais",
      "location": "Paris",
      "room_type": "Superior Loft",
      "check_in_date": "2026-09-01",
      "check_out_date": "2026-09-05",
      "currency": "EUR",
      "base_price": 150.0,
      "taxes_and_fees": 30.0,
      "total_price": 180.0,
      "cancellation_policy": "Flexible cancellation",
      "availability_status": "available"
    },
    {
      "supplier_id": "atlas",
      "property_id": "ATL-PAR-01",
      "property_name": "Atlas Grand Hotel Paris",
      "location": "Paris",
      "room_type": "Deluxe King",
      "check_in_date": "2026-09-01",
      "check_out_date": "2026-09-05",
      "currency": "EUR",
      "base_price": 200.0,
      "taxes_and_fees": 40.0,
      "total_price": 240.0,
      "cancellation_policy": "Free cancellation up to 24 hours before check-in",
      "availability_status": "available"
    }
  ],
  "suppliers_queried": [
    "atlas",
    "nova"
  ],
  "suppliers_failed": [],
  "request_id": "197c9538-ed68-4305-a220-16531485af5c"
}
```

#### Error Responses
- **`422 Unprocessable Entity`** (Validation failure e.g. check-out before check-in):
```json
{
  "detail": [
    {
      "loc": ["body"],
      "msg": "Value error, check_out date (2026-08-31) must be strictly after check_in date (2026-09-01)",
      "type": "value_error"
    }
  ]
}
```

---

## Booking Endpoints

Endpoints for initiating, polling, and cancelling hotel booking workflows orchestrated via Temporal.

### `POST /bookings`
Triggers a new hotel booking Temporal workflow, or returns current status if the `idempotency_key` has already been submitted.

- **Status Code**: `202 Accepted`
- **Request Schema**:
  - `offer_id` (string, required): Offer identifier string.
  - `supplier_id` (string, required): Target supplier (`atlas` or `nova`).
  - `property_id` (string, required): Supplier property code.
  - `check_in_date` (date string, required): `YYYY-MM-DD`.
  - `check_out_date` (date string, required): `YYYY-MM-DD`.
  - `quoted_price` (float, required): Price quoted during search (must be > 0).
  - `currency` (string, default `"USD"`): ISO currency code.
  - `guest_name` (string, required): Primary guest name.
  - `idempotency_key` (string, required): Unique client key.

#### Real Request Example
```json
{
  "offer_id": "OFFER-atlas-ATL-PAR-01",
  "supplier_id": "atlas",
  "property_id": "ATL-PAR-01",
  "check_in_date": "2026-09-01",
  "check_out_date": "2026-09-05",
  "quoted_price": 240.0,
  "currency": "EUR",
  "guest_name": "Alice Smith",
  "idempotency_key": "e2e-test-01"
}
```

#### Real Response Example (New Request)
```json
{
  "workflow_id": "booking-e2e-test-01",
  "status": "PROCESSING",
  "message": "Booking workflow started"
}
```

#### Real Response Example (Duplicate Idempotency Key)
```json
{
  "workflow_id": "booking-e2e-test-01",
  "status": "CONFIRMED",
  "message": "Workflow already running/completed for idempotency_key",
  "details": {
    "booking_id": "BK-e2e-test-01",
    "status": "CONFIRMED",
    "current_step": "COMPLETED",
    "supplier_reservation_id": "ATL-RES-FBD82D48",
    "idempotency_key": "e2e-test-01",
    "supplier_id": "atlas",
    "cancel_requested": false
  }
}
```

---

### `GET /bookings/{workflow_id}`
Queries the current state of an ongoing or completed booking workflow from Temporal.

- **Status Code**: `200 OK`
- **Path Parameter**: `workflow_id` (e.g. `booking-e2e-test-01`).

#### Real Response Example
```json
{
  "booking_id": "BK-e2e-test-01",
  "cancel_requested": false,
  "current_step": "COMPLETED",
  "idempotency_key": "e2e-test-01",
  "status": "CONFIRMED",
  "supplier_id": "atlas",
  "supplier_reservation_id": "ATL-RES-FBD82D48"
}
```

#### Error Responses
- **`404 Not Found`** (Workflow ID does not exist):
```json
{
  "detail": "Workflow 'booking-unknown-id' not found or unreachable: workflow execution not found"
}
```

---

### `POST /bookings/{workflow_id}/cancel`
Sends an out-of-band cancellation signal to an active booking workflow.

- **Status Code**: `200 OK`
- **Path Parameter**: `workflow_id` (e.g. `booking-e2e-test-01`).
- **Request Body**: None

#### Real Response Example
```json
{
  "workflow_id": "booking-e2e-test-01",
  "message": "Cancellation signal sent to workflow"
}
```

---

## Observability & Admin Endpoints

Endpoints for auditing state transition history, retrieving search request details, and viewing system failures.

### `GET /bookings/{booking_id}/history`
Retrieves the chronological status transition audit log for a given booking.

- **Status Code**: `200 OK`
- **Path Parameter**: `booking_id` (accepts both `BK-xxx` or raw `xxx` key format).

#### Real Response Example
```json
[
  {
    "id": "63f9dcdd09cc44fda2fde1aaffa26f42",
    "booking_id": "BK-e2e-test-01",
    "previous_status": "PROCESSING",
    "new_status": "CONFIRMED",
    "reason": "Supplier confirmed reservation",
    "changed_at": "2026-08-07T11:17:12.709091+00:00"
  }
]
```

---

### `GET /search-requests/{request_id}`
Retrieves search request metadata and all normalized offers persisted for a given search UUID.

- **Status Code**: `200 OK`
- **Path Parameter**: `request_id` (UUID4).

#### Real Response Example
```json
{
  "request": {
    "request_id": "197c9538-ed68-4305-a220-16531485af5c",
    "destination": "Paris",
    "check_in": "2026-09-01",
    "check_out": "2026-09-05",
    "guests": 2,
    "rooms": 1,
    "suppliers_queried": ["atlas", "nova"],
    "suppliers_failed": [],
    "created_at": "2026-08-07T11:11:48.123456+00:00"
  },
  "offers": [
    {
      "offer_id": "OFFER-330001a322faaf48",
      "supplier_id": "nova",
      "property_id": "NOV-PAR-101",
      "property_name": "Nova Boutique Stay Le Marais",
      "location": "Paris",
      "room_type": "Superior Loft",
      "check_in_date": "2026-09-01",
      "check_out_date": "2026-09-05",
      "currency": "EUR",
      "base_price": 150.0,
      "taxes_and_fees": 30.0,
      "total_price": 180.0,
      "cancellation_policy": "Flexible cancellation",
      "availability_status": "available",
      "rank_score": 1.0
    }
  ]
}
```

#### Error Responses
- **`404 Not Found`**:
```json
{
  "detail": "Search request 'invalid-uuid' not found."
}
```

---

### `GET /failures`
Queries persisted failure log records, with optional query filtering by context or supplier.

- **Status Code**: `200 OK`
- **Query Parameters**:
  - `context` (string, optional): Filter by sub-area (e.g. `search`, `booking_workflow`, `adapter`).
  - `supplier_id` (string, optional): Filter by supplier (`atlas` or `nova`).

#### Real Response Example
```json
[
  {
    "id": "e4f8a12b90cd41ab82ef1234567890ab",
    "context": "search",
    "request_id": "89ab12cd-34ef-5678-90ab-cdef12345678",
    "booking_id": null,
    "supplier_id": "atlas",
    "error_type": "TimeoutError",
    "error_message": "Atlas API timed out after 30000ms",
    "retry_attempt_number": 1,
    "occurred_at": "2026-08-07T10:15:30.000000+00:00"
  }
]
```
