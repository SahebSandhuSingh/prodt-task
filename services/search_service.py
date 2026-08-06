import asyncio
import logging
import re
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Set, Tuple, Optional

from adapters.exceptions import SupplierError
from adapters.registry import registry
from db.models import (
    FailureLogRecord,
    NormalizedOfferRecord,
    SearchRequestRecord,
    generate_deterministic_offer_id,
)
from db.session import AsyncSessionLocal
from schemas.offer import AvailabilityStatus, UnifiedOffer
from schemas.search import SearchRequest, SearchResponse
from services.ranking import rank_offers

# Configure structured logger for search service
logger = logging.getLogger("search_service")

# Module-level set holding strong references to running background audit tasks
# Prevents Python asyncio garbage collection of unreferenced tasks mid-execution
_background_tasks: Set[asyncio.Task] = set()

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


async def _persist_search_audit_task(
    request: SearchRequest,
    request_id: str,
    suppliers_queried: List[str],
    suppliers_failed: List[str],
    ranked_offers: List[UnifiedOffer],
    failures: List[Dict[str, Any]]
) -> None:
    """
    Background fire-and-forget task persisting search requests, offers, and failure logs.
    
    Best-Effort Policy:
    -------------------
    Errors encountered during DB audit persistence are caught and logged; they NEVER 
    raise exceptions or disrupt the search API response.
    """
    try:
        async with AsyncSessionLocal() as session:
            # 1. Persist SearchRequestRecord
            search_record = SearchRequestRecord(
                request_id=request_id,
                destination=request.destination,
                check_in=request.check_in,
                check_out=request.check_out,
                guests=request.guests,
                rooms=request.rooms,
                suppliers_queried=suppliers_queried,
                suppliers_failed=suppliers_failed,
                created_at=datetime.now(timezone.utc)
            )
            session.add(search_record)
            await session.flush()

            # 2. Persist NormalizedOfferRecord rows
            for idx, offer in enumerate(ranked_offers):
                # Score is inverse rank approximation for DB record
                rank_score = round(1.0 - (idx / max(1, len(ranked_offers))), 4)
                offer_id = generate_deterministic_offer_id(
                    supplier_id=offer.supplier_id,
                    property_id=offer.property_id,
                    room_type=offer.room_type,
                    check_in_date=offer.check_in_date,
                    check_out_date=offer.check_out_date
                )
                offer_record = NormalizedOfferRecord(
                    offer_id=offer_id,
                    request_id=request_id,
                    supplier_id=offer.supplier_id,
                    property_id=offer.property_id,
                    property_name=offer.property_name,
                    location=offer.location,
                    room_type=offer.room_type,
                    check_in_date=offer.check_in_date,
                    check_out_date=offer.check_out_date,
                    currency=offer.currency,
                    base_price=offer.base_price,
                    taxes_and_fees=offer.taxes_and_fees,
                    total_price=offer.total_price,
                    cancellation_policy=offer.cancellation_policy,
                    availability_status=offer.availability_status.value,
                    rank_score=rank_score,
                    created_at=datetime.now(timezone.utc)
                )
                session.add(offer_record)

            # 3. Persist FailureLogRecord rows
            for fail in failures:
                fail_record = FailureLogRecord(
                    context="search",
                    request_id=request_id,
                    supplier_id=fail.get("supplier_id"),
                    error_type=fail.get("error_type", "SupplierError"),
                    error_message=fail.get("error_message", "Unknown error"),
                    retry_attempt_number=fail.get("retry_attempt", 1),
                    occurred_at=datetime.now(timezone.utc)
                )
                session.add(fail_record)

            await session.commit()
    except Exception as e:
        logger.error(
            f"Failed to persist search audit records for request '{request_id}': {e}",
            extra={"request_id": request_id, "error": str(e)}
        )


async def perform_search(
    request: SearchRequest,
    request_id: str
) -> SearchResponse:
    """
    Perform a concurrent hotel search across all registered suppliers.
    """
    suppliers_to_query = registry.list_suppliers()
    suppliers_failed: List[str] = []
    collected_offers: List[UnifiedOffer] = []
    failures_to_log: List[Dict[str, Any]] = []

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
            error_type = result.__class__.__name__
            error_msg = str(result)

            failures_to_log.append({
                "supplier_id": supplier_id,
                "error_type": error_type,
                "error_message": error_msg,
                "retry_attempt": 1
            })

            logger.error(
                f"Supplier '{supplier_id}' failed: {error_msg}",
                extra={"request_id": request_id, "supplier_id": supplier_id, "error": error_msg}
            )
        else:
            collected_offers.extend(result)

    # Filter out unavailable offers
    bookable_offers = [
        offer for offer in collected_offers
        if offer.availability_status in (AvailabilityStatus.AVAILABLE, AvailabilityStatus.ON_REQUEST)
    ]

    # Deduplicate offers (keeping cheaper offer per property)
    deduped_offers = deduplicate_offers(bookable_offers)

    # Rank offers descending by score
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

    # True Fire-and-Forget: launch background task with retained strong reference
    task = asyncio.create_task(
        _persist_search_audit_task(
            request=request,
            request_id=request_id,
            suppliers_queried=suppliers_to_query,
            suppliers_failed=suppliers_failed,
            ranked_offers=ranked_offers,
            failures=failures_to_log
        )
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return SearchResponse(
        results=ranked_offers,
        suppliers_queried=suppliers_to_query,
        suppliers_failed=suppliers_failed,
        request_id=request_id
    )
