import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

import asyncio
from datetime import timedelta
import pytest
from temporalio import activity
from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError
from temporalio.testing import WorkflowEnvironment
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
from adapters.atlas_adapter import AtlasAdapter
from adapters.registry import AdapterRegistry, registry
from db.session import init_db
from mocks.mock_atlas_api import MockAtlasAPI
from workflows.booking_workflow import BookingRequest, BookingWorkflow

TASK_QUEUE = "test-booking-queue"

ALL_ACTIVITIES = [
    revalidate_offer_activity,
    create_supplier_reservation_activity,
    persist_booking_record_activity,
    poll_supplier_confirmation_activity,
    cancel_supplier_reservation_activity,
    record_status_change_activity,
    record_supplier_reference_activity,
    record_failure_log_activity,
]


@pytest.fixture(autouse=True)
async def setup_mock_adapters():
    """Ensure clean mock adapters and DB tables are set up for each test."""
    await init_db()
    test_reg = AdapterRegistry()
    mock_atlas = MockAtlasAPI()
    test_reg.register(AtlasAdapter(api=mock_atlas))
    
    orig = registry._adapters
    registry._adapters = test_reg._adapters
    yield mock_atlas
    registry._adapters = orig


@pytest.mark.asyncio
async def test_booking_workflow_happy_path(setup_mock_adapters):
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[BookingWorkflow],
            activities=ALL_ACTIVITIES,
        ):
            req = BookingRequest(
                offer_id="OFFER-01",
                supplier_id="atlas",
                property_id="ATL-PAR-01",
                check_in_date="2026-09-01",
                check_out_date="2026-09-05",
                quoted_price=240.0,
                currency="EUR",
                guest_details={"name": "Alice Smith"},
                idempotency_key="happy-path-key"
            )

            handle = await env.client.start_workflow(
                BookingWorkflow.run,
                req,
                id="booking-happy-path-key",
                task_queue=TASK_QUEUE
            )
            result = await handle.result()

            assert result["status"] == "CONFIRMED"
            assert result["supplier_reservation_id"].startswith("ATL-RES-")

            status = await handle.query(BookingWorkflow.get_status)
            assert status["status"] == "CONFIRMED"


@pytest.mark.asyncio
async def test_booking_workflow_price_changed_exceeded():
    test_reg = AdapterRegistry()
    test_reg.register(AtlasAdapter(api=MockAtlasAPI(simulated_failure="price_changed")))
    orig = registry._adapters
    registry._adapters = test_reg._adapters

    try:
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=TASK_QUEUE,
                workflows=[BookingWorkflow],
                activities=ALL_ACTIVITIES,
            ):
                req = BookingRequest(
                    offer_id="OFFER-02",
                    supplier_id="atlas",
                    property_id="ATL-PAR-01",
                    check_in_date="2026-09-01",
                    check_out_date="2026-09-05",
                    quoted_price=240.0,
                    currency="EUR",
                    guest_details={"name": "Bob Jones"},
                    idempotency_key="price-drift-key"
                )

                handle = await env.client.start_workflow(
                    BookingWorkflow.run,
                    req,
                    id="booking-price-drift-key",
                    task_queue=TASK_QUEUE
                )
                result = await handle.result()

                assert result["status"] == "PRICE_CHANGED"
    finally:
        registry._adapters = orig


@pytest.mark.asyncio
async def test_booking_workflow_saga_compensation_on_db_persist_fail(setup_mock_adapters):
    mock_atlas = setup_mock_adapters

    @activity.defn(name="persist_booking_record_activity")
    async def mock_failed_persist(payload):
        raise RuntimeError("Database connection pool exhausted")

    activities = [
        revalidate_offer_activity,
        create_supplier_reservation_activity,
        mock_failed_persist,
        poll_supplier_confirmation_activity,
        cancel_supplier_reservation_activity,
        record_status_change_activity,
        record_supplier_reference_activity,
        record_failure_log_activity,
    ]

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[BookingWorkflow],
            activities=activities,
        ):
            req = BookingRequest(
                offer_id="OFFER-03",
                supplier_id="atlas",
                property_id="ATL-PAR-01",
                check_in_date="2026-09-01",
                check_out_date="2026-09-05",
                quoted_price=240.0,
                currency="EUR",
                guest_details={"name": "Charlie"},
                idempotency_key="saga-db-fail-key"
            )

            handle = await env.client.start_workflow(
                BookingWorkflow.run,
                req,
                id="booking-saga-db-fail-key",
                task_queue=TASK_QUEUE
            )
            result = await handle.result()

            assert result["status"] == "FAILED"
            assert result["supplier_reservation_id"] is not None

            res_id = result["supplier_reservation_id"]
            booking_record = mock_atlas._reservations[res_id]
            assert booking_record["booking_status"] == "CANCELLED"


