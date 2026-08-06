import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

from datetime import date
import pytest

from adapters.atlas_adapter import AtlasAdapter
from adapters.nova_adapter import NovaAdapter
from adapters.registry import AdapterRegistry, registry
from mocks.mock_atlas_api import MockAtlasAPI
from mocks.mock_nova_api import MockNovaAPI
from schemas.offer import AvailabilityStatus, UnifiedOffer
from schemas.search import SearchRequest
from services.search_service import deduplicate_offers, perform_search


@pytest.mark.asyncio
async def test_search_both_suppliers_succeed():
    # Setup test registry with normal mocks
    test_reg = AdapterRegistry()
    test_reg.register(AtlasAdapter(api=MockAtlasAPI()))
    test_reg.register(NovaAdapter(api=MockNovaAPI()))

    # Swap global registry for duration of test
    original_adapters = registry._adapters
    registry._adapters = test_reg._adapters

    try:
        req = SearchRequest(
            destination="Paris",
            check_in=date(2026, 9, 1),
            check_out=date(2026, 9, 5),
            guests=2,
            rooms=1
        )
        response = await perform_search(req, request_id="TEST-REQ-1")

        assert response.request_id == "TEST-REQ-1"
        assert set(response.suppliers_queried) == {"atlas", "nova"}
        assert response.suppliers_failed == []
        assert len(response.results) == 2

        # Check ranking order (cheaper Nova offer at 180 should be first before Atlas at 240)
        assert response.results[0].supplier_id == "nova"
        assert response.results[0].total_price == 180.0
        assert response.results[1].supplier_id == "atlas"
        assert response.results[1].total_price == 240.0
    finally:
        registry._adapters = original_adapters


@pytest.mark.asyncio
async def test_search_partial_failure_atlas_timeout():
    test_reg = AdapterRegistry()
    test_reg.register(AtlasAdapter(api=MockAtlasAPI(simulated_failure="timeout")))
    test_reg.register(NovaAdapter(api=MockNovaAPI()))

    original_adapters = registry._adapters
    registry._adapters = test_reg._adapters

    try:
        req = SearchRequest(
            destination="Paris",
            check_in=date(2026, 9, 1),
            check_out=date(2026, 9, 5),
            guests=2,
            rooms=1
        )
        response = await perform_search(req, request_id="TEST-REQ-2")

        assert set(response.suppliers_queried) == {"atlas", "nova"}
        assert response.suppliers_failed == ["atlas"]
        assert len(response.results) == 1
        assert response.results[0].supplier_id == "nova"
    finally:
        registry._adapters = original_adapters


@pytest.mark.asyncio
async def test_search_all_suppliers_failed():
    test_reg = AdapterRegistry()
    test_reg.register(AtlasAdapter(api=MockAtlasAPI(simulated_failure="500_error")))
    test_reg.register(NovaAdapter(api=MockNovaAPI(simulated_failure="timeout")))

    original_adapters = registry._adapters
    registry._adapters = test_reg._adapters

    try:
        req = SearchRequest(
            destination="Paris",
            check_in=date(2026, 9, 1),
            check_out=date(2026, 9, 5),
            guests=2,
            rooms=1
        )
        response = await perform_search(req, request_id="TEST-REQ-3")

        assert set(response.suppliers_queried) == {"atlas", "nova"}
        assert set(response.suppliers_failed) == {"atlas", "nova"}
        assert response.results == []
    finally:
        registry._adapters = original_adapters


def test_deduplication_keeps_cheaper_offer():
    offer_expensive = UnifiedOffer(
        supplier_id="atlas",
        property_id="ATL-1",
        property_name="Grand Central Resort & Spa",
        location="Paris, France",
        room_type="King Room",
        check_in_date=date(2026, 9, 1),
        check_out_date=date(2026, 9, 5),
        currency="EUR",
        base_price=200.0,
        taxes_and_fees=40.0,
        total_price=240.0,
        cancellation_policy="Free cancellation",
        availability_status=AvailabilityStatus.AVAILABLE
    )

    offer_cheaper = UnifiedOffer(
        supplier_id="nova",
        property_id="NOV-1",
        property_name="Grand Central Resort & Spa",
        location="Paris, France",
        room_type="King Suite",
        check_in_date=date(2026, 9, 1),
        check_out_date=date(2026, 9, 5),
        currency="EUR",
        base_price=150.0,
        taxes_and_fees=30.0,
        total_price=180.0,
        cancellation_policy="Flexible",
        availability_status=AvailabilityStatus.AVAILABLE
    )

    deduped = deduplicate_offers([offer_expensive, offer_cheaper])

    assert len(deduped) == 1
    assert deduped[0].supplier_id == "nova"
    assert deduped[0].total_price == 180.0
