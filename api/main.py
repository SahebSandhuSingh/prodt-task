import logging
from fastapi import FastAPI
from api.routes.search import router as search_router
from api.routes.booking import router as booking_router
from api.routes.admin import router as admin_router
from logging_config import setup_json_logging

# Configure structured JSON logging globally
setup_json_logging()

app = FastAPI(
    title="Travel Supplier Search & Booking API",
    description="Step 2 Search, Step 3 Temporal Booking Engine, and Step 4 Observability",
    version="0.1.0"
)

# Register routers
app.include_router(search_router)
app.include_router(booking_router)
app.include_router(admin_router)