@pytest.mark.asyncio
async def test_booking_workflow_compensation_also_fails():
    test_reg = AdapterRegistry()
    mock_api = MockAtlasAPI()
    test_reg.register(AtlasAdapter(api=mock_api))
    orig = registry._adapters
    registry._adapters = test_reg._adapters

    @activity.defn(name="persist_booking_record_activity")
    async def mock_failed_persist(payload):
        raise RuntimeError("Database fail")

    @activity.defn(name="cancel_supplier_reservation_activity")
    async def mock_failed_cancel(payload):
        raise RuntimeError("Supplier cancellation service unreachable")

    activities = [
        revalidate_offer_activity,
        create_supplier_reservation_activity,
        mock_failed_persist,
        poll_supplier_confirmation_activity,
        mock_failed_cancel,
        record_status_change_activity,
        record_supplier_reference_activity,
        record_failure_log_activity,
    ]

    try:
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=TASK_QUEUE,
                workflows=[BookingWorkflow],
                activities=activities,
            ):
                req = BookingRequest(
                    offer_id="OFFER-04",
                    supplier_id="atlas",
                    property_id="ATL-PAR-01",
                    check_in_date="2026-09-01",
                    check_out_date="2026-09-05",
                    quoted_price=240.0,
                    currency="EUR",
                    guest_details={"name": "David"},
                    idempotency_key="compensation-fail-key"
                )

                handle = await env.client.start_workflow(
                    BookingWorkflow.run,
                    req,
                    id="booking-compensation-fail-key",
                    task_queue=TASK_QUEUE
                )
                result = await handle.result()

                assert result["status"] == "REQUIRES_MANUAL_REVIEW"
    finally:
        registry._adapters = orig


@pytest.mark.asyncio
async def test_booking_workflow_idempotency_duplicate_start(setup_mock_adapters):
    mock_atlas = setup_mock_adapters

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[BookingWorkflow],
            activities=ALL_ACTIVITIES,
        ):
            req = BookingRequest(
                offer_id="OFFER-05",
                supplier_id="atlas",
                property_id="ATL-PAR-01",
                check_in_date="2026-09-01",
                check_out_date="2026-09-05",
                quoted_price=240.0,
                currency="EUR",
                guest_details={"name": "Eve"},
                idempotency_key="duplicate-key-99"
            )

            workflow_id = "booking-duplicate-key-99"
            handle1 = await env.client.start_workflow(
                BookingWorkflow.run,
                req,
                id=workflow_id,
                task_queue=TASK_QUEUE,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE
            )

            with pytest.raises(WorkflowAlreadyStartedError):
                await env.client.start_workflow(
                    BookingWorkflow.run,
                    req,
                    id=workflow_id,
                    task_queue=TASK_QUEUE,
                    id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE
                )

            res1 = await handle1.result()
            assert res1["status"] == "CONFIRMED"

            handle2 = env.client.get_workflow_handle(workflow_id)
            res2 = await handle2.query(BookingWorkflow.get_status)
            assert res2["status"] == "CONFIRMED"

            assert len(mock_atlas._reservations) == 1


@pytest.mark.asyncio
async def test_booking_workflow_cancel_signal_during_polling(setup_mock_adapters):
    mock_atlas = setup_mock_adapters

    @activity.defn(name="poll_supplier_confirmation_activity")
    async def mock_pending_poll(payload):
        return {"status": "pending"}

    activities = [
        revalidate_offer_activity,
        create_supplier_reservation_activity,
        persist_booking_record_activity,
        mock_pending_poll,
        cancel_supplier_reservation_activity,
        record_status_change_activity,
        record_supplier_reference_activity,
        record_failure_log_activity,
    ]

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[BookingWorkflow],
            activities=activities,
        ):
            req = BookingRequest(
                offer_id="OFFER-06",
                supplier_id="atlas",
                property_id="ATL-PAR-01",
                check_in_date="2026-09-01",
                check_out_date="2026-09-05",
                quoted_price=240.0,
                currency="EUR",
                guest_details={"name": "Frank"},
                idempotency_key="cancel-mid-polling-key"
            )

            handle = await env.client.start_workflow(
                BookingWorkflow.run,
                req,
                id="booking-cancel-mid-polling-key",
                task_queue=TASK_QUEUE
            )

            await handle.signal(BookingWorkflow.cancel_booking)
            result = await handle.result()

            assert result["status"] == "CANCELLED"
            if result.get("supplier_reservation_id"):
                res_id = result["supplier_reservation_id"]
                assert mock_atlas._reservations[res_id]["booking_status"] == "CANCELLED"


