import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.routes.search import router as search_router
from api.routes.booking import router as booking_router
from api.routes.admin import router as admin_router
from logging_config import setup_json_logging

# Configure structured JSON logging globally
setup_json_logging()

app = FastAPI(
    title="Travel Supplier Search & Booking API",
    description="Step 2 Search, Step 3 Temporal Booking Engine, Step 4 Observability & Step 5 Web Dashboard",
    version="0.1.0"
)

# Enable CORS for local development and web dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routers
app.include_router(search_router)
app.include_router(booking_router)
app.include_router(admin_router)

static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")

@app.get("/")
async def serve_spa():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"status": "Travel API is online. Dashboard static files not found."}

if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static_assets")
    app.mount("/css", StaticFiles(directory=os.path.join(static_dir, "css")), name="css_assets")
    app.mount("/js", StaticFiles(directory=os.path.join(static_dir, "js")), name="js_assets")
