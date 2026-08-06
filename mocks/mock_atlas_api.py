from typing import Any, Dict, List, Optional
import uuid
from datetime import datetime, timezone


class MockAtlasAPI:
    """
    Simulates the external "Atlas Hotels API" with constructor-injected failure modes.
    
    Atlas API conventions:
    - Field names: hotel_code, dest_city, room_info, price_breakdown
    - Date format: YYYY-MM-DD
    - Nested price objects: net_amount, tax_and_service, gross_amount, currency_code
    - Policy string enum: FREE_CANCEL_24H, NON_REFUNDABLE_ATLAS
    """

    def __init__(self, simulated_failure: Optional[str] = None):
        self.simulated_failure = simulated_failure
        self._reservations: Dict[str, Dict[str, Any]] = {}
        self._idempotency_records: Dict[str, Dict[str, Any]] = {}
        
        # Hardcoded sample properties for Atlas Hotels
        self._properties = [
            {
                "hotel_code": "ATL-PAR-01",
                "name": "Atlas Grand Hotel Paris",
                "dest_city": "Paris",
                "room_info": {"category": "Deluxe King", "vacant": True},
                "price_breakdown": {
                    "net_amount": 200.0,
                    "tax_and_service": 40.0,
                    "gross_amount": 240.0,
                    "currency_code": "EUR"
                },
                "policy": {"cancel_terms": "FREE_CANCEL_24H"}
            },
            {
                "hotel_code": "ATL-NYC-02",
                "name": "Atlas Manhattan Suites",
                "dest_city": "New York",
                "room_info": {"category": "Executive Suite", "vacant": True},
                "price_breakdown": {
                    "net_amount": 350.0,
                    "tax_and_service": 70.0,
                    "gross_amount": 420.0,
                    "currency_code": "USD"
                },
                "policy": {"cancel_terms": "NON_REFUNDABLE_ATLAS"}
            },
            {
                "hotel_code": "ATL-TYO-03",
                "name": "Atlas Tokyo Bay Resort",
                "dest_city": "Tokyo",
                "room_info": {"category": "Ocean View Double", "vacant": True},
                "price_breakdown": {
                    "net_amount": 28000.0,
                    "tax_and_service": 2800.0,
                    "gross_amount": 30800.0,
                    "currency_code": "JPY"
                },
                "policy": {"cancel_terms": "FREE_CANCEL_24H"}
            }
        ]

    def _check_simulated_failure(self):
        if self.simulated_failure == "timeout":
            raise TimeoutError("Atlas API timed out after 30000ms")
        elif self.simulated_failure == "500_error":
            raise RuntimeError("Atlas API Internal Server Error (500): Connection pool exhausted")

    async def search_hotels(
        self,
        city: str,
        start_date: str,
        end_date: str,
        num_guests: int = 1,
        num_rooms: int = 1
    ) -> List[Dict[str, Any]]:
        self._check_simulated_failure()
        
        if self.simulated_failure == "malformed":
            return [
                {
                    "hotel_code": "ATL-BAD-00",
                    "invalid_name": None,
                    # missing price_breakdown, dest_city, policy
                }
            ]

        results = []
        for prop in self._properties:
            if city.lower() in prop["dest_city"].lower() or prop["dest_city"].lower() in city.lower():
                item = dict(prop)
                item["stay_period"] = {"start": start_date, "end": end_date}
                results.append(item)
        return results

    async def fetch_hotel_details(
        self,
        hotel_code: str,
        start_date: str,
        end_date: str,
        room_cat: Optional[str] = None
    ) -> Dict[str, Any]:
        self._check_simulated_failure()

        if self.simulated_failure == "malformed":
            return {"hotel_code": hotel_code, "corrupted": True}

        prop = next((p for p in self._properties if p["hotel_code"] == hotel_code), None)
        if not prop:
            raise KeyError(f"Hotel {hotel_code} not found in Atlas database")

        res = dict(prop)
        res["stay_period"] = {"start": start_date, "end": end_date}

        if self.simulated_failure == "price_changed":
            # Increase gross amount
            res = dict(prop)
            res["stay_period"] = {"start": start_date, "end": end_date}
            res["price_breakdown"] = {
                "net_amount": prop["price_breakdown"]["net_amount"] + 50.0,
                "tax_and_service": prop["price_breakdown"]["tax_and_service"] + 10.0,
                "gross_amount": prop["price_breakdown"]["gross_amount"] + 60.0,
                "currency_code": prop["price_breakdown"]["currency_code"]
            }

        return res

    async def book_stay(
        self,
        hotel_code: str,
        guest_info: Dict[str, Any],
        start_date: str,
        end_date: str,
        expected_price: float,
        idempotency_key: Optional[str] = None
    ) -> Dict[str, Any]:
        self._check_simulated_failure()

        if idempotency_key and idempotency_key in self._idempotency_records:
            return self._idempotency_records[idempotency_key]

        if self.simulated_failure == "malformed":
            return {"status": "OK"}  # missing booking ref and details

        booking_ref = f"ATL-RES-{uuid.uuid4().hex[:8].upper()}"
        prop = next((p for p in self._properties if p["hotel_code"] == hotel_code), None)
        price = prop["price_breakdown"]["gross_amount"] if prop else expected_price
        currency = prop["price_breakdown"]["currency_code"] if prop else "USD"

        reservation = {
            "atlas_booking_id": booking_ref,
            "hotel_code": hotel_code,
            "guest_full_name": guest_info.get("name", "Unknown Guest"),
            "booking_status": "CONFIRMED",
            "total_charged": price,
            "currency": currency,
            "confirmation_pin": uuid.uuid4().hex[:6].upper(),
            "timestamp_iso": datetime.now(timezone.utc).isoformat() + "Z"
        }
        self._reservations[booking_ref] = reservation
        if idempotency_key:
            self._idempotency_records[idempotency_key] = reservation
        return reservation

    async def fetch_booking(self, booking_ref: str) -> Dict[str, Any]:
        self._check_simulated_failure()

        if self.simulated_failure == "malformed":
            return {"raw_id": booking_ref}

        if booking_ref not in self._reservations:
            raise KeyError(f"Atlas booking {booking_ref} not found")

        return self._reservations[booking_ref]

    async def cancel_booking(self, booking_ref: str) -> Dict[str, Any]:
        self._check_simulated_failure()

        if self.simulated_failure == "malformed":
            return {"cancelled": "yes"}

        if booking_ref not in self._reservations:
            raise KeyError(f"Atlas booking {booking_ref} not found")

        res = self._reservations[booking_ref]
        res["booking_status"] = "CANCELLED"
        
        return {
            "atlas_booking_id": booking_ref,
            "booking_status": "CANCELLED",
            "cancellation_ref": f"ATL-CNL-{uuid.uuid4().hex[:6].upper()}",
            "refund_issued": res["total_charged"],
            "cancellation_time": datetime.now(timezone.utc).isoformat() + "Z"
        }
