from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from adapters.base import SupplierAdapter
from adapters.exceptions import (
    SupplierBookingError,
    SupplierError,
    SupplierMalformedResponseError,
    SupplierNotFoundError,
    SupplierPriceChangedError,
    SupplierServerError,
    SupplierTimeoutError,
)
from mocks.mock_nova_api import MockNovaAPI
from schemas.offer import AvailabilityStatus, UnifiedOffer


class NovaAdapter(SupplierAdapter):
    """
    Adapter integrating Nova Stays API with the unified internal schema.
    """

    def __init__(self, api: Optional[MockNovaAPI] = None):
        self.api = api or MockNovaAPI()

    @property
    def supplier_id(self) -> str:
        return "nova"

    def _format_date(self, d: date) -> str:
        return d.strftime("%d-%m-%Y")

    def _parse_date(self, d_str: str) -> date:
        return datetime.strptime(d_str, "%d-%m-%Y").date()

    def _normalize_cancellation_policy(self, raw_policy: str) -> str:
        if raw_policy == "FLEXIBLE_CANCEL":
            return "Flexible cancellation"
        elif raw_policy == "NON_REFUNDABLE_NOVA":
            return "Non-refundable"
        return raw_policy or "Standard policy"

    def _parse_offer(self, item: Dict[str, Any], check_in: date, check_out: date) -> UnifiedOffer:
        try:
            prop_id = item["propId"]
            title = str(item["title"])
            location = str(item.get("locationName", "Unknown Location"))
            room_type = str(item.get("roomType", "Standard Room"))

            pricing = item["pricing"]
            nightly_base = float(pricing["nightlyBase"])
            nights = int(pricing.get("nights", 1))
            base_price = nightly_base * nights
            taxes_and_fees = float(pricing["surcharges"])
            total_price = round(base_price + taxes_and_fees, 2)
            currency = str(pricing["currency"])

            cancellation = self._normalize_cancellation_policy(item.get("cancellation", ""))
            status_str = item.get("status", "AVAILABLE")
            avail_status = AvailabilityStatus.AVAILABLE if status_str == "AVAILABLE" else AvailabilityStatus.UNAVAILABLE

            return UnifiedOffer(
                supplier_id=self.supplier_id,
                property_id=prop_id,
                property_name=title,
                location=location,
                room_type=room_type,
                check_in_date=check_in,
                check_out_date=check_out,
                currency=currency,
                base_price=base_price,
                taxes_and_fees=taxes_and_fees,
                total_price=total_price,
                cancellation_policy=cancellation,
                availability_status=avail_status,
            )
        except (KeyError, TypeError, ValueError) as e:
            raise SupplierMalformedResponseError(
                f"Failed to parse Nova offer response: {e}",
                supplier_id=self.supplier_id,
                original_error=e
            )

    async def search_properties(
        self,
        destination: str,
        check_in: date,
        check_out: date,
        guests: int = 1,
        rooms: int = 1
    ) -> List[UnifiedOffer]:
        try:
            raw_results = await self.api.query_available_stays(
                location=destination,
                checkin_str=self._format_date(check_in),
                checkout_str=self._format_date(check_out),
                guests=guests,
                rooms=rooms
            )
            return [self._parse_offer(item, check_in, check_out) for item in raw_results]
        except TimeoutError as e:
            raise SupplierTimeoutError(str(e), supplier_id=self.supplier_id, original_error=e)
        except ConnectionError as e:
            raise SupplierServerError(str(e), supplier_id=self.supplier_id, original_error=e)
        except SupplierError:
            raise
        except Exception as e:
            raise SupplierMalformedResponseError(f"Unexpected error searching Nova: {e}", supplier_id=self.supplier_id, original_error=e)

    async def get_pricing_and_availability(
        self,
        property_id: str,
        check_in: date,
        check_out: date,
        guests: int = 1,
        rooms: int = 1,
        room_type: Optional[str] = None
    ) -> UnifiedOffer:
        try:
            raw_quote = await self.api.get_stay_quote(
                prop_id=property_id,
                checkin_str=self._format_date(check_in),
                checkout_str=self._format_date(check_out)
            )
            offer = self._parse_offer(raw_quote, check_in, check_out)

            if self.api.simulated_failure == "price_changed":
                raise SupplierPriceChangedError(
                    f"Price changed for Nova property {property_id}",
                    supplier_id=self.supplier_id,
                    old_price=offer.total_price - 50.0,
                    new_price=offer.total_price
                )

            return offer
        except TimeoutError as e:
            raise SupplierTimeoutError(str(e), supplier_id=self.supplier_id, original_error=e)
        except ConnectionError as e:
            raise SupplierServerError(str(e), supplier_id=self.supplier_id, original_error=e)
        except ValueError as e:
            if "not found" in str(e).lower():
                raise SupplierNotFoundError(str(e), supplier_id=self.supplier_id, original_error=e)
            raise SupplierMalformedResponseError(str(e), supplier_id=self.supplier_id, original_error=e)
        except SupplierError:
            raise
        except Exception as e:
            raise SupplierMalformedResponseError(f"Unexpected error fetching Nova quote: {e}", supplier_id=self.supplier_id, original_error=e)

    async def create_reservation(
        self,
        offer: UnifiedOffer,
        guest_details: Dict[str, Any]
    ) -> Dict[str, Any]:
        try:
            guest_name = guest_details.get("name", "Unknown Guest")
            raw_booking = await self.api.place_booking(
                prop_id=offer.property_id,
                lead_guest=guest_name,
                checkin_str=self._format_date(offer.check_in_date),
                checkout_str=self._format_date(offer.check_out_date),
                quoted_total=offer.total_price
            )

            status = "confirmed" if raw_booking.get("state") == "ACTIVE" else "failed"

            return {
                "reservation_id": raw_booking["bookingCode"],
                "supplier_id": self.supplier_id,
                "property_id": raw_booking.get("propId", offer.property_id),
                "status": status,
                "total_price": float(raw_booking["chargedAmount"]),
                "currency": raw_booking["currency"],
                "guest_name": raw_booking.get("guestName", guest_name),
                "confirmation_code": raw_booking.get("securityCode", ""),
                "created_at": raw_booking.get("timestamp", datetime.now(timezone.utc).isoformat() + "Z")
            }
        except TimeoutError as e:
            raise SupplierTimeoutError(str(e), supplier_id=self.supplier_id, original_error=e)
        except ConnectionError as e:
            raise SupplierServerError(str(e), supplier_id=self.supplier_id, original_error=e)
        except (KeyError, TypeError, ValueError) as e:
            raise SupplierMalformedResponseError(f"Nova booking payload invalid: {e}", supplier_id=self.supplier_id, original_error=e)
        except SupplierError:
            raise
        except Exception as e:
            raise SupplierBookingError(f"Nova reservation creation failed: {e}", supplier_id=self.supplier_id, original_error=e)

    async def get_reservation_status(
        self,
        reservation_id: str
    ) -> Dict[str, Any]:
        try:
            raw_state = await self.api.query_booking_state(reservation_id)
            state = raw_state["state"]
            status = "confirmed" if state == "ACTIVE" else ("cancelled" if state == "VOIDED" else state.lower())

            return {
                "reservation_id": raw_state["bookingCode"],
                "supplier_id": self.supplier_id,
                "property_id": raw_state.get("propId", ""),
                "status": status,
                "guest_name": raw_state.get("guestName", ""),
                "updated_at": raw_state.get("timestamp", datetime.now(timezone.utc).isoformat() + "Z")
            }
        except TimeoutError as e:
            raise SupplierTimeoutError(str(e), supplier_id=self.supplier_id, original_error=e)
        except ConnectionError as e:
            raise SupplierServerError(str(e), supplier_id=self.supplier_id, original_error=e)
        except ValueError as e:
            if "not found" in str(e).lower():
                raise SupplierNotFoundError(f"Nova booking {reservation_id} not found", supplier_id=self.supplier_id, original_error=e)
            raise SupplierMalformedResponseError(f"Invalid Nova status data: {e}", supplier_id=self.supplier_id, original_error=e)
        except (TypeError, KeyError) as e:
            raise SupplierMalformedResponseError(f"Invalid Nova status data: {e}", supplier_id=self.supplier_id, original_error=e)

    async def cancel_reservation(
        self,
        reservation_id: str
    ) -> Dict[str, Any]:
        try:
            raw_void = await self.api.void_booking(reservation_id)
            return {
                "reservation_id": raw_void["bookingCode"],
                "supplier_id": self.supplier_id,
                "status": "cancelled" if raw_void.get("state") == "VOIDED" else raw_void.get("state", "").lower(),
                "cancellation_code": raw_void["cancellationAuth"],
                "refund_amount": float(raw_void["refundedSum"]),
                "cancelled_at": raw_void.get("voidedTimestamp", datetime.now(timezone.utc).isoformat() + "Z")
            }
        except TimeoutError as e:
            raise SupplierTimeoutError(str(e), supplier_id=self.supplier_id, original_error=e)
        except ConnectionError as e:
            raise SupplierServerError(str(e), supplier_id=self.supplier_id, original_error=e)
        except ValueError as e:
            if "not found" in str(e).lower():
                raise SupplierNotFoundError(f"Nova booking {reservation_id} not found to void", supplier_id=self.supplier_id, original_error=e)
            raise SupplierMalformedResponseError(f"Invalid Nova void response: {e}", supplier_id=self.supplier_id, original_error=e)
        except (TypeError, KeyError) as e:
            raise SupplierMalformedResponseError(f"Invalid Nova void response: {e}", supplier_id=self.supplier_id, original_error=e)
