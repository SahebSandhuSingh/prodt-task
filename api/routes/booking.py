from datetime import date
from typing import Any, Dict
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
import os

from temporalio.client import Client
from temporalio.exceptions import WorkflowAlreadyStartedError
from workflows.booking_workflow import BookingRequest, BookingWorkflow

router = APIRouter(prefix="/bookings", tags=["Bookings"])
TEMPORAL_HOST = os.getenv("TEMPORAL_HOST", "localhost:7233")
TASK_QUEUE = "booking-task-queue"


class BookingRequestPayload(BaseModel):
    offer_id: str
    supplier_id: str
    property_id: str
    check_in_date: date
    check_out_date: date
    quoted_price: float = Field(..., gt=0)
    currency: str = "USD"
    guest_name: str
    idempotency_key: str = Field(..., min_length=1)


async def get_temporal_client() -> Client:
    temporal_host = os.getenv("TEMPORAL_HOST", "localhost:7233")
    return await Client.connect(temporal_host)


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_booking(payload: BookingRequestPayload) -> Dict[str, Any]:
    """
    Trigger a new hotel booking workflow or return status of existing idempotency_key workflow.
    """
    workflow_id = f"booking-{payload.idempotency_key}"
    booking_req = BookingRequest(
        offer_id=payload.offer_id,
        supplier_id=payload.supplier_id,
        property_id=payload.property_id,
        check_in_date=payload.check_in_date.isoformat(),
        check_out_date=payload.check_out_date.isoformat(),
        quoted_price=payload.quoted_price,
        currency=payload.currency,
        guest_details={"name": payload.guest_name},
        idempotency_key=payload.idempotency_key
    )

    try:
        client = await get_temporal_client()
        handle = await client.start_workflow(
            BookingWorkflow.run,
            booking_req,
            id=workflow_id,
            task_queue=TASK_QUEUE
        )
        return {
            "workflow_id": handle.id,
            "status": "PROCESSING",
            "message": "Booking workflow started"
        }
    except WorkflowAlreadyStartedError:
        # Handle duplicate start cleanly by querying existing handle
        client = await get_temporal_client()
        handle = client.get_workflow_handle(workflow_id)
        current_status = await handle.query(BookingWorkflow.get_status)
        return {
            "workflow_id": workflow_id,
            "status": current_status.get("status"),
            "message": "Workflow already running/completed for idempotency_key",
            "details": current_status
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start booking workflow: {e}"
        )


@router.get("/{workflow_id}")
async def get_booking_status(workflow_id: str) -> Dict[str, Any]:
    """
    Query the status of an ongoing or completed booking workflow.
    """
    try:
        client = await get_temporal_client()
        handle = client.get_workflow_handle(workflow_id)
        return await handle.query(BookingWorkflow.get_status)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow '{workflow_id}' not found or unreachable: {e}"
        )


@router.post("/{workflow_id}/cancel", status_code=status.HTTP_200_OK)
async def cancel_booking_endpoint(workflow_id: str) -> Dict[str, Any]:
    """
    Send cancellation signal to an active booking workflow.
    """
    try:
        client = await get_temporal_client()
        handle = client.get_workflow_handle(workflow_id)
        await handle.signal(BookingWorkflow.cancel_booking)
        return {
            "workflow_id": workflow_id,
            "message": "Cancellation signal sent to workflow"
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send cancellation signal: {e}"
        )
