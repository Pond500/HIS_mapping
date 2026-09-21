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
    accounts, api_v1, conflicts, dashboard, mapping, pages, registration, reviews, summary,
    manual, rounds, workplaces,
    upload, upload_legacy,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Checkpointer tables/indexes are created here, before any request can hold a
    # transaction open (setup() uses CREATE INDEX CONCURRENTLY, which waits for them).
    service.init()
    # api_v1.resume_unfinished() — see the note on the mount below (D19-หนี้)
    yield


# ---------------------------------------------------------------------------
# Create app
# ---------------------------------------------------------------------------

app = FastAPI(title="HIS Mapping", description="แปลงข้อมูล HIS → Template อาชีวอนามัย", lifespan=lifespan)

# Static files & templates
BASE_DIR = os.path.dirname(__file__)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
# the HTML pages themselves live in app/routes/pages.py

# External API for hospital HIS systems (D19), with its own docs at /api/v1/docs.
#
# CLOSED while the schema moves to the department's shape (D19-หนี้). A results
# file now only means something inside a checkup round, and the round — company,
# survey, appointment date — is chosen by a person in the upload dialog. A HIS
# posting bytes and a key cannot supply any of that, and D23 ruled out asking the
# hospitals to change their side.
#
# The code stays. The agreed direction is to accept the file into a waiting state
# and let a member of staff attach it to a round in the web page, which keeps the
# promise made to the department without a change at the hospital end.
#
# app.mount("/api/v1", api_v1.api)

# Routes (internal)
app.include_router(accounts.router)
app.include_router(registration.router)
app.include_router(upload.router)
# /api/legacy/upload needs no sign-in and writes with the pre-D23 code, which no longer
# matches the schema. Only the paused `baseline` evaluation uses it, so it is off unless
# ENABLE_LEGACY_UPLOAD is set. A server must never set it (D22).
if os.environ.get("ENABLE_LEGACY_UPLOAD", "").lower() in ("on", "1", "true", "yes"):
    app.include_router(upload_legacy.router)
app.include_router(dashboard.router)
app.include_router(mapping.router)
app.include_router(reviews.router)
app.include_router(conflicts.router)
app.include_router(summary.router)
app.include_router(workplaces.router)
app.include_router(rounds.router)
app.include_router(manual.router)


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

app.include_router(pages.router)     # /login, /, /profile, /users, /import (Env-Occ style)
