-- Initial SQL schema setup for travel booking PostgreSQL database (Step 4 Extended)

CREATE TABLE IF NOT EXISTS bookings (
    booking_id VARCHAR(64) PRIMARY KEY,
    workflow_id VARCHAR(128) NOT NULL,
    idempotency_key VARCHAR(128) UNIQUE NOT NULL,
    supplier_id VARCHAR(32) NOT NULL,
    property_id VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    supplier_reservation_id VARCHAR(128),
    total_price DOUBLE PRECISION NOT NULL,
    currency VARCHAR(10) NOT NULL DEFAULT 'USD',
    guest_name VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS search_requests (
    request_id VARCHAR(64) PRIMARY KEY,
    destination VARCHAR(128) NOT NULL,
    check_in DATE NOT NULL,
    check_out DATE NOT NULL,
    guests INTEGER NOT NULL,
    rooms INTEGER NOT NULL,
    suppliers_queried JSONB NOT NULL,
    suppliers_failed JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS normalized_offers (
    offer_id VARCHAR(64) NOT NULL,
    request_id VARCHAR(64) NOT NULL REFERENCES search_requests(request_id) ON DELETE CASCADE,
    supplier_id VARCHAR(32) NOT NULL,
    property_id VARCHAR(64) NOT NULL,
    property_name VARCHAR(128) NOT NULL,
    location VARCHAR(128) NOT NULL,
    room_type VARCHAR(64) NOT NULL,
    check_in_date DATE NOT NULL,
    check_out_date DATE NOT NULL,
    currency VARCHAR(10) NOT NULL,
    base_price DOUBLE PRECISION NOT NULL,
    taxes_and_fees DOUBLE PRECISION NOT NULL,
    total_price DOUBLE PRECISION NOT NULL,
    cancellation_policy VARCHAR(256) NOT NULL,
    availability_status VARCHAR(32) NOT NULL,
    rank_score DOUBLE PRECISION,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (offer_id, request_id)
);

CREATE TABLE IF NOT EXISTS supplier_references (
    id VARCHAR(64) PRIMARY KEY,
    booking_id VARCHAR(64) NOT NULL REFERENCES bookings(booking_id) ON DELETE CASCADE,
    supplier_id VARCHAR(32) NOT NULL,
    supplier_reservation_id VARCHAR(128) NOT NULL,
    raw_supplier_response JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS booking_status_history (
    id VARCHAR(64) PRIMARY KEY,
    booking_id VARCHAR(64) NOT NULL REFERENCES bookings(booking_id) ON DELETE CASCADE,
    previous_status VARCHAR(32),
    new_status VARCHAR(32) NOT NULL,
    reason TEXT,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS failure_log (
    id VARCHAR(64) PRIMARY KEY,
    context VARCHAR(64) NOT NULL,
    request_id VARCHAR(64),
    booking_id VARCHAR(64),
    supplier_id VARCHAR(32),
    error_type VARCHAR(128) NOT NULL,
    error_message TEXT NOT NULL,
    retry_attempt_number INTEGER,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_bookings_workflow_id ON bookings(workflow_id);
CREATE INDEX IF NOT EXISTS idx_bookings_idempotency_key ON bookings(idempotency_key);
CREATE INDEX IF NOT EXISTS idx_normalized_offers_request_id ON normalized_offers(request_id);
CREATE INDEX IF NOT EXISTS idx_supplier_references_booking_id ON supplier_references(booking_id);
CREATE INDEX IF NOT EXISTS idx_booking_status_history_booking_id ON booking_status_history(booking_id);
CREATE INDEX IF NOT EXISTS idx_failure_log_request_id ON failure_log(request_id);
CREATE INDEX IF NOT EXISTS idx_failure_log_booking_id ON failure_log(booking_id);
