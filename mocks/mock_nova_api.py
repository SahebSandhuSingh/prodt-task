from typing import Any, Dict, List, Optional
import uuid
from datetime import datetime, timezone


class MockNovaAPI:
    """
    Simulates the external "Nova Stays API" with constructor-injected failure modes.
    
    Nova API conventions:
    - Field names: propId, title, locationName, roomType, pricing
    - Date format: DD-MM-YYYY (e.g. "01-09-2026")
    - Nightly price structure: nightlyBase * nights + surcharges
    - Cancellation enum: FLEXIBLE_CANCEL, NON_REFUNDABLE_NOVA
    """

    def __init__(self, simulated_failure: Optional[str] = None):
        self.simulated_failure = simulated_failure
        self._bookings: Dict[str, Dict[str, Any]] = {}
        self._idempotency_records: Dict[str, Dict[str, Any]] = {}

        # Hardcoded sample properties for Nova Stays
        self._properties = [
            {
                "propId": "NOV-PAR-101",
                "title": "Nova Boutique Stay Le Marais",
                "locationName": "Paris",
                "roomType": "Superior Loft",
                "pricing": {
                    "nightlyBase": 150.0,
                    "nights": 1,
                    "surcharges": 30.0,
                    "currency": "EUR"
                },
                "cancellation": "FLEXIBLE_CANCEL",
                "status": "AVAILABLE"
            },
            {
                "propId": "NOV-LON-202",
                "title": "Nova Covent Garden Apartments",
                "locationName": "London",
                "roomType": "1-Bedroom Apartment",
                "pricing": {
                    "nightlyBase": 180.0,
                    "nights": 1,
                    "surcharges": 35.0,
                    "currency": "GBP"
                },
                "cancellation": "NON_REFUNDABLE_NOVA",
                "status": "AVAILABLE"
            },
            {
                "propId": "NOV-NYC-201",
                "title": "Nova Times Square Residences",
                "locationName": "New York",
                "roomType": "Skyline Loft",
                "pricing": {
                    "nightlyBase": 320.0,
                    "nights": 1,
                    "surcharges": 60.0,
                    "currency": "USD"
                },
                "cancellation": "FLEXIBLE_CANCEL",
                "status": "AVAILABLE"
            },
            {
                "propId": "NOV-TYO-201",
                "title": "Nova Shibuya Modern Stay",
                "locationName": "Tokyo",
                "roomType": "Urban Studio",
                "pricing": {
                    "nightlyBase": 19000.0,
                    "nights": 1,
                    "surcharges": 3000.0,
                    "currency": "JPY"
                },
                "cancellation": "FLEXIBLE_CANCEL",
                "status": "AVAILABLE"
            },
            {
                "propId": "NOV-SYD-303",
                "title": "Nova Harbour View Villas",
                "locationName": "Sydney",
                "roomType": "Harbour Villa",
                "pricing": {
                    "nightlyBase": 300.0,
                    "nights": 1,
                    "surcharges": 60.0,
                    "currency": "AUD"
                },
                "cancellation": "FLEXIBLE_CANCEL",
                "status": "AVAILABLE"
            },
            {
                "propId": "NOV-ROM-101",
                "title": "Nova Spanish Steps Heritage Stay",
                "locationName": "Rome",
                "roomType": "Classic Balcony Room",
                "pricing": {
                    "nightlyBase": 165.0,
                    "nights": 1,
                    "surcharges": 30.0,
                    "currency": "EUR"
                },
                "cancellation": "FLEXIBLE_CANCEL",
                "status": "AVAILABLE"
            }
        ]

    def _check_simulated_failure(self):
        if self.simulated_failure == "timeout":
            raise TimeoutError("Nova Stays API request timeout after 15000ms")
        elif self.simulated_failure == "500_error":
            raise ConnectionError("Nova Stays Service Unavailable (HTTP 502 Bad Gateway)")

    async def query_available_stays(
        self,
        location: str,
        checkin_str: str,
        checkout_str: str,
        guests: int = 1,
        rooms: int = 1
    ) -> List[Dict[str, Any]]:
        self._check_simulated_failure()

        if self.simulated_failure == "malformed":
            return [
                {
                    "propId": "NOV-CORRUPT",
                    "title": 12345,  # wrong type
                    # missing pricing, locationName, roomType
                }
            ]

        results = []
        for prop in self._properties:
            if location.lower() in prop["locationName"].lower() or prop["locationName"].lower() in location.lower():
                item = dict(prop)
                item["fromDate"] = checkin_str
                item["toDate"] = checkout_str
                results.append(item)
        return results

    async def get_stay_quote(
        self,
        prop_id: str,
        checkin_str: str,
        checkout_str: str
    ) -> Dict[str, Any]:
        self._check_simulated_failure()

        if self.simulated_failure == "malformed":
            return {"propId": prop_id, "error_code": "BROKEN_PAYLOAD"}

        prop = next((p for p in self._properties if p["propId"] == prop_id), None)
        if not prop:
            raise ValueError(f"Property {prop_id} not found in Nova inventory")

        res = dict(prop)
        res["fromDate"] = checkin_str
        res["toDate"] = checkout_str

        if self.simulated_failure == "price_changed":
            res = dict(prop)
            res["fromDate"] = checkin_str
            res["toDate"] = checkout_str
            res["pricing"] = {
                "nightlyBase": prop["pricing"]["nightlyBase"] + 40.0,
                "nights": prop["pricing"]["nights"],
                "surcharges": prop["pricing"]["surcharges"] + 10.0,
                "currency": prop["pricing"]["currency"]
            }

        return res

    async def place_booking(
        self,
        prop_id: str,
        lead_guest: str,
        checkin_str: str,
        checkout_str: str,
        quoted_total: float,
        idempotency_key: Optional[str] = None
    ) -> Dict[str, Any]:
        self._check_simulated_failure()

        if idempotency_key and idempotency_key in self._idempotency_records:
            return self._idempotency_records[idempotency_key]

        if self.simulated_failure == "malformed":
            return {"res": "ok"}

        booking_code = f"NOV-BK-{uuid.uuid4().hex[:8].upper()}"
        prop = next((p for p in self._properties if p["propId"] == prop_id), None)
        pricing = prop["pricing"] if prop else {"nightlyBase": 100.0, "surcharges": 20.0, "currency": "EUR"}
        total = (pricing["nightlyBase"] * pricing.get("nights", 1)) + pricing["surcharges"]

        record = {
            "bookingCode": booking_code,
            "propId": prop_id,
            "guestName": lead_guest,
            "state": "ACTIVE",
            "chargedAmount": total,
            "currency": pricing["currency"],
            "securityCode": uuid.uuid4().hex[:6].upper(),
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z"
        }
        self._bookings[booking_code] = record
        if idempotency_key:
            self._idempotency_records[idempotency_key] = record
        return record

    async def query_booking_state(self, booking_code: str) -> Dict[str, Any]:
        self._check_simulated_failure()

        if self.simulated_failure == "malformed":
            return {"id": booking_code}

        if booking_code not in self._bookings:
            raise ValueError(f"Nova booking {booking_code} not found")

        return self._bookings[booking_code]

    async def void_booking(self, booking_code: str) -> Dict[str, Any]:
        self._check_simulated_failure()

        if self.simulated_failure == "malformed":
            return {"status": "voided"}

        if booking_code not in self._bookings:
            raise ValueError(f"Nova booking {booking_code} not found")

        record = self._bookings[booking_code]
        record["state"] = "VOIDED"

        return {
            "bookingCode": booking_code,
            "state": "VOIDED",
            "cancellationAuth": f"NOV-VOID-{uuid.uuid4().hex[:6].upper()}",
            "refundedSum": record["chargedAmount"],
            "voidedTimestamp": datetime.now(timezone.utc).isoformat() + "Z"
        }
