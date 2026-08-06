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
from mocks.mock_atlas_api import MockAtlasAPI
from schemas.offer import AvailabilityStatus, UnifiedOffer


class AtlasAdapter(SupplierAdapter):
    """
    Adapter integrating Atlas Hotels API with the unified internal schema.
    """

    def __init__(self, api: Optional[MockAtlasAPI] = None):
        self.api = api or MockAtlasAPI()

    @property
    def supplier_id(self) -> str:
        return "atlas"

    def _normalize_cancellation_policy(self, raw_policy: Dict[str, Any]) -> str:
        code = raw_policy.get("cancel_terms", "")
        if code == "FREE_CANCEL_24H":
            return "Free cancellation up to 24 hours before check-in"
        elif code == "NON_REFUNDABLE_ATLAS":
            return "Non-refundable"
        return code or "Standard policy"

    def _parse_offer(self, item: Dict[str, Any], check_in: date, check_out: date) -> UnifiedOffer:
        try:
            hotel_code = item["hotel_code"]
            name = item.get("name", "Unknown Atlas Hotel")
            city = item.get("dest_city", "Unknown City")
            room_info = item.get("room_info", {})
            room_type = room_info.get("category", "Standard Room")
            vacant = room_info.get("vacant", True)

            price_breakdown = item["price_breakdown"]
            base_price = float(price_breakdown["net_amount"])
            taxes = float(price_breakdown["tax_and_service"])
            total = float(price_breakdown["gross_amount"])
            currency = str(price_breakdown["currency_code"])

            policy_str = self._normalize_cancellation_policy(item.get("policy", {}))
            status = AvailabilityStatus.AVAILABLE if vacant else AvailabilityStatus.UNAVAILABLE

            return UnifiedOffer(
                supplier_id=self.supplier_id,
                property_id=hotel_code,
                property_name=name,
                location=city,
                room_type=room_type,
                check_in_date=check_in,
                check_out_date=check_out,
                currency=currency,
                base_price=base_price,
                taxes_and_fees=taxes,
                total_price=total,
                cancellation_policy=policy_str,
                availability_status=status,
            )
        except (KeyError, TypeError, ValueError) as e:
            raise SupplierMalformedResponseError(
                f"Failed to parse Atlas offer response: {e}",
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
            raw_results = await self.api.search_hotels(
                city=destination,
                start_date=check_in.isoformat(),
                end_date=check_out.isoformat(),
                num_guests=guests,
                num_rooms=rooms
            )
            return [self._parse_offer(item, check_in, check_out) for item in raw_results]
        except TimeoutError as e:
            raise SupplierTimeoutError(str(e), supplier_id=self.supplier_id, original_error=e)
        except RuntimeError as e:
            raise SupplierServerError(str(e), supplier_id=self.supplier_id, original_error=e)
        except SupplierError:
            raise
        except Exception as e:
            raise SupplierMalformedResponseError(f"Unexpected error searching Atlas: {e}", supplier_id=self.supplier_id, original_error=e)

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
            raw_details = await self.api.fetch_hotel_details(
                hotel_code=property_id,
                start_date=check_in.isoformat(),
                end_date=check_out.isoformat(),
                room_cat=room_type
            )
            offer = self._parse_offer(raw_details, check_in, check_out)

            if self.api.simulated_failure == "price_changed":
                raise SupplierPriceChangedError(
                    f"Price changed for Atlas property {property_id}",
                    supplier_id=self.supplier_id,
                    old_price=offer.total_price - 60.0,
                    new_price=offer.total_price
                )

            return offer
        except TimeoutError as e:
            raise SupplierTimeoutError(str(e), supplier_id=self.supplier_id, original_error=e)
        except RuntimeError as e:
            raise SupplierServerError(str(e), supplier_id=self.supplier_id, original_error=e)
        except KeyError as e:
            raise SupplierNotFoundError(str(e), supplier_id=self.supplier_id, original_error=e)
        except SupplierError:
            raise
        except Exception as e:
            raise SupplierMalformedResponseError(f"Unexpected error fetching Atlas details: {e}", supplier_id=self.supplier_id, original_error=e)

    async def create_reservation(
        self,
        offer: UnifiedOffer,
        guest_details: Dict[str, Any],
        idempotency_key: Optional[str] = None
    ) -> Dict[str, Any]:
        try:
            raw_res = await self.api.book_stay(
                hotel_code=offer.property_id,
                guest_info=guest_details,
                start_date=offer.check_in_date.isoformat(),
                end_date=offer.check_out_date.isoformat(),
                expected_price=offer.total_price,
                idempotency_key=idempotency_key
            )
            
            return {
                "reservation_id": raw_res["atlas_booking_id"],
                "supplier_id": self.supplier_id,
                "property_id": raw_res.get("hotel_code", offer.property_id),
                "status": raw_res.get("booking_status", "CONFIRMED").lower(),
                "total_price": float(raw_res["total_charged"]),
                "currency": raw_res["currency"],
                "guest_name": raw_res.get("guest_full_name", guest_details.get("name", "Unknown")),
                "confirmation_code": raw_res.get("confirmation_pin", ""),
                "created_at": raw_res.get("timestamp_iso", datetime.now(timezone.utc).isoformat() + "Z")
            }
        except TimeoutError as e:
            raise SupplierTimeoutError(str(e), supplier_id=self.supplier_id, original_error=e)
        except RuntimeError as e:
            raise SupplierServerError(str(e), supplier_id=self.supplier_id, original_error=e)
        except (KeyError, TypeError, ValueError) as e:
            raise SupplierMalformedResponseError(f"Atlas booking payload invalid: {e}", supplier_id=self.supplier_id, original_error=e)
        except SupplierError:
            raise
        except Exception as e:
            raise SupplierBookingError(f"Atlas reservation creation failed: {e}", supplier_id=self.supplier_id, original_error=e)

    async def get_reservation_status(
        self,
        reservation_id: str
    ) -> Dict[str, Any]:
        try:
            raw_res = await self.api.fetch_booking(reservation_id)
            return {
                "reservation_id": raw_res["atlas_booking_id"],
                "supplier_id": self.supplier_id,
                "property_id": raw_res["hotel_code"],
                "status": raw_res["booking_status"].lower(),
                "guest_name": raw_res["guest_full_name"],
                "updated_at": raw_res.get("timestamp_iso", datetime.now(timezone.utc).isoformat() + "Z")
            }
        except TimeoutError as e:
            raise SupplierTimeoutError(str(e), supplier_id=self.supplier_id, original_error=e)
        except RuntimeError as e:
            raise SupplierServerError(str(e), supplier_id=self.supplier_id, original_error=e)
        except KeyError as e:
            raise SupplierNotFoundError(f"Atlas reservation {reservation_id} not found: {e}", supplier_id=self.supplier_id, original_error=e)
        except (TypeError, ValueError) as e:
            raise SupplierMalformedResponseError(f"Invalid reservation data from Atlas: {e}", supplier_id=self.supplier_id, original_error=e)

    async def cancel_reservation(
        self,
        reservation_id: str
    ) -> Dict[str, Any]:
        try:
            raw_res = await self.api.cancel_booking(reservation_id)
            return {
                "reservation_id": raw_res["atlas_booking_id"],
                "supplier_id": self.supplier_id,
                "status": raw_res["booking_status"].lower(),
                "cancellation_code": raw_res["cancellation_ref"],
                "refund_amount": float(raw_res["refund_issued"]),
                "cancelled_at": raw_res.get("cancellation_time", datetime.now(timezone.utc).isoformat() + "Z")
            }
        except TimeoutError as e:
            raise SupplierTimeoutError(str(e), supplier_id=self.supplier_id, original_error=e)
        except RuntimeError as e:
            raise SupplierServerError(str(e), supplier_id=self.supplier_id, original_error=e)
        except KeyError as e:
            raise SupplierNotFoundError(f"Atlas reservation {reservation_id} not found to cancel", supplier_id=self.supplier_id, original_error=e)
        except (TypeError, ValueError) as e:
            raise SupplierMalformedResponseError(f"Invalid cancellation response from Atlas: {e}", supplier_id=self.supplier_id, original_error=e)
