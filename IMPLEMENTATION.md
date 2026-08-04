# Supplier Integration Layer — Implementation & Architecture Guide

## Overview

The **Supplier Integration Layer** is an isolated Python module designed to normalize data and interaction flows across heterogeneous hotel supply partners (such as Atlas Hotels and Nova Stays). It abstracts differences in field names, pricing structures, date formats, and error conditions into a unified internal representation (`UnifiedOffer`) and standardized exception hierarchy.

---

## Directory Structure

```
/Users/sahebsandhu/prodt-task/
├── pyproject.toml              # Build & pytest setup (asyncio_mode = "auto")
├── IMPLEMENTATION.md           # Implementation document & architectural guide
├── README.md                   # Quickstart guide
├── schemas/
│   └── offer.py                # Pydantic schema for UnifiedOffer & AvailabilityStatus
├── mocks/
│   ├── mock_atlas_api.py       # Simulated Atlas Hotels API (ISO dates, net/gross price)
│   └── mock_nova_api.py        # Simulated Nova Stays API (DD-MM-YYYY dates, per-night price)
├── adapters/
│   ├── base.py                 # Abstract base class SupplierAdapter
│   ├── exceptions.py           # Standardized exception hierarchy (SupplierError base)
│   ├── atlas_adapter.py        # Adapter for Atlas Hotels API
│   ├── nova_adapter.py         # Adapter for Nova Stays API
│   └── registry.py             # Supplier adapter registry and factory functions
└── tests/
    ├── test_atlas_adapter.py   # Unit tests for AtlasAdapter & failure modes
    ├── test_nova_adapter.py    # Unit tests for NovaAdapter & failure modes
    └── test_normalization.py   # Schema price math & cross-supplier normalization tests
```

---

## 1. Unified Internal Schema (`schemas/offer.py`)

The `UnifiedOffer` Pydantic model normalizes all supplier-specific stay quotes into a common format:

```python
class UnifiedOffer(BaseModel):
    supplier_id: str
    property_id: str
    property_name: str
    location: str
    room_type: str
    check_in_date: date
    check_out_date: date
    currency: str
    base_price: float
    taxes_and_fees: float
    total_price: float
    cancellation_policy: str
    availability_status: AvailabilityStatus
```

### Price Validation Rule
The model includes a `@model_validator(mode="after")` that enforces mathematical consistency:
$$\text{total\_price} = \text{round}(\text{base\_price} + \text{taxes\_and\_fees}, 2)$$
If a supplier payload violates this contract, a Pydantic `ValidationError` is raised immediately.

---

## 2. Standardized Exceptions (`adapters/exceptions.py`)

All supplier-specific runtime errors, HTTP status codes, socket timeouts, and parsing failures are mapped into normalized exceptions derived from `SupplierError`:

- `SupplierError(Exception)` — Base exception carrying `supplier_id` and optional `original_error`.
  - `SupplierTimeoutError` — Raised when a supplier call exceeds timeout limits.
  - `SupplierServerError` — Raised on supplier 5xx internal server errors.
  - `SupplierMalformedResponseError` — Raised when a response lacks required fields or has incompatible types.
  - `SupplierPriceChangedError` — Raised during pricing re-checks if the total quote has changed (`old_price` vs `new_price`).
  - `SupplierNotFoundError` — Raised when a property or reservation ID is not found.
  - `SupplierBookingError` — Raised when reservation creation or cancellation fails.

---

## 3. Abstract Base Adapter (`adapters/base.py`)

All concrete adapters inherit from `SupplierAdapter(ABC)` and implement five core asynchronous methods:

```python
class SupplierAdapter(ABC):
    @property
    @abstractmethod
    def supplier_id(self) -> str: pass

    @abstractmethod
    async def search_properties(self, destination: str, check_in: date, check_out: date, guests: int = 1, rooms: int = 1) -> List[UnifiedOffer]: pass

    @abstractmethod
    async def get_pricing_and_availability(self, property_id: str, check_in: date, check_out: date, guests: int = 1, rooms: int = 1, room_type: Optional[str] = None) -> UnifiedOffer: pass

    @abstractmethod
    async def create_reservation(self, offer: UnifiedOffer, guest_details: Dict[str, Any]) -> Dict[str, Any]: pass

    @abstractmethod
    async def get_reservation_status(self, reservation_id: str) -> Dict[str, Any]: pass

    @abstractmethod
    async def cancel_reservation(self, reservation_id: str) -> Dict[str, Any]: pass
```

### Standardized Reservation Response Format

To ensure consistent integration across suppliers, reservation methods return standard dictionary contracts:

