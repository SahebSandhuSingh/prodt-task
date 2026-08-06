from datetime import datetime, timezone
import hashlib
import uuid
from typing import Any, Dict, Optional
from sqlalchemy import Column, Date, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def generate_deterministic_offer_id(
    supplier_id: str,
    property_id: str,
    room_type: str,
    check_in_date: Any,
    check_out_date: Any
) -> str:
    """
    Generate a deterministic SHA-256 offer_id hash derived from property, dates, and supplier.
    Enables cross-search tracking and repeat offer detection across search requests.
    """
    raw_key = f"{supplier_id.lower()}:{property_id.lower()}:{room_type.lower()}:{str(check_in_date)}:{str(check_out_date)}"
    return f"OFFER-{hashlib.sha256(raw_key.encode('utf-8')).hexdigest()[:16]}"


class BookingRecord(Base):
    """
    PostgreSQL SQLAlchemy ORM model for persisting hotel booking records.
    """
    __tablename__ = "bookings"

    booking_id = Column(String(64), primary_key=True, index=True)
    workflow_id = Column(String(128), index=True, nullable=False)
    idempotency_key = Column(String(128), unique=True, index=True, nullable=False)
    supplier_id = Column(String(32), nullable=False)
    property_id = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False)  # CONFIRMED, FAILED, CANCELLED, PRICE_CHANGED, REQUIRES_MANUAL_REVIEW
    supplier_reservation_id = Column(String(128), nullable=True)
    total_price = Column(Float, nullable=False)  # Documented limitation: float used for prototype simplicity
    currency = Column(String(10), nullable=False, default="USD")
    guest_name = Column(String(128), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "booking_id": self.booking_id,
            "workflow_id": self.workflow_id,
            "idempotency_key": self.idempotency_key,
            "supplier_id": self.supplier_id,
            "property_id": self.property_id,
            "status": self.status,
            "supplier_reservation_id": self.supplier_reservation_id,
            "total_price": self.total_price,
            "currency": self.currency,
            "guest_name": self.guest_name,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class SearchRequestRecord(Base):
    """
    Persisted search request metadata.
    """
    __tablename__ = "search_requests"

    request_id = Column(String(64), primary_key=True, index=True)
    destination = Column(String(128), nullable=False)
    check_in = Column(Date, nullable=False)
    check_out = Column(Date, nullable=False)
    guests = Column(Integer, nullable=False)
    rooms = Column(Integer, nullable=False)
    suppliers_queried = Column(JSON, nullable=False)
    suppliers_failed = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class NormalizedOfferRecord(Base):
    """
    Persisted search offers normalized and ranked for search requests.
    """
    __tablename__ = "normalized_offers"

    offer_id = Column(String(64), primary_key=True, index=True)
    request_id = Column(String(64), ForeignKey("search_requests.request_id"), index=True, nullable=False)
    supplier_id = Column(String(32), nullable=False)
    property_id = Column(String(64), nullable=False)
    property_name = Column(String(128), nullable=False)
    location = Column(String(128), nullable=False)
    room_type = Column(String(64), nullable=False)
    check_in_date = Column(Date, nullable=False)
    check_out_date = Column(Date, nullable=False)
    currency = Column(String(10), nullable=False)
    base_price = Column(Float, nullable=False)
    taxes_and_fees = Column(Float, nullable=False)
    total_price = Column(Float, nullable=False)
    cancellation_policy = Column(String(256), nullable=False)
    availability_status = Column(String(32), nullable=False)
    rank_score = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class SupplierReferenceRecord(Base):
    """
    Persisted raw supplier response payloads for debugging and audit trail.
    """
    __tablename__ = "supplier_references"

    id = Column(String(64), primary_key=True, default=lambda: uuid.uuid4().hex)
    booking_id = Column(String(64), ForeignKey("bookings.booking_id"), index=True, nullable=False)
    supplier_id = Column(String(32), nullable=False)
    supplier_reservation_id = Column(String(128), nullable=False)
    raw_supplier_response = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class BookingStatusHistoryRecord(Base):
    """
    Audit log of all booking status state transitions.
    """
    __tablename__ = "booking_status_history"

    id = Column(String(64), primary_key=True, default=lambda: uuid.uuid4().hex)
    booking_id = Column(String(64), ForeignKey("bookings.booking_id"), index=True, nullable=False)
    previous_status = Column(String(32), nullable=True)
    new_status = Column(String(32), nullable=False)
    reason = Column(Text, nullable=True)
    changed_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class FailureLogRecord(Base):
    """
    Audit log for supplier and workflow activity failure events.
    """
    __tablename__ = "failure_log"

    id = Column(String(64), primary_key=True, default=lambda: uuid.uuid4().hex)
    context = Column(String(64), nullable=False)  # "search", "booking_workflow", "adapter"
    request_id = Column(String(64), index=True, nullable=True)
    booking_id = Column(String(64), index=True, nullable=True)
    supplier_id = Column(String(32), nullable=True)
    error_type = Column(String(128), nullable=False)
    error_message = Column(Text, nullable=False)
    retry_attempt_number = Column(Integer, nullable=True)
    occurred_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
