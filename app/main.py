"""
FastAPI Application Entry Point
================================
HIS Mapping Web Application
"""

import os
import sys

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.database import init_db
from app.routes import dashboard, upload, mapping

# ---------------------------------------------------------------------------
# Create app
# ---------------------------------------------------------------------------

app = FastAPI(title="HIS Mapping", description="แปลงข้อมูล HIS → Template อาชีวอนามัย")

# Static files & templates
BASE_DIR = os.path.dirname(__file__)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# Routes
app.include_router(upload.router)
app.include_router(dashboard.router)
app.include_router(mapping.router)


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

@app.on_event("startup")
def startup():
    init_db()
    print("🏥 HIS Mapping Web App started!")
    print("   Open http://localhost:8000 in your browser")
