import asyncio
import logging
import os
import sys
import uuid
from typing import Optional

from temporalio.client import Client
from temporalio.exceptions import WorkflowAlreadyStartedError

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from workflows.booking_workflow import BookingRequest, BookingWorkflow

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("booking_client")

TEMPORAL_HOST = os.getenv("TEMPORAL_HOST", "localhost:7233")
TASK_QUEUE = "booking-task-queue"


async def trigger_booking(
    supplier_id: str = "atlas",
    property_id: str = "ATL-PAR-01",
    idempotency_key: Optional[str] = None
) -> str:
    key = idempotency_key or f"test-key-{uuid.uuid4().hex[:6]}"
    workflow_id = f"booking-{key}"

    client = await Client.connect(TEMPORAL_HOST)
    booking_req = BookingRequest(
        offer_id="OFFER-101",
        supplier_id=supplier_id,
        property_id=property_id,
        check_in_date="2026-09-01",
        check_out_date="2026-09-05",
        quoted_price=240.0,
        currency="EUR",
        guest_details={"name": "Alice Smith"},
        idempotency_key=key
    )

    try:
        handle = await client.start_workflow(
            BookingWorkflow.run,
            booking_req,
            id=workflow_id,
            task_queue=TASK_QUEUE
        )
        logger.info(f"Started workflow '{handle.id}'")
        return handle.id
    except WorkflowAlreadyStartedError:
        logger.info(f"Workflow '{workflow_id}' already running/completed.")
        return workflow_id


async def query_status(workflow_id: str):
    client = await Client.connect(TEMPORAL_HOST)
    handle = client.get_workflow_handle(workflow_id)
    status_info = await handle.query(BookingWorkflow.get_status)
    logger.info(f"Workflow status for '{workflow_id}': {status_info}")
    return status_info


async def cancel_workflow(workflow_id: str):
    client = await Client.connect(TEMPORAL_HOST)
    handle = client.get_workflow_handle(workflow_id)
    await handle.signal(BookingWorkflow.cancel_booking)
    logger.info(f"Sent cancel signal to workflow '{workflow_id}'")


if __name__ == "__main__":
    w_id = asyncio.run(trigger_booking())
    asyncio.run(query_status(w_id))
