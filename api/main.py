import logging
from fastapi import FastAPI
from api.routes.search import router as search_router
from api.routes.booking import router as booking_router

# Configure root logger format
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s"
)

app = FastAPI(
    title="Travel Supplier Search & Booking API",
    description="Step 2 Search & Step 3 Temporal Booking Engine",
    version="0.1.0"
)

# Register routers
app.include_router(search_router)
app.include_router(booking_router)
