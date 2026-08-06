import asyncio
import logging
import os
from temporalio.client import Client
from temporalio.worker import Worker

from activities.booking_activities import (
    cancel_supplier_reservation_activity,
    create_supplier_reservation_activity,
    persist_booking_record_activity,
    poll_supplier_confirmation_activity,
    revalidate_offer_activity,
    record_failure_log_activity,
    record_status_change_activity,
    record_supplier_reference_activity,
)
from db.session import init_db
from logging_config import setup_json_logging
from workflows.booking_workflow import BookingWorkflow

# Initialize structured JSON logging
setup_json_logging()
logger = logging.getLogger("temporal_worker")

TEMPORAL_HOST = os.getenv("TEMPORAL_HOST", "localhost:7233")
TASK_QUEUE = "booking-task-queue"


async def main():
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        logger.info("Initializing database tables...")
        await init_db()

    temporal_host = os.getenv("TEMPORAL_HOST", "localhost:7233")
    logger.info(f"Connecting to Temporal server at {temporal_host}...")
    client = await Client.connect(temporal_host)

    logger.info(f"Starting Temporal worker on task queue '{TASK_QUEUE}'...")
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[BookingWorkflow],
        activities=[
            revalidate_offer_activity,
            create_supplier_reservation_activity,
            persist_booking_record_activity,
            poll_supplier_confirmation_activity,
            cancel_supplier_reservation_activity,
            record_status_change_activity,
            record_supplier_reference_activity,
            record_failure_log_activity,
        ],
    )

    logger.info("Worker started. Listening for tasks...")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
