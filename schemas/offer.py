from datetime import date
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, model_validator


class AvailabilityStatus(str, Enum):
    AVAILABLE = "available"
    ON_REQUEST = "on_request"
    SOLD_OUT = "sold_out"
    UNAVAILABLE = "unavailable"


class UnifiedOffer(BaseModel):
    """
    Unified hotel offer schema representing normalized data across all hotel suppliers.
    """
    supplier_id: str = Field(..., description="Unique identifier of the supplier (e.g. atlas, nova)")
    property_id: str = Field(..., description="Supplier's internal property identifier")
    property_name: str = Field(..., description="Name of the hotel or stay property")
    location: str = Field(..., description="Location, city, or destination name")
    room_type: str = Field(..., description="Room category or name")
    check_in_date: date = Field(..., description="Check-in date")
    check_out_date: date = Field(..., description="Check-out date")
    currency: str = Field(..., description="3-letter ISO currency code (e.g. USD, EUR)")
    base_price: float = Field(..., description="Base price before taxes and fees")
    taxes_and_fees: float = Field(..., description="Combined taxes, surcharges, and service fees")
    total_price: float = Field(..., description="Grand total price including taxes and fees")
    cancellation_policy: str = Field(..., description="Standardized cancellation policy description")
    availability_status: AvailabilityStatus = Field(
        default=AvailabilityStatus.AVAILABLE,
        description="Current availability status of the room offer"
    )

    @model_validator(mode="after")
    def validate_price_totals(self) -> "UnifiedOffer":
        """
        Validate that base_price + taxes_and_fees equals total_price (within floating point precision).
        """
        expected_total = round(self.base_price + self.taxes_and_fees, 2)
        actual_total = round(self.total_price, 2)
        if abs(expected_total - actual_total) > 0.01:
            raise ValueError(
                f"Total price inconsistency: base_price ({self.base_price}) + "
                f"taxes_and_fees ({self.taxes_and_fees}) = {expected_total}, "
                f"but total_price was {self.total_price}"
            )
        return self
