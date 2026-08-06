from datetime import date
from typing import List
from pydantic import BaseModel, Field, model_validator

from schemas.offer import UnifiedOffer


class SearchRequest(BaseModel):
    """
    Hotel search request parameters with field validation.
    """
    destination: str = Field(..., description="Target city, region, or destination name", min_length=1)
    check_in: date = Field(..., description="Check-in date")
    check_out: date = Field(..., description="Check-out date")
    guests: int = Field(1, description="Number of adult guests (must be > 0)", gt=0)
    rooms: int = Field(1, description="Number of rooms requested (must be > 0)", gt=0)

    @model_validator(mode="after")
    def validate_dates(self) -> "SearchRequest":
        """
        Validate that check_out date strictly follows check_in date.
        """
        if self.check_out <= self.check_in:
            raise ValueError(
                f"check_out date ({self.check_out}) must be strictly after check_in date ({self.check_in})"
            )
        return self


class SearchResponse(BaseModel):
    """
    Unified hotel search response containing aggregated, normalized, and ranked offers.
    """
    results: List[UnifiedOffer] = Field(default_factory=list, description="Ranked list of normalized offers")
    suppliers_queried: List[str] = Field(default_factory=list, description="List of supplier IDs queried")
    suppliers_failed: List[str] = Field(default_factory=list, description="List of supplier IDs that experienced errors")
    request_id: str = Field(..., description="Unique request tracing ID (UUID4)")
