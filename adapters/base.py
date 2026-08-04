import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from abc import ABC, abstractmethod
from datetime import date
from typing import Any, Dict, List, Optional
from schemas.offer import UnifiedOffer


class SupplierAdapter(ABC):
    """
    Abstract Base Class defining the unified interface for all supplier adapters.
    
    All returned reservation dictionaries follow a standardized structure:
    
    1. create_reservation(...) -> dict:
        {
            "reservation_id": str,
            "supplier_id": str,
            "property_id": str,
            "status": str,  # "confirmed", "failed"
            "total_price": float,
            "currency": str,
            "guest_name": str,
            "confirmation_code": str,
            "created_at": str  # ISO-8601 timestamp
        }
        
    2. get_reservation_status(...) -> dict:
        {
            "reservation_id": str,
            "supplier_id": str,
            "property_id": str,
            "status": str,  # "confirmed", "cancelled", "pending"
            "guest_name": str,
            "updated_at": str  # ISO-8601 timestamp
        }
        
    3. cancel_reservation(...) -> dict:
        {
            "reservation_id": str,
            "supplier_id": str,
            "status": str,  # "cancelled"
            "cancellation_code": str,
            "refund_amount": float,
            "cancelled_at": str  # ISO-8601 timestamp
        }
    """

    @property
    @abstractmethod
    def supplier_id(self) -> str:
        """Return the unique identifier for this supplier."""
        pass

    @abstractmethod
    async def search_properties(
        self,
        destination: str,
        check_in: date,
        check_out: date,
        guests: int = 1,
        rooms: int = 1
    ) -> List[UnifiedOffer]:
        """Search available property offers for the given parameters."""
        pass

    @abstractmethod
    async def get_pricing_and_availability(
        self,
        property_id: str,
        check_in: date,
        check_out: date,
        guests: int = 1,
        rooms: int = 1,
        room_type: Optional[str] = None
    ) -> UnifiedOffer:
        """Re-check pricing and availability for a specific property and stay."""
        pass

    @abstractmethod
    async def create_reservation(
        self,
        offer: UnifiedOffer,
        guest_details: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Book a reservation given a validated offer and guest details."""
        pass

    @abstractmethod
    async def get_reservation_status(
        self,
        reservation_id: str
    ) -> Dict[str, Any]:
        """Retrieve current reservation status by reservation ID."""
        pass

    @abstractmethod
    async def cancel_reservation(
        self,
        reservation_id: str
    ) -> Dict[str, Any]:
        """Cancel an existing reservation by reservation ID."""
        pass
