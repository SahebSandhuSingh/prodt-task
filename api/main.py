import logging
from fastapi import FastAPI
from api.routes.search import router as search_router

# Configure root logger format
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s"
)

app = FastAPI(
    title="Travel Supplier Search API",
    description="Step 2 Unified Hotel Search Service",
    version="0.1.0"
)

# Register search router
app.include_router(search_router)
