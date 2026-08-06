import asyncio
import logging
import re
from typing import Dict, List, Set, Tuple
from datetime import date

from adapters.exceptions import SupplierError
from adapters.registry import registry
from schemas.offer import AvailabilityStatus, UnifiedOffer
from schemas.search import SearchRequest, SearchResponse
from services.ranking import rank_offers

# Configure structured logger for search service
logger = logging.getLogger("search_service")

# Default maximum timeout allowed per supplier call (in seconds)
DEFAULT_SUPPLIER_TIMEOUT: float = 5.0


def _normalize_string(text: str) -> str:
    """Normalize string by lowercasing, stripping punctuation, and compressing spaces."""
    cleaned = re.sub(r"[^\w\s]", "", text.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def deduplicate_offers(offers: List[UnifiedOffer]) -> List[UnifiedOffer]:
    """
    Deduplicate hotel offers representing the same physical property across suppliers.
    
    Heuristic:
    ----------
    - Properties are matched using a composite key: (normalized_property_name, normalized_location).
    - When duplicate properties are identified from multiple suppliers, the **cheaper offer** 
      (lowest total_price) is retained to ensure maximum value for the user.
    """
    grouped_offers: Dict[Tuple[str, str], UnifiedOffer] = {}

    for offer in offers:
        norm_name = _normalize_string(offer.property_name)
        norm_loc = _normalize_string(offer.location)
        key = (norm_name, norm_loc)

        if key not in grouped_offers:
            grouped_offers[key] = offer
        else:
            existing = grouped_offers[key]
            # Retain the offer with the lower total_price
            if offer.total_price < existing.total_price:
                grouped_offers[key] = offer

    return list(grouped_offers.values())


async def _search_supplier(
    supplier_id: str,
    request: SearchRequest,
    timeout: float = DEFAULT_SUPPLIER_TIMEOUT
) -> List[UnifiedOffer]:
    """
    Execute a search against a single supplier adapter with strict timeout protection.
    """
    adapter = registry.get(supplier_id)
    return await asyncio.wait_for(
        adapter.search_properties(
            destination=request.destination,
            check_in=request.check_in,
            check_out=request.check_out,
            guests=request.guests,
            rooms=request.rooms
        ),
        timeout=timeout
    )


async def perform_search(
    request: SearchRequest,
    request_id: str
) -> SearchResponse:
    """
    Perform a concurrent hotel search across all registered suppliers.
    
    Workflow:
    ---------
    1. Query all registered suppliers concurrently using asyncio.gather.
    2. Catch supplier exceptions & timeouts safely; track failed suppliers.
    3. Filter out unavailable offers.
    4. Deduplicate offers matching the same property (retaining cheaper offer).
    5. Rank results descending by composite score.
    6. Return unified SearchResponse.
    """
    suppliers_to_query = registry.list_suppliers()
    suppliers_failed: List[str] = []
    collected_offers: List[UnifiedOffer] = []

    logger.info(
        "Initiating search",
        extra={
            "request_id": request_id,
            "destination": request.destination,
            "check_in": request.check_in.isoformat(),
            "check_out": request.check_out.isoformat(),
            "suppliers_queried": suppliers_to_query
        }
    )

    if not suppliers_to_query:
        return SearchResponse(
            results=[],
            suppliers_queried=[],
            suppliers_failed=[],
            request_id=request_id
        )

    # Launch supplier tasks concurrently
    tasks = [
        _search_supplier(supplier_id, request)
        for supplier_id in suppliers_to_query
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Process results per supplier
    for supplier_id, result in zip(suppliers_to_query, results):
        if isinstance(result, Exception):
            suppliers_failed.append(supplier_id)
            if isinstance(result, SupplierError):
                logger.error(
                    f"Supplier '{supplier_id}' failed: {result.message}",
                    extra={"request_id": request_id, "supplier_id": supplier_id, "error": str(result)}
                )
            elif isinstance(result, asyncio.TimeoutError):
                logger.error(
                    f"Supplier '{supplier_id}' timed out after {DEFAULT_SUPPLIER_TIMEOUT}s",
                    extra={"request_id": request_id, "supplier_id": supplier_id}
                )
            else:
                logger.error(
                    f"Supplier '{supplier_id}' unexpected error: {result}",
                    extra={"request_id": request_id, "supplier_id": supplier_id, "error": str(result)}
                )
        else:
            collected_offers.extend(result)

    # Filter out unavailable offers (keep AVAILABLE or ON_REQUEST)
    bookable_offers = [
        offer for offer in collected_offers
        if offer.availability_status in (AvailabilityStatus.AVAILABLE, AvailabilityStatus.ON_REQUEST)
    ]

    # Deduplicate offers (keeping cheaper offer per physical property)
    deduped_offers = deduplicate_offers(bookable_offers)

    # Rank offers descending by composite score
    ranked_offers = rank_offers(deduped_offers)

    logger.info(
        "Search completed",
        extra={
            "request_id": request_id,
            "destination": request.destination,
            "suppliers_queried": suppliers_to_query,
            "suppliers_failed": suppliers_failed,
            "raw_offers_count": len(collected_offers),
            "final_results_count": len(ranked_offers)
        }
    )

    return SearchResponse(
        results=ranked_offers,
        suppliers_queried=suppliers_to_query,
        suppliers_failed=suppliers_failed,
        request_id=request_id
    )
