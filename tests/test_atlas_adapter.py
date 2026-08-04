import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

from datetime import date
import pytest

from adapters.atlas_adapter import AtlasAdapter
from adapters.exceptions import (
    SupplierMalformedResponseError,
    SupplierPriceChangedError,
    SupplierServerError,
    SupplierTimeoutError,
)
from mocks.mock_atlas_api import MockAtlasAPI
from schemas.offer import AvailabilityStatus, UnifiedOffer


@pytest.mark.asyncio
async def test_atlas_search_success():
    mock_api = MockAtlasAPI()
    adapter = AtlasAdapter(api=mock_api)

    offers = await adapter.search_properties(
        destination="Paris",
        check_in=date(2026, 9, 1),
        check_out=date(2026, 9, 5),
        guests=2,
        rooms=1
    )

    assert len(offers) == 1
    offer = offers[0]
    assert isinstance(offer, UnifiedOffer)
    assert offer.supplier_id == "atlas"
    assert offer.property_id == "ATL-PAR-01"
    assert offer.property_name == "Atlas Grand Hotel Paris"
    assert offer.location == "Paris"
    assert offer.currency == "EUR"
    assert offer.base_price == 200.0
    assert offer.taxes_and_fees == 40.0
    assert offer.total_price == 240.0
    assert offer.cancellation_policy == "Free cancellation up to 24 hours before check-in"
    assert offer.availability_status == AvailabilityStatus.AVAILABLE


@pytest.mark.asyncio
async def test_atlas_pricing_and_availability():
    mock_api = MockAtlasAPI()
    adapter = AtlasAdapter(api=mock_api)

    offer = await adapter.get_pricing_and_availability(
        property_id="ATL-PAR-01",
        check_in=date(2026, 9, 1),
        check_out=date(2026, 9, 5)
    )

    assert offer.property_id == "ATL-PAR-01"
    assert offer.total_price == 240.0


@pytest.mark.asyncio
async def test_atlas_reservation_flow():
    mock_api = MockAtlasAPI()
    adapter = AtlasAdapter(api=mock_api)

    search_results = await adapter.search_properties("Paris", date(2026, 9, 1), date(2026, 9, 5))
    offer = search_results[0]

    # Create reservation
    booking = await adapter.create_reservation(offer, {"name": "Alice Smith"})
    assert booking["supplier_id"] == "atlas"
    assert booking["status"] == "confirmed"
    assert booking["guest_name"] == "Alice Smith"
    res_id = booking["reservation_id"]
    assert res_id.startswith("ATL-RES-")

    # Get status
    status_res = await adapter.get_reservation_status(res_id)
    assert status_res["reservation_id"] == res_id
    assert status_res["status"] == "confirmed"

    # Cancel reservation
    cancel_res = await adapter.cancel_reservation(res_id)
    assert cancel_res["reservation_id"] == res_id
    assert cancel_res["status"] == "cancelled"
    assert cancel_res["refund_amount"] == 240.0


@pytest.mark.asyncio
async def test_atlas_timeout_failure():
    mock_api = MockAtlasAPI(simulated_failure="timeout")
    adapter = AtlasAdapter(api=mock_api)

    with pytest.raises(SupplierTimeoutError) as exc_info:
        await adapter.search_properties("Paris", date(2026, 9, 1), date(2026, 9, 5))
    
    assert exc_info.value.supplier_id == "atlas"


@pytest.mark.asyncio
async def test_atlas_server_500_failure():
    mock_api = MockAtlasAPI(simulated_failure="500_error")
    adapter = AtlasAdapter(api=mock_api)

    with pytest.raises(SupplierServerError) as exc_info:
        await adapter.search_properties("Paris", date(2026, 9, 1), date(2026, 9, 5))

    assert exc_info.value.supplier_id == "atlas"


@pytest.mark.asyncio
async def test_atlas_malformed_response_failure():
    mock_api = MockAtlasAPI(simulated_failure="malformed")
    adapter = AtlasAdapter(api=mock_api)

    with pytest.raises(SupplierMalformedResponseError) as exc_info:
        await adapter.search_properties("Paris", date(2026, 9, 1), date(2026, 9, 5))

    assert exc_info.value.supplier_id == "atlas"


@pytest.mark.asyncio
async def test_atlas_price_changed_failure():
    mock_api = MockAtlasAPI(simulated_failure="price_changed")
    adapter = AtlasAdapter(api=mock_api)

    with pytest.raises(SupplierPriceChangedError) as exc_info:
        await adapter.get_pricing_and_availability("ATL-PAR-01", date(2026, 9, 1), date(2026, 9, 5))

    assert exc_info.value.supplier_id == "atlas"
