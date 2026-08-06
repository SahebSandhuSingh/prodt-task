from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import Column, DateTime, Float, String
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


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