1. **`create_reservation(...)`**:
   ```json
   {
     "reservation_id": "ATL-RES-A1B2C3D4",
     "supplier_id": "atlas",
     "property_id": "ATL-PAR-01",
     "status": "confirmed",
     "total_price": 240.0,
     "currency": "EUR",
     "guest_name": "Alice Smith",
     "confirmation_code": "PIN123",
     "created_at": "2026-08-05T00:00:00Z"
   }
   ```
2. **`get_reservation_status(...)`**:
   ```json
   {
     "reservation_id": "ATL-RES-A1B2C3D4",
     "supplier_id": "atlas",
     "property_id": "ATL-PAR-01",
     "status": "confirmed",
     "guest_name": "Alice Smith",
     "updated_at": "2026-08-05T00:00:00Z"
   }
   ```
3. **`cancel_reservation(...)`**:
   ```json
   {
     "reservation_id": "ATL-RES-A1B2C3D4",
     "supplier_id": "atlas",
     "status": "cancelled",
     "cancellation_code": "ATL-CNL-998877",
     "refund_amount": 240.0,
     "cancelled_at": "2026-08-05T00:00:00Z"
   }
   ```

---

## 4. Supplier Mocks (`mocks/`)

### `MockAtlasAPI` (`mocks/mock_atlas_api.py`)
- **Date Format**: ISO 8601 strings (`YYYY-MM-DD`).
- **Pricing Payload**: Nested `price_breakdown` (`net_amount`, `tax_and_service`, `gross_amount`, `currency_code`).
- **Policy Enum**: `FREE_CANCEL_24H`, `NON_REFUNDABLE_ATLAS`.
- **Constructor Injection**: Accepts `simulated_failure: str | None = None` (`"timeout"`, `"500_error"`, `"malformed"`, `"price_changed"`).

### `MockNovaAPI` (`mocks/mock_nova_api.py`)
- **Date Format**: Custom European format (`DD-MM-YYYY`).
- **Pricing Payload**: Per-night base calculation (`nightlyBase * nights + surcharges`).
- **Policy Enum**: `FLEXIBLE_CANCEL`, `NON_REFUNDABLE_NOVA`.
- **Constructor Injection**: Accepts `simulated_failure: str | None = None` (`"timeout"`, `"500_error"`, `"malformed"`, `"price_changed"`).

---

## 5. Adapter Registry (`adapters/registry.py`)

The `AdapterRegistry` manages supplier instances dynamically using a dictionary mapping `supplier_id -> SupplierAdapter`.

```python
from adapters.registry import get_adapter, register_adapter

# Fetch pre-registered adapters
atlas_adapter = get_adapter("atlas")
nova_adapter = get_adapter("nova")

# Adding a 3rd supplier later requires 0 edits to existing adapters:
# register_adapter(AcmeAdapter())
```

---

## 6. Running Unit Tests

Unit tests are written using `pytest` and `pytest-asyncio` with `asyncio_mode = "auto"`.

### Test Execution Command
```bash
pytest -v tests/
```

### Verified Test Cases
1. `test_atlas_adapter.py`:
   - Search normalization to `UnifiedOffer`
   - Price re-check and booking flow
   - Standardized exception mapping for timeout, 500 error, malformed response, and price change
2. `test_nova_adapter.py`:
   - `DD-MM-YYYY` date conversion and per-night price computation
   - Booking, status lookup, and void/cancellation flow
   - Exception mapping for all simulated failure modes
3. `test_normalization.py`:
   - Pydantic price total validator assertion (`base_price + taxes_and_fees == total_price`)
   - Invalid price total rejection check
   - Multi-supplier search aggregation uniformity
   - Adapter registry lookup and error handling

---

## Key Design Decisions & Assumptions

1. **Constructor Failure Injection**:
   Rather than relying on environment variables (which introduce global state side-effects during concurrent test runs), mock failure modes are injected directly into the mock API constructors (`MockAtlasAPI(simulated_failure="timeout")`).
2. **Explicit Price Math Validation**:
   `UnifiedOffer` enforces floating point price consistency via Pydantic model validation (`round(base_price + taxes_and_fees, 2) == round(total_price, 2)`).
3. **Normalized Date Objects**:
   All internal search and offer models use Python `datetime.date` objects. Date formatting logic (ISO for Atlas, `DD-MM-YYYY` for Nova) is entirely isolated within each adapter.
4. **Decoupled Architecture**:
   None of the adapter code imports from another supplier adapter or leaks supplier-specific fields into `schemas/` or `base.py`.
