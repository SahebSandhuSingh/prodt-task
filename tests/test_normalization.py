import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

from datetime import date
import pytest
from pydantic import ValidationError

from adapters.atlas_adapter import AtlasAdapter
from adapters.exceptions import SupplierNotFoundError
from adapters.nova_adapter import NovaAdapter
from adapters.registry import AdapterRegistry, get_adapter, register_adapter
from schemas.offer import AvailabilityStatus, UnifiedOffer


def test_unified_offer_valid_math():
    offer = UnifiedOffer(
        supplier_id="test_supplier",
        property_id="PROP-101",
        property_name="Test Grand Hotel",
        location="Test City",
        room_type="Deluxe Room",
        check_in_date=date(2026, 9, 1),
        check_out_date=date(2026, 9, 5),
        currency="USD",
        base_price=100.0,
        taxes_and_fees=20.0,
        total_price=120.0,
        cancellation_policy="Free cancellation",
        availability_status=AvailabilityStatus.AVAILABLE
    )
    assert offer.total_price == offer.base_price + offer.taxes_and_fees


def test_unified_offer_invalid_math_raises_validation_error():
    with pytest.raises(ValidationError) as exc_info:
        UnifiedOffer(
            supplier_id="test_supplier",
            property_id="PROP-101",
            property_name="Test Grand Hotel",
            location="Test City",
            room_type="Deluxe Room",
            check_in_date=date(2026, 9, 1),
            check_out_date=date(2026, 9, 5),
            currency="USD",
            base_price=100.0,
            taxes_and_fees=20.0,
            total_price=150.0,  # Incorrect total!
            cancellation_policy="Free cancellation",
            availability_status=AvailabilityStatus.AVAILABLE
        )
    assert "Total price inconsistency" in str(exc_info.value)


@pytest.mark.asyncio
async def test_cross_supplier_normalization_consistency():
    atlas_adapter = AtlasAdapter()
    nova_adapter = NovaAdapter()

    check_in = date(2026, 9, 1)
    check_out = date(2026, 9, 5)

    atlas_offers = await atlas_adapter.search_properties("Paris", check_in, check_out)
    nova_offers = await nova_adapter.search_properties("Paris", check_in, check_out)

    all_offers = atlas_offers + nova_offers
    assert len(all_offers) == 2

    for offer in all_offers:
        assert isinstance(offer, UnifiedOffer)
        assert round(offer.total_price, 2) == round(offer.base_price + offer.taxes_and_fees, 2)
        assert offer.location == "Paris"
        assert offer.check_in_date == check_in
        assert offer.check_out_date == check_out


def test_registry_management():
    test_reg = AdapterRegistry()
    atlas = AtlasAdapter()
    nova = NovaAdapter()

    test_reg.register(atlas)
    test_reg.register(nova)

    assert test_reg.get("atlas") is atlas
    assert test_reg.get("nova") is nova
    assert test_reg.get("ATLAS") is atlas  # case insensitivity test

    assert set(test_reg.list_suppliers()) == {"atlas", "nova"}

    with pytest.raises(SupplierNotFoundError):
        test_reg.get("non_existent_supplier")


def test_global_registry_helper():
    atlas = get_adapter("atlas")
    assert atlas.supplier_id == "atlas"
    
    nova = get_adapter("nova")
    assert nova.supplier_id == "nova"
