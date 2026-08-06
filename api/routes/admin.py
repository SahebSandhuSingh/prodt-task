from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy.future import select

from db.models import (
    BookingStatusHistoryRecord,
    FailureLogRecord,
    NormalizedOfferRecord,
    SearchRequestRecord,
)
from db.session import AsyncSessionLocal

router = APIRouter(prefix="", tags=["Observability & Admin"])


@router.get("/bookings/{booking_id}/history")
async def get_booking_history(booking_id: str) -> List[Dict[str, Any]]:
    """
    Retrieve status transition audit history for a booking, ordered chronologically.
    """
    async with AsyncSessionLocal() as session:
        stmt = (
            select(BookingStatusHistoryRecord)
            .where(
                (BookingStatusHistoryRecord.booking_id == booking_id) |
                (BookingStatusHistoryRecord.booking_id == f"BK-{booking_id}")
            )
            .order_by(BookingStatusHistoryRecord.changed_at.asc())
        )
        res = await session.execute(stmt)
        records = res.scalars().all()

        return [
            {
                "id": r.id,
                "booking_id": r.booking_id,
                "previous_status": r.previous_status,
                "new_status": r.new_status,
                "reason": r.reason,
                "changed_at": r.changed_at.isoformat() if r.changed_at else None,
            }
            for r in records
        ]


@router.get("/search-requests/{request_id}")
async def get_search_request_details(request_id: str) -> Dict[str, Any]:
    """
    Retrieve search request metadata and its associated normalized offers.
    """
    async with AsyncSessionLocal() as session:
        # Query search request
        req_stmt = select(SearchRequestRecord).where(SearchRequestRecord.request_id == request_id)
        req_res = await session.execute(req_stmt)
        req_record = req_res.scalar_one_or_none()

        if not req_record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Search request '{request_id}' not found."
            )

        # Query normalized offers
        offer_stmt = (
            select(NormalizedOfferRecord)
            .where(NormalizedOfferRecord.request_id == request_id)
            .order_by(NormalizedOfferRecord.rank_score.desc())
        )
        offer_res = await session.execute(offer_stmt)
        offer_records = offer_res.scalars().all()

        return {
            "request": {
                "request_id": req_record.request_id,
                "destination": req_record.destination,
                "check_in": req_record.check_in.isoformat(),
                "check_out": req_record.check_out.isoformat(),
                "guests": req_record.guests,
                "rooms": req_record.rooms,
                "suppliers_queried": req_record.suppliers_queried,
                "suppliers_failed": req_record.suppliers_failed,
                "created_at": req_record.created_at.isoformat() if req_record.created_at else None,
            },
            "offers": [
                {
                    "offer_id": o.offer_id,
                    "supplier_id": o.supplier_id,
                    "property_id": o.property_id,
                    "property_name": o.property_name,
                    "location": o.location,
                    "room_type": o.room_type,
                    "check_in_date": o.check_in_date.isoformat(),
                    "check_out_date": o.check_out_date.isoformat(),
                    "currency": o.currency,
                    "base_price": o.base_price,
                    "taxes_and_fees": o.taxes_and_fees,
                    "total_price": o.total_price,
                    "cancellation_policy": o.cancellation_policy,
                    "availability_status": o.availability_status,
                    "rank_score": o.rank_score,
                }
                for o in offer_records
            ]
        }


@router.get("/failures")
async def get_failure_logs(
    context: Optional[str] = Query(None, description="Filter by context e.g. search, booking_workflow"),
    supplier_id: Optional[str] = Query(None, description="Filter by supplier_id")
) -> List[Dict[str, Any]]:
    """
    Retrieve failure log records, optionally filtered by context or supplier.
    """
    async with AsyncSessionLocal() as session:
        stmt = select(FailureLogRecord).order_by(FailureLogRecord.occurred_at.desc())
        if context:
            stmt = stmt.where(FailureLogRecord.context == context)
        if supplier_id:
            stmt = stmt.where(FailureLogRecord.supplier_id == supplier_id)

        res = await session.execute(stmt)
        records = res.scalars().all()

        return [
            {
                "id": r.id,
                "context": r.context,
                "request_id": r.request_id,
                "booking_id": r.booking_id,
                "supplier_id": r.supplier_id,
                "error_type": r.error_type,
                "error_message": r.error_message,
                "retry_attempt_number": r.retry_attempt_number,
                "occurred_at": r.occurred_at.isoformat() if r.occurred_at else None,
            }
            for r in records
        ]
