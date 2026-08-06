import io
import logging
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

import asyncio
from datetime import date, timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.future import select
from temporalio import activity
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
from adapters.nova_adapter import NovaAdapter
from adapters.registry import AdapterRegistry, registry
from api.main import app
from db.models import (
    BookingStatusHistoryRecord,
    FailureLogRecord,
    NormalizedOfferRecord,
    SearchRequestRecord,
    SupplierReferenceRecord,
)
from db.session import AsyncSessionLocal, init_db
from logging_config import JSONFormatter, setup_json_logging
from mocks.mock_atlas_api import MockAtlasAPI
from mocks.mock_nova_api import MockNovaAPI
from schemas.search import SearchRequest
from services.search_service import perform_search
from workflows.booking_workflow import BookingRequest, BookingWorkflow

TASK_QUEUE = "test-observability-queue"
test_client = TestClient(app)


@pytest.fixture(autouse=True)
async def setup_test_environment():
    """Initialize SQLite in-memory DB tables and register clean mock adapters."""
    await init_db()
    test_reg = AdapterRegistry()
    mock_atlas = MockAtlasAPI()
    mock_nova = MockNovaAPI()
    test_reg.register(AtlasAdapter(api=mock_atlas))
    test_reg.register(NovaAdapter(api=mock_nova))

    orig = registry._adapters
    registry._adapters = test_reg._adapters
    yield mock_atlas, mock_nova
    registry._adapters = orig


@pytest.mark.asyncio
async def test_search_persistence_and_partial_failure():
    """
    Verify search_service persists search_requests, normalized_offers, and failure_log.
    Simulate partial failure where Nova fails, verifying Atlas offers still get logged.
    """
    nova_failing_adapter = NovaAdapter(api=MockNovaAPI(simulated_failure="500_error"))
    orig_nova = registry._adapters.get("nova")
    registry._adapters["nova"] = nova_failing_adapter

    try:
        req = SearchRequest(
            destination="Paris",
            check_in=date(2026, 9, 1),
            check_out=date(2026, 9, 5),
            guests=2,
            rooms=1
        )

        request_id = "req-obs-test-01"
        response = await perform_search(req, request_id)

        assert "nova" in response.suppliers_failed
        assert "atlas" in response.suppliers_queried

        # Give background asyncio.create_task a brief moment to commit
        await asyncio.sleep(0.1)

        async with AsyncSessionLocal() as session:
            # Verify search_requests row
            search_res = await session.execute(
                select(SearchRequestRecord).where(SearchRequestRecord.request_id == request_id)
            )
            search_rec = search_res.scalar_one_or_none()
            assert search_rec is not None
            assert search_rec.destination == "Paris"
            assert "nova" in search_rec.suppliers_failed

            # Verify normalized_offers rows (Atlas offers persisted)
            offers_res = await session.execute(
                select(NormalizedOfferRecord).where(NormalizedOfferRecord.request_id == request_id)
            )
            offer_recs = offers_res.scalars().all()
            assert len(offer_recs) > 0
            for o in offer_recs:
                assert o.supplier_id == "atlas"
                assert o.rank_score is not None

            # Verify failure_log row for Nova failure
            fail_res = await session.execute(
                select(FailureLogRecord).where(FailureLogRecord.request_id == request_id)
            )
            fail_recs = fail_res.scalars().all()
            assert len(fail_recs) == 1
            assert fail_recs[0].supplier_id == "nova"
            assert fail_recs[0].context == "search"
    finally:
        if orig_nova:
            registry._adapters["nova"] = orig_nova


@pytest.mark.asyncio
async def test_booking_status_history_and_supplier_reference_persistence():
    """
    Verify booking_workflow status transitions write booking_status_history rows in order,
    and supplier_references row is created upon reservation creation.
    """
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
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
        ):
            req = BookingRequest(
                offer_id="OFFER-OBS-01",
                supplier_id="atlas",
                property_id="ATL-PAR-01",
                check_in_date="2026-09-01",
                check_out_date="2026-09-05",
                quoted_price=240.0,
                currency="EUR",
                guest_details={"name": "Alice Smith"},
                idempotency_key="obs-history-key"
            )

            handle = await env.client.start_workflow(
                BookingWorkflow.run,
                req,
                id="booking-obs-history-key",
                task_queue=TASK_QUEUE
            )
            res = await handle.result()
            assert res["status"] == "CONFIRMED"

            booking_id = f"BK-{req.idempotency_key[:12]}"

            async with AsyncSessionLocal() as session:
                # 1. Assert status history transition rows ordered chronologically
                hist_res = await session.execute(
                    select(BookingStatusHistoryRecord)
                    .where(BookingStatusHistoryRecord.booking_id == booking_id)
                    .order_by(BookingStatusHistoryRecord.changed_at.asc())
                )
                history_rows = hist_res.scalars().all()

                assert len(history_rows) >= 2
                statuses = [r.new_status for r in history_rows]
                assert "PROCESSING" in statuses
                assert "CONFIRMED" in statuses

                # 2. Assert supplier_references row
                ref_res = await session.execute(
                    select(SupplierReferenceRecord)
                    .where(SupplierReferenceRecord.booking_id == booking_id)
                )
                ref_row = ref_res.scalar_one_or_none()
                assert ref_row is not None
                assert ref_row.supplier_id == "atlas"
                assert ref_row.raw_supplier_response["status"] == "confirmed"


