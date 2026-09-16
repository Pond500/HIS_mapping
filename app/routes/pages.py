"""
pages.py
========
The staff web pages, styled after the Env-Occ manual in docs/:

    /login      เข้าสู่ระบบ
    /           เมนูหลัก (cards)
    /profile    หน้าโปรไฟล์
    /users      จัดการผู้ใช้งาน (superadmin / admin)
    /import     the HIS Mapping import screen (this project's own converter)

Every page except /login needs a session; without one the browser is sent to /login.
"""

import os

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app import auth
from app.auth import get_db
from app.models import AppUser, Hospital

router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates"))

MENU = [
    {"key": "registration", "label": "ขึ้นทะเบียนหน่วยบริการ", "href": "/registration", "roles": ("superadmin", "admin", "staff", "doctor")},
    {"key": "walkthrough", "label": "รายงานผล WalkThroughSurvey", "href": "/walkthrough", "roles": ("superadmin", "admin", "staff", "doctor")},
    {"key": "health", "label": "รายงานผลตรวจสุขภาพกลุ่มเสี่ยง", "href": "/health-report", "roles": ("superadmin", "admin", "staff", "doctor")},
    {"key": "import", "label": "นำเข้าผลตรวจจากไฟล์ (HIS Mapping)", "href": "/import", "roles": ("superadmin", "admin", "staff")},
]
STAFF_MENU = [
    {"key": "users", "label": "จัดการผู้ใช้งาน", "href": "/users", "roles": ("superadmin", "admin")},
]


def _ctx(request: Request, user: AppUser, db: Session, **extra) -> dict:
    hospital = db.get(Hospital, user.hospital_id) if user.hospital_id else None
    return {"request": request, "user": user, "role_th": auth.ROLE_TH.get(user.role, user.role),
            "hospital": hospital.name if hospital else "ส่วนกลาง",
            "menu": [m for m in MENU if user.role in m["roles"]],
            "staff_menu": [m for m in STAFF_MENU if user.role in m["roles"]], **extra}


def _guard(request: Request, response: Response):
    """Returns (user, None) or (None, redirect to the sign-in page)."""
    user = auth.current_user(request, response)
    if user is None:
        nxt = request.url.path
        return None, RedirectResponse(f"/login?next={nxt}", status_code=303)
    return user, None


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, response: Response, next: str = "/"):
    if auth.current_user(request, response) is not None:
        return RedirectResponse(next or "/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"next": next})


@router.get("/", response_class=HTMLResponse)
def menu_page(request: Request, response: Response, db: Session = Depends(get_db)):
    user, redirect = _guard(request, response)
    if redirect:
        return redirect
    page = templates.TemplateResponse(request, "menu.html", _ctx(request, user, db, active="menu"))
    page.headers.update(response.headers)      # keep the refreshed session cookie
    return page


@router.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request, response: Response, db: Session = Depends(get_db)):
    user, redirect = _guard(request, response)
    if redirect:
        return redirect
    page = templates.TemplateResponse(request, "profile.html", _ctx(request, user, db, active="profile"))
    page.headers.update(response.headers)
    return page


@router.get("/users", response_class=HTMLResponse)
def users_page(request: Request, response: Response, db: Session = Depends(get_db)):
    user, redirect = _guard(request, response)
    if redirect:
        return redirect
    if user.role not in ("superadmin", "admin"):
        return RedirectResponse("/", status_code=303)
    page = templates.TemplateResponse(request, "users.html", _ctx(request, user, db, active="users"))
    page.headers.update(response.headers)
    return page


@router.get("/registration", response_class=HTMLResponse)
def registration_page(request: Request, response: Response, db: Session = Depends(get_db)):
    """ขึ้นทะเบียนหน่วยบริการ: the six-step form, its status timeline and the history."""
    user, redirect = _guard(request, response)
    if redirect:
        return redirect
    page = templates.TemplateResponse(request, "registration.html", _ctx(request, user, db, active="registration"))
    page.headers.update(response.headers)
    return page


@router.get("/walkthrough", response_class=HTMLResponse)
def walkthrough_page(request: Request, response: Response, db: Session = Depends(get_db)):
    """รายงานผล Walk Through Survey — mockup only, nothing is stored yet."""
    user, redirect = _guard(request, response)
    if redirect:
        return redirect
    page = templates.TemplateResponse(request, "mock_walkthrough.html", _ctx(request, user, db, active="walkthrough"))
    page.headers.update(response.headers)
    return page


@router.get("/health-report", response_class=HTMLResponse)
def health_report_page(request: Request, response: Response, db: Session = Depends(get_db)):
    """รายงานผลตรวจสุขภาพกลุ่มเสี่ยง — mockup only, nothing is stored yet."""
    user, redirect = _guard(request, response)
    if redirect:
        return redirect
    page = templates.TemplateResponse(request, "mock_health.html", _ctx(request, user, db, active="health"))
    page.headers.update(response.headers)
    return page


@router.get("/import", response_class=HTMLResponse)
def import_page(request: Request, response: Response, db: Session = Depends(get_db)):
    """นำเข้าผลตรวจ (AI): send a file, the graph converts it, unsure items go to a human."""
    user, redirect = _guard(request, response)
    if redirect:
        return redirect
    page = templates.TemplateResponse(request, "import_upload.html",
                                      _ctx(request, user, db, active="import"))
    page.headers.update(response.headers)
    return page


@router.get("/import-legacy", response_class=HTMLResponse)
def import_legacy_page(request: Request, response: Response, db: Session = Depends(get_db)):
    """
    The old single-page converter screen, kept reachable while its tabs are moved into
    the Env-Occ pages one by one (D20). Delete it once the new cards cover everything.
    """
    user, redirect = _guard(request, response)
    if redirect:
        return redirect
    page = templates.TemplateResponse(request, "index.html", {"request": request})
    page.headers.update(response.headers)
    return page
