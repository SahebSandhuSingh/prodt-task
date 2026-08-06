import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

from datetime import date
import pytest

from schemas.offer import AvailabilityStatus, UnifiedOffer
from services.ranking import calculate_offer_score, rank_offers, SUPPLIER_CONFIDENCE


def test_calculate_offer_score_ranking():
    cheap_available_atlas = UnifiedOffer(
        supplier_id="atlas",
        property_id="ATL-1",
        property_name="Paris Grand Hotel",
        location="Paris",
        room_type="Standard",
        check_in_date=date(2026, 9, 1),
        check_out_date=date(2026, 9, 5),
        currency="EUR",
        base_price=100.0,
        taxes_and_fees=20.0,
        total_price=120.0,
        cancellation_policy="Free cancellation",
        availability_status=AvailabilityStatus.AVAILABLE
    )

    expensive_available_nova = UnifiedOffer(
        supplier_id="nova",
        property_id="NOV-1",
        property_name="Paris Luxury Suites",
        location="Paris",
        room_type="Suite",
        check_in_date=date(2026, 9, 1),
        check_out_date=date(2026, 9, 5),
        currency="EUR",
        base_price=300.0,
        taxes_and_fees=60.0,
        total_price=360.0,
        cancellation_policy="Non-refundable",
        availability_status=AvailabilityStatus.AVAILABLE
    )

    # Min price = 120, Max price = 360
    score_cheap = calculate_offer_score(cheap_available_atlas, min_price=120.0, max_price=360.0)
    score_expensive = calculate_offer_score(expensive_available_nova, min_price=120.0, max_price=360.0)

    # Cheaper offer should have higher score
    assert score_cheap > score_expensive


def test_rank_offers_sorting_order():
    offer_a = UnifiedOffer(
        supplier_id="atlas",
        property_id="A1",
        property_name="Hotel A",
        location="Paris",
        room_type="Standard",
        check_in_date=date(2026, 9, 1),
        check_out_date=date(2026, 9, 5),
        currency="EUR",
        base_price=200.0,
        taxes_and_fees=40.0,
        total_price=240.0,
        cancellation_policy="Free cancellation",
        availability_status=AvailabilityStatus.AVAILABLE
    )

    offer_b = UnifiedOffer(
        supplier_id="nova",
        property_id="B1",
        property_name="Hotel B",
        location="Paris",
        room_type="Standard",
        check_in_date=date(2026, 9, 1),
        check_out_date=date(2026, 9, 5),
        currency="EUR",
        base_price=100.0,
        taxes_and_fees=20.0,
        total_price=120.0,
        cancellation_policy="Free cancellation",
        availability_status=AvailabilityStatus.AVAILABLE
    )

    ranked = rank_offers([offer_a, offer_b])

    assert len(ranked) == 2
    # B is cheaper (120 vs 240), so B should rank first
    assert ranked[0].property_id == "B1"
    assert ranked[1].property_id == "A1"


def test_rank_offers_empty():
    assert rank_offers([]) == []


def test_rank_offers_single():
    offer = UnifiedOffer(
        supplier_id="atlas",
        property_id="A1",
        property_name="Solo Hotel",
        location="Paris",
        room_type="Standard",
        check_in_date=date(2026, 9, 1),
        check_out_date=date(2026, 9, 5),
        currency="EUR",
        base_price=100.0,
        taxes_and_fees=20.0,
        total_price=120.0,
        cancellation_policy="Free cancellation",
        availability_status=AvailabilityStatus.AVAILABLE
    )
    ranked = rank_offers([offer])
    assert len(ranked) == 1
    assert ranked[0].property_id == "A1"