@pytest.mark.asyncio
async def test_saga_compensation_status_history_and_failure_logging():
    """
    Verify Saga compensation path records transitions (PROCESSING -> COMPENSATING -> FAILED)
    and writes failure_log row.
    """
    @activity.defn(name="persist_booking_record_activity")
    async def mock_failed_persist(payload):
        raise RuntimeError("Persistent DB disk failure")

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[BookingWorkflow],
            activities=[
                revalidate_offer_activity,
                create_supplier_reservation_activity,
                mock_failed_persist,
                poll_supplier_confirmation_activity,
                cancel_supplier_reservation_activity,
                record_status_change_activity,
                record_supplier_reference_activity,
                record_failure_log_activity,
            ],
        ):
            req = BookingRequest(
                offer_id="OFFER-OBS-02",
                supplier_id="atlas",
                property_id="ATL-PAR-01",
                check_in_date="2026-09-01",
                check_out_date="2026-09-05",
                quoted_price=240.0,
                currency="EUR",
                guest_details={"name": "Bob Jones"},
                idempotency_key="saga-obs-key"
            )

            handle = await env.client.start_workflow(
                BookingWorkflow.run,
                req,
                id="booking-saga-obs-key",
                task_queue=TASK_QUEUE
            )
            res = await handle.result()
            assert res["status"] == "FAILED"

            booking_id = f"BK-{req.idempotency_key[:12]}"

            async with AsyncSessionLocal() as session:
                hist_res = await session.execute(
                    select(BookingStatusHistoryRecord)
                    .where(BookingStatusHistoryRecord.booking_id == booking_id)
                    .order_by(BookingStatusHistoryRecord.changed_at.asc())
                )
                history_rows = hist_res.scalars().all()
                statuses = [r.new_status for r in history_rows]

                assert "PROCESSING" in statuses
                assert "COMPENSATING" in statuses
                assert "FAILED" in statuses

                # Verify failure_log entry
                fail_res = await session.execute(
                    select(FailureLogRecord).where(FailureLogRecord.booking_id == booking_id)
                )
                fail_rows = fail_res.scalars().all()
                assert len(fail_rows) >= 1
                assert fail_rows[0].error_type == "DatabasePersistError"


def test_admin_read_endpoints():
    """
    Test Admin observability API read endpoints.
    """
    # Seed data in test database
    async def seed():
        async with AsyncSessionLocal() as session:
            session.add(SearchRequestRecord(
                request_id="req-admin-01",
                destination="Tokyo",
                check_in=date(2026, 10, 1),
                check_out=date(2026, 10, 5),
                guests=2,
                rooms=1,
                suppliers_queried=["atlas"],
                suppliers_failed=[]
            ))
            session.add(NormalizedOfferRecord(
                offer_id="OFFER-ADMIN-01",
                request_id="req-admin-01",
                supplier_id="atlas",
                property_id="ATL-TYO-01",
                property_name="Tokyo Stay",
                location="Shinjuku",
                room_type="Deluxe",
                check_in_date=date(2026, 10, 1),
                check_out_date=date(2026, 10, 5),
                currency="USD",
                base_price=200.0,
                taxes_and_fees=40.0,
                total_price=240.0,
                cancellation_policy="Standard",
                availability_status="available",
                rank_score=0.95
            ))
            session.add(FailureLogRecord(
                context="search",
                request_id="req-admin-01",
                supplier_id="nova",
                error_type="SupplierTimeoutError",
                error_message="Nova API timeout after 5.0s",
                retry_attempt_number=1
            ))
            await session.commit()

    asyncio.run(seed())

    # GET /search-requests/{request_id}
    resp = test_client.get("/search-requests/req-admin-01")
    assert resp.status_code == 200
    data = resp.json()
    assert data["request"]["destination"] == "Tokyo"
    assert len(data["offers"]) == 1
    assert data["offers"][0]["offer_id"] == "OFFER-ADMIN-01"

    # GET /failures?context=search
    resp_fail = test_client.get("/failures?context=search")
    assert resp_fail.status_code == 200
    fail_data = resp_fail.json()
    assert len(fail_data) >= 1
    assert fail_data[0]["supplier_id"] == "nova"


@pytest.mark.asyncio
async def test_no_guest_pii_in_log_output(caplog):
    """
    AUDIT ASSERTION: Capture log output during booking workflow execution and assert
    that NO guest PII (e.g. 'SensitiveGuestName') appears anywhere in log records.
    """
    caplog.set_level(logging.INFO)

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
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
        ):
            pii_guest_name = "SensitiveGuestName-Private123"
            req = BookingRequest(
                offer_id="OFFER-PII-01",
                supplier_id="atlas",
                property_id="ATL-PAR-01",
                check_in_date="2026-09-01",
                check_out_date="2026-09-05",
                quoted_price=240.0,
                currency="EUR",
                guest_details={"name": pii_guest_name, "email": "private@example.com"},
                idempotency_key="pii-audit-key"
            )

            handle = await env.client.start_workflow(
                BookingWorkflow.run,
                req,
                id="booking-pii-audit-key",
                task_queue=TASK_QUEUE
            )
            result = await handle.result()
            assert result["status"] == "CONFIRMED"

            # Assert captured log records contain ZERO instances of PII
            log_text = caplog.text
            assert pii_guest_name not in log_text
            assert "private@example.com" not in log_text
