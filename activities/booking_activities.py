from datetime import date, datetime, timezone
import logging
import uuid
from typing import Any, Dict, Optional

from temporalio import activity
from sqlalchemy.future import select

from adapters.exceptions import SupplierPriceChangedError, SupplierError
from adapters.registry import registry
from db.models import (
    BookingRecord,
    BookingStatusHistoryRecord,
    FailureLogRecord,
    SupplierReferenceRecord,
)
from db.session import AsyncSessionLocal
from schemas.offer import AvailabilityStatus, UnifiedOffer

logger = logging.getLogger("booking_activities")
PRICE_DRIFT_THRESHOLD: float = 0.05


@activity.defn
async def revalidate_offer_activity(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Activity 1: Revalidate pricing and availability with the supplier.
    """
    supplier_id = payload["supplier_id"]
    property_id = payload["property_id"]
    check_in = date.fromisoformat(payload["check_in_date"])
    check_out = date.fromisoformat(payload["check_out_date"])
    quoted_price = float(payload["quoted_price"])

    adapter = registry.get(supplier_id)
    try:
        current_offer = await adapter.get_pricing_and_availability(
            property_id=property_id,
            check_in=check_in,
            check_out=check_out
        )
        new_price = current_offer.total_price
        drift = abs(new_price - quoted_price) / quoted_price if quoted_price > 0 else 0.0
        exceeded = drift > PRICE_DRIFT_THRESHOLD

        return {
            "valid": True,
            "new_price": new_price,
            "price_drift": drift,
            "price_changed_exceeded": exceeded,
            "availability_status": current_offer.availability_status.value
        }
    except SupplierPriceChangedError as e:
        drift = abs(e.new_price - e.old_price) / e.old_price if e.old_price > 0 else 0.10
        return {
            "valid": False,
            "new_price": e.new_price,
            "price_drift": drift,
            "price_changed_exceeded": True,
            "availability_status": AvailabilityStatus.AVAILABLE.value
        }


@activity.defn
async def create_supplier_reservation_activity(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Activity 2: Book reservation with supplier adapter using idempotency token.
    """
    supplier_id = payload["supplier_id"]
    property_id = payload["property_id"]
    check_in = date.fromisoformat(payload["check_in_date"])
    check_out = date.fromisoformat(payload["check_out_date"])
    total_price = float(payload["total_price"])
    currency = payload.get("currency", "USD")
    guest_details = payload.get("guest_details", {"name": "Guest"})
    idempotency_key = payload.get("idempotency_key")

    dummy_offer = UnifiedOffer(
        supplier_id=supplier_id,
        property_id=property_id,
        property_name="Stay Property",
        location="Location",
        room_type="Standard Room",
        check_in_date=check_in,
        check_out_date=check_out,
        currency=currency,
        base_price=total_price * 0.8,
        taxes_and_fees=total_price * 0.2,
        total_price=total_price,
        cancellation_policy="Standard",
        availability_status=AvailabilityStatus.AVAILABLE
    )

    adapter = registry.get(supplier_id)
    return await adapter.create_reservation(
        offer=dummy_offer,
        guest_details=guest_details,
        idempotency_key=idempotency_key
    )


@activity.defn
async def persist_booking_record_activity(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Activity 3: Write or update the booking record in PostgreSQL DB.
    """
    booking_id = payload.get("booking_id") or f"BK-{uuid.uuid4().hex[:8].upper()}"
    workflow_id = payload["workflow_id"]
    idempotency_key = payload["idempotency_key"]
    supplier_id = payload["supplier_id"]
    property_id = payload["property_id"]
    status = payload["status"]
    supplier_res_id = payload.get("supplier_reservation_id")
    total_price = float(payload["total_price"])
    currency = payload.get("currency", "USD")
    guest_name = payload.get("guest_name", "Guest")

    async with AsyncSessionLocal() as session:
        stmt = select(BookingRecord).where(BookingRecord.idempotency_key == idempotency_key)
        res = await session.execute(stmt)
        record = res.scalar_one_or_none()

        if record:
            record.status = status
            record.supplier_reservation_id = supplier_res_id
            record.updated_at = datetime.now(timezone.utc)
        else:
            record = BookingRecord(
                booking_id=booking_id,
                workflow_id=workflow_id,
                idempotency_key=idempotency_key,
                supplier_id=supplier_id,
                property_id=property_id,
                status=status,
                supplier_reservation_id=supplier_res_id,
                total_price=total_price,
                currency=currency,
                guest_name=guest_name,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            )
            session.add(record)

        await session.commit()
        return record.to_dict()


@activity.defn
async def poll_supplier_confirmation_activity(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Activity 4: Query current status of reservation from supplier.
    """
    supplier_id = payload["supplier_id"]
    supplier_res_id = payload["supplier_reservation_id"]

    adapter = registry.get(supplier_id)
    return await adapter.get_reservation_status(supplier_res_id)


@activity.defn
async def cancel_supplier_reservation_activity(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Activity 5: Undo/cancel supplier reservation (Saga compensation).
    """
    supplier_id = payload["supplier_id"]
    supplier_res_id = payload["supplier_reservation_id"]

    adapter = registry.get(supplier_id)
    return await adapter.cancel_reservation(supplier_res_id)


@activity.defn
async def record_status_change_activity(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Step 4 Activity: Write a status history audit record for every workflow state transition.
    """
    booking_id = payload["booking_id"]
    previous_status = payload.get("previous_status")
    new_status = payload["new_status"]
    reason = payload.get("reason", "")

    try:
        async with AsyncSessionLocal() as session:
            history_record = BookingStatusHistoryRecord(
                booking_id=booking_id,
                previous_status=previous_status,
                new_status=new_status,
                reason=reason,
                changed_at=datetime.now(timezone.utc)
            )
            session.add(history_record)
            await session.commit()
            return {"status": "persisted", "history_id": history_record.id}
    except Exception as e:
        logger.error(f"Failed to record status change for booking '{booking_id}': {e}")
        return {"status": "failed", "error": str(e)}


@activity.defn
async def record_supplier_reference_activity(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Step 4 Activity: Persist raw supplier response details for audit trail.
    """
    booking_id = payload["booking_id"]
    supplier_id = payload["supplier_id"]
    supplier_res_id = payload["supplier_reservation_id"]
    raw_response = payload.get("raw_supplier_response", {})

    try:
        async with AsyncSessionLocal() as session:
            ref_record = SupplierReferenceRecord(
                booking_id=booking_id,
                supplier_id=supplier_id,
                supplier_reservation_id=supplier_res_id,
                raw_supplier_response=raw_response,
                created_at=datetime.now(timezone.utc)
            )
            session.add(ref_record)
            await session.commit()
            return {"status": "persisted", "ref_id": ref_record.id}
    except Exception as e:
        logger.error(f"Failed to record supplier reference for booking '{booking_id}': {e}")
        return {"status": "failed", "error": str(e)}


@activity.defn
async def record_failure_log_activity(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Step 4 Activity: Write an activity or workflow failure event record.
    """
    context = payload.get("context", "booking_workflow")
    request_id = payload.get("request_id")
    booking_id = payload.get("booking_id")
    supplier_id = payload.get("supplier_id")
    error_type = payload["error_type"]
    error_message = payload["error_message"]
    retry_attempt = payload.get("retry_attempt_number", 1)

    try:
        async with AsyncSessionLocal() as session:
            fail_record = FailureLogRecord(
                context=context,
                request_id=request_id,
                booking_id=booking_id,
                supplier_id=supplier_id,
                error_type=error_type,
                error_message=error_message,
                retry_attempt_number=retry_attempt,
                occurred_at=datetime.now(timezone.utc)
            )
            session.add(fail_record)
            await session.commit()
            return {"status": "persisted", "failure_id": fail_record.id}
    except Exception as e:
        logger.error(f"Failed to write failure log: {e}")
        return {"status": "failed", "error": str(e)}
