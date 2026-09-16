"""
FastAPI Application Entry Point
================================
HIS Mapping Web Application
"""

import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.graph import service
from app.routes import (
    accounts, api_v1, conflicts, dashboard, mapping, pages, reviews, upload, upload_legacy,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Checkpointer tables/indexes are created here, before any request can hold a
    # transaction open (setup() uses CREATE INDEX CONCURRENTLY, which waits for them).
    service.init()
    api_v1.resume_unfinished()   # files whose background run died with the last process
    yield


# ---------------------------------------------------------------------------
# Create app
# ---------------------------------------------------------------------------

app = FastAPI(title="HIS Mapping", description="แปลงข้อมูล HIS → Template อาชีวอนามัย", lifespan=lifespan)

# Static files & templates
BASE_DIR = os.path.dirname(__file__)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
# the HTML pages themselves live in app/routes/pages.py

# External API for hospital HIS systems (D19), with its own docs at /api/v1/docs. Mounted
# before the internal routes so none of them can shadow it. Only /api/v1 may be exposed
# to the internet (deploy/Caddyfile); everything else is the staff web page's API.
app.mount("/api/v1", api_v1.api)

# Routes (internal)
app.include_router(accounts.router)
app.include_router(upload.router)
app.include_router(upload_legacy.router)
app.include_router(dashboard.router)
app.include_router(mapping.router)
app.include_router(reviews.router)
app.include_router(conflicts.router)


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

app.include_router(pages.router)     # /login, /, /profile, /users, /import (Env-Occ style)
