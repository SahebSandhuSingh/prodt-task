from typing import Dict, List
from schemas.offer import AvailabilityStatus, UnifiedOffer

# Named scoring weights (must sum to 1.0)
PRICE_WEIGHT: float = 0.50
AVAILABILITY_WEIGHT: float = 0.30
SUPPLIER_WEIGHT: float = 0.20

# Static supplier confidence configuration
SUPPLIER_CONFIDENCE: Dict[str, float] = {
    "atlas": 0.90,
    "nova": 0.85,
}
DEFAULT_SUPPLIER_CONFIDENCE: float = 0.80


def calculate_offer_score(
    offer: UnifiedOffer,
    min_price: float,
    max_price: float
) -> float:
    """
    Calculate a normalized composite score for a single UnifiedOffer.
    
    Formula Breakdown:
    ------------------
    1. Price Score [0.0 - 1.0]:
       - Uses min-max normalization inverted so that lower total_price yields higher score.
       - Price Score = 1.0 - ((total_price - min_price) / (max_price - min_price))
       - If all offers in the set have identical price (max_price == min_price), Price Score = 1.0.
       
    2. Availability Score [0.0 - 1.0]:
       - AVAILABLE -> 1.0
       - ON_REQUEST -> 0.7
       - Others (UNAVAILABLE, SOLD_OUT) -> 0.0
       
    3. Supplier Confidence Weight [0.0 - 1.0]:
       - Retrieved from SUPPLIER_CONFIDENCE dictionary (Atlas: 0.90, Nova: 0.85, default: 0.80).
       
    Final Score = (PRICE_WEIGHT * Price Score) + (AVAILABILITY_WEIGHT * Availability Score) + (SUPPLIER_WEIGHT * Supplier Weight)
    """
    # 1. Price Score (Inverted min-max)
    if max_price == min_price:
        price_score = 1.0
    else:
        price_score = 1.0 - ((offer.total_price - min_price) / (max_price - min_price))
        price_score = max(0.0, min(1.0, price_score))  # clamp bounds

    # 2. Availability Score
    if offer.availability_status == AvailabilityStatus.AVAILABLE:
        availability_score = 1.0
    elif offer.availability_status == AvailabilityStatus.ON_REQUEST:
        availability_score = 0.7
    else:
        availability_score = 0.0

    # 3. Supplier Confidence Weight
    supplier_score = SUPPLIER_CONFIDENCE.get(
        offer.supplier_id.lower(),
        DEFAULT_SUPPLIER_CONFIDENCE
    )

    # Weighted Sum
    final_score = (
        (PRICE_WEIGHT * price_score) +
        (AVAILABILITY_WEIGHT * availability_score) +
        (SUPPLIER_WEIGHT * supplier_score)
    )
    return final_score


def rank_offers(offers: List[UnifiedOffer]) -> List[UnifiedOffer]:
    """
    Rank a list of UnifiedOffer instances descending by composite score.
    
    Returns a new sorted list without mutating input.
    """
    if not offers:
        return []

    prices = [offer.total_price for offer in offers]
    min_price = min(prices)
    max_price = max(prices)

    # Sort offers by computed score descending
    scored_offers = [
        (calculate_offer_score(offer, min_price, max_price), offer)
        for offer in offers
    ]
    scored_offers.sort(key=lambda item: item[0], reverse=True)

    return [offer for _, offer in scored_offers]
