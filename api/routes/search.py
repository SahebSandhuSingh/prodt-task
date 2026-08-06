import uuid
from fastapi import APIRouter, status
from schemas.search import SearchRequest, SearchResponse
from services.search_service import perform_search

router = APIRouter(tags=["Search"])


@router.get("/health", status_code=status.HTTP_200_OK)
async def health_check():
    """Basic service healthcheck endpoint."""
    return {"status": "healthy"}


@router.post("/search/hotels", response_model=SearchResponse, status_code=status.HTTP_200_OK)
async def search_hotels(request: SearchRequest):
    """
    Search available hotel offers across all registered suppliers.
    """
    request_id = str(uuid.uuid4())
    return await perform_search(request=request, request_id=request_id)
