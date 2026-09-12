"""
FastAPI Application Entry Point
================================
HIS Mapping Web Application
"""

import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.graph import service
from app.routes import dashboard, mapping, reviews, upload, upload_legacy


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Checkpointer tables/indexes are created here, before any request can hold a
    # transaction open (setup() uses CREATE INDEX CONCURRENTLY, which waits for them).
    service.init()
    yield


# ---------------------------------------------------------------------------
# Create app
# ---------------------------------------------------------------------------

app = FastAPI(title="HIS Mapping", description="แปลงข้อมูล HIS → Template อาชีวอนามัย", lifespan=lifespan)

# Static files & templates
BASE_DIR = os.path.dirname(__file__)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# Routes
app.include_router(upload.router)
app.include_router(upload_legacy.router)
app.include_router(dashboard.router)
app.include_router(mapping.router)
app.include_router(reviews.router)


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")
