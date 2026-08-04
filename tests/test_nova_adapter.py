import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

from datetime import date
import pytest

from adapters.exceptions import (
    SupplierMalformedResponseError,
    SupplierPriceChangedError,
    SupplierServerError,
    SupplierTimeoutError,
)
from adapters.nova_adapter import NovaAdapter
from mocks.mock_nova_api import MockNovaAPI
from schemas.offer import AvailabilityStatus, UnifiedOffer


@pytest.mark.asyncio
async def test_nova_search_success():
    mock_api = MockNovaAPI()
    adapter = NovaAdapter(api=mock_api)

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
    assert offer.supplier_id == "nova"
    assert offer.property_id == "NOV-PAR-101"
    assert offer.property_name == "Nova Boutique Stay Le Marais"
    assert offer.location == "Paris"
    assert offer.currency == "EUR"
    assert offer.base_price == 150.0
    assert offer.taxes_and_fees == 30.0
    assert offer.total_price == 180.0
    assert offer.cancellation_policy == "Flexible cancellation"
    assert offer.availability_status == AvailabilityStatus.AVAILABLE


@pytest.mark.asyncio
async def test_nova_pricing_and_availability():
    mock_api = MockNovaAPI()
    adapter = NovaAdapter(api=mock_api)

    offer = await adapter.get_pricing_and_availability(
        property_id="NOV-PAR-101",
        check_in=date(2026, 9, 1),
        check_out=date(2026, 9, 5)
    )

    assert offer.property_id == "NOV-PAR-101"
    assert offer.total_price == 180.0


@pytest.mark.asyncio
async def test_nova_reservation_flow():
    mock_api = MockNovaAPI()
    adapter = NovaAdapter(api=mock_api)

    search_results = await adapter.search_properties("Paris", date(2026, 9, 1), date(2026, 9, 5))
    offer = search_results[0]

    # Create reservation
    booking = await adapter.create_reservation(offer, {"name": "Bob Johnson"})
    assert booking["supplier_id"] == "nova"
    assert booking["status"] == "confirmed"
    assert booking["guest_name"] == "Bob Johnson"
    res_id = booking["reservation_id"]
    assert res_id.startswith("NOV-BK-")

    # Get status
    status_res = await adapter.get_reservation_status(res_id)
    assert status_res["reservation_id"] == res_id
    assert status_res["status"] == "confirmed"

    # Cancel reservation
    cancel_res = await adapter.cancel_reservation(res_id)
    assert cancel_res["reservation_id"] == res_id
    assert cancel_res["status"] == "cancelled"
    assert cancel_res["refund_amount"] == 180.0


@pytest.mark.asyncio
async def test_nova_timeout_failure():
    mock_api = MockNovaAPI(simulated_failure="timeout")
    adapter = NovaAdapter(api=mock_api)

    with pytest.raises(SupplierTimeoutError) as exc_info:
        await adapter.search_properties("Paris", date(2026, 9, 1), date(2026, 9, 5))

    assert exc_info.value.supplier_id == "nova"


@pytest.mark.asyncio
async def test_nova_server_500_failure():
    mock_api = MockNovaAPI(simulated_failure="500_error")
    adapter = NovaAdapter(api=mock_api)

    with pytest.raises(SupplierServerError) as exc_info:
        await adapter.search_properties("Paris", date(2026, 9, 1), date(2026, 9, 5))

    assert exc_info.value.supplier_id == "nova"


@pytest.mark.asyncio
async def test_nova_malformed_response_failure():
    mock_api = MockNovaAPI(simulated_failure="malformed")
    adapter = NovaAdapter(api=mock_api)

    with pytest.raises(SupplierMalformedResponseError) as exc_info:
        await adapter.search_properties("Paris", date(2026, 9, 1), date(2026, 9, 5))

    assert exc_info.value.supplier_id == "nova"


@pytest.mark.asyncio
async def test_nova_price_changed_failure():
    mock_api = MockNovaAPI(simulated_failure="price_changed")
    adapter = NovaAdapter(api=mock_api)

    with pytest.raises(SupplierPriceChangedError) as exc_info:
        await adapter.get_pricing_and_availability("NOV-PAR-101", date(2026, 9, 1), date(2026, 9, 5))

    assert exc_info.value.supplier_id == "nova"
