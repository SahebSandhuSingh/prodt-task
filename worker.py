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
)
from db.session import init_db
from workflows.booking_workflow import BookingWorkflow

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s"
)
logger = logging.getLogger("temporal_worker")

TEMPORAL_HOST = os.getenv("TEMPORAL_HOST", "localhost:7233")
TASK_QUEUE = "booking-task-queue"


async def main():
    logger.info("Initializing database tables...")
    try:
        await init_db()
    except Exception as e:
        logger.warning(f"Database initialization warning (ignoring if offline during mock tests): {e}")

    logger.info(f"Connecting to Temporal server at {TEMPORAL_HOST}...")
    client = await Client.connect(TEMPORAL_HOST)

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
        ],
    )

    logger.info("Worker started. Listening for tasks...")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