@pytest.mark.asyncio
async def test_booking_workflow_cancel_signal_post_terminal(setup_mock_adapters):
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[BookingWorkflow],
            activities=ALL_ACTIVITIES,
        ):
            req = BookingRequest(
                offer_id="OFFER-07",
                supplier_id="atlas",
                property_id="ATL-PAR-01",
                check_in_date="2026-09-01",
                check_out_date="2026-09-05",
                quoted_price=240.0,
                currency="EUR",
                guest_details={"name": "Grace"},
                idempotency_key="cancel-post-terminal-key"
            )

            handle = await env.client.start_workflow(
                BookingWorkflow.run,
                req,
                id="booking-cancel-post-terminal-key",
                task_queue=TASK_QUEUE
            )
            result = await handle.result()
            assert result["status"] == "CONFIRMED"

            try:
                await handle.signal(BookingWorkflow.cancel_booking)
            except RPCError as e:
                assert "Completed workflow" in str(e)

            status = await handle.query(BookingWorkflow.get_status)
            assert status["status"] == "CONFIRMED"


@pytest.mark.asyncio
async def test_booking_workflow_unconfirmed_polling_resolves_manual_review(setup_mock_adapters):
    @activity.defn(name="poll_supplier_confirmation_activity")
    async def mock_always_pending_poll(payload):
        return {"status": "pending"}

    activities = [
        revalidate_offer_activity,
        create_supplier_reservation_activity,
        persist_booking_record_activity,
        mock_always_pending_poll,
        cancel_supplier_reservation_activity,
        record_status_change_activity,
        record_supplier_reference_activity,
        record_failure_log_activity,
    ]

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[BookingWorkflow],
            activities=activities,
        ):
            req = BookingRequest(
                offer_id="OFFER-08",
                supplier_id="atlas",
                property_id="ATL-PAR-01",
                check_in_date="2026-09-01",
                check_out_date="2026-09-05",
                quoted_price=240.0,
                currency="EUR",
                guest_details={"name": "Heidi"},
                idempotency_key="unconfirmed-polling-key"
            )

            handle = await env.client.start_workflow(
                BookingWorkflow.run,
                req,
                id="booking-unconfirmed-polling-key",
                task_queue=TASK_QUEUE
            )
            result = await handle.result()

            assert result["status"] == "REQUIRES_MANUAL_REVIEW"


@pytest.mark.asyncio
async def test_worker_restart_recovery_automated(setup_mock_adapters):
    async with await WorkflowEnvironment.start_time_skipping() as env:
        worker1 = Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[BookingWorkflow],
            activities=ALL_ACTIVITIES,
        )

        worker1_task = asyncio.create_task(worker1.run())

        req = BookingRequest(
            offer_id="OFFER-09",
            supplier_id="atlas",
            property_id="ATL-PAR-01",
            check_in_date="2026-09-01",
            check_out_date="2026-09-05",
            quoted_price=240.0,
            currency="EUR",
            guest_details={"name": "Ivan"},
            idempotency_key="worker-restart-key"
        )

        handle = await env.client.start_workflow(
            BookingWorkflow.run,
            req,
            id="booking-worker-restart-key",
            task_queue=TASK_QUEUE
        )

        await asyncio.sleep(0.1)

        worker1_task.cancel()
        try:
            await worker1_task
        except asyncio.CancelledError:
            pass

        worker2 = Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[BookingWorkflow],
            activities=ALL_ACTIVITIES,
        )

        worker2_task = asyncio.create_task(worker2.run())

        result = await handle.result()
        assert result["status"] == "CONFIRMED"

        worker2_task.cancel()
        try:
            await worker2_task
        except asyncio.CancelledError:
            pass
