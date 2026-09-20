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

# The main menu is the manual's, and only the manual's: three cards plus the
# staff section (หน้าเมนูหลัก, p.4). Everything this project added lives inside
# "รายงานผลตรวจสุขภาพกลุ่มเสี่ยง", which is where the manual itself puts searching
# for a company, its checkup rounds, and uploading the employee and result files.
MENU = [
    {"key": "registration", "label": "ขึ้นทะเบียนหน่วยบริการ", "href": "/registration", "roles": ("superadmin", "admin", "staff", "doctor")},
    {"key": "walkthrough", "label": "รายงานผล Walk Through Survey", "href": "/walkthrough", "roles": ("superadmin", "admin", "staff", "doctor")},
    {"key": "health", "label": "รายงานผลตรวจสุขภาพกลุ่มเสี่ยง", "href": "/health-report", "roles": ("superadmin", "admin", "staff", "doctor")},
]

#: The steps inside "รายงานผลตรวจสุขภาพกลุ่มเสี่ยง", in the order they have to happen.
HEALTH_STEPS = [
    {"key": "workplaces", "label": "ทะเบียนสถานประกอบการ", "href": "/workplaces",
     "note": "สถานประกอบการและแผนกงาน ต้องมีก่อนทุกอย่าง",
     "roles": ("superadmin", "admin", "staff", "doctor")},
    {"key": "rounds", "label": "รอบตรวจสุขภาพ", "href": "/rounds",
     "note": "รอบและวันนัดตรวจ เป็นที่มาของวันที่ตรวจทุกคน",
     "roles": ("superadmin", "admin", "staff", "doctor")},
    {"key": "registry", "label": "นำเข้าทะเบียนพนักงาน", "href": "/import-registry",
     "note": "ไฟล์รายชื่อพนักงาน ต้องนำเข้าก่อนผลตรวจ",
     "roles": ("superadmin", "admin", "staff")},
    {"key": "import", "label": "นำเข้าผลตรวจ (AI)", "href": "/import",
     "note": "ไฟล์ผลตรวจจาก HIS หน้าตาแบบไหนก็ได้",
     "roles": ("superadmin", "admin", "staff")},
    {"key": "manual", "label": "กรอกผลตรวจทีละคน", "href": "/manual-entry",
     "note": "สำหรับคนเดียว หรือแก้ค่าที่พิมพ์ผิด",
     "roles": ("superadmin", "admin", "staff", "doctor")},
    {"key": "reviews", "label": "งานที่ต้องตรวจ", "href": "/reviews",
     "note": "สิ่งที่ระบบไม่ยอมเดา รอให้คนตัดสิน",
     "roles": ("superadmin", "admin", "staff")},
    {"key": "people", "label": "ข้อมูลพนักงาน", "href": "/people",
     "note": "ทะเบียนและผลตรวจรายคน", "roles": ("superadmin", "admin", "staff", "doctor")},
    {"key": "summary", "label": "ภาพรวมและส่งรายงาน", "href": "/summary",
     "note": "สรุปรายรอบ และสร้างไฟล์ส่งกรมฯ",
     "roles": ("superadmin", "admin", "staff", "doctor")},
]
STAFF_MENU = [
    {"key": "users", "label": "จัดการผู้ใช้งาน", "href": "/users", "roles": ("superadmin", "admin")},
]


def _ctx(request: Request, user: AppUser, db: Session, **extra) -> dict:
    hospital = db.get(Hospital, user.hospital_id) if user.hospital_id else None
    return {"request": request, "user": user, "role_th": auth.ROLE_TH.get(user.role, user.role),
            "hospital": hospital.name if hospital else "ส่วนกลาง",
            "menu": [m for m in MENU if user.role in m["roles"]],
            "health_steps": [m for m in HEALTH_STEPS if user.role in m["roles"]],
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


@router.get("/workplaces", response_class=HTMLResponse)
def workplaces_page(request: Request, response: Response, db: Session = Depends(get_db)):
    """ทะเบียนสถานประกอบการ: the workplaces and their departments (D23). Everything
    downstream — surveys, rounds, the register, results — hangs off a row here."""
    user, redirect = _guard(request, response)
    if redirect:
        return redirect
    page = templates.TemplateResponse(request, "workplaces.html",
                                      _ctx(request, user, db, active="workplaces"))
    page.headers.update(response.headers)
    return page


@router.get("/walkthrough", response_class=HTMLResponse)
def walkthrough_page(request: Request, response: Response, db: Session = Depends(get_db)):
    """Walk Through Survey — the header is real (D23): a checkup round points at a
    survey with a NOT NULL key, so results cannot exist without one. The risk
    questionnaire itself is still the mockup, at /walkthrough-mock."""
    user, redirect = _guard(request, response)
    if redirect:
        return redirect
    page = templates.TemplateResponse(request, "walkthrough.html", _ctx(request, user, db, active="walkthrough"))
    page.headers.update(response.headers)
    return page


@router.get("/walkthrough-mock", response_class=HTMLResponse)
def walkthrough_mock_page(request: Request, response: Response, db: Session = Depends(get_db)):
    """The risk questionnaire from the manual — mockup only, nothing is stored."""
    user, redirect = _guard(request, response)
    if redirect:
        return redirect
    page = templates.TemplateResponse(request, "mock_walkthrough.html", _ctx(request, user, db, active="walkthrough"))
    page.headers.update(response.headers)
    return page


@router.get("/rounds", response_class=HTMLResponse)
def rounds_page(request: Request, response: Response, db: Session = Depends(get_db)):
    """รอบตรวจสุขภาพ: where the visit date comes from (D23)."""
    user, redirect = _guard(request, response)
    if redirect:
        return redirect
    page = templates.TemplateResponse(request, "rounds.html", _ctx(request, user, db, active="rounds"))
    page.headers.update(response.headers)
    return page


@router.get("/health-report", response_class=HTMLResponse)
def health_report_page(request: Request, response: Response, db: Session = Depends(get_db)):
    """รายงานผลตรวจสุขภาพกลุ่มเสี่ยง — the hub the manual puts this flow under."""
    user, redirect = _guard(request, response)
    if redirect:
        return redirect
    page = templates.TemplateResponse(request, "health_report.html",
                                      _ctx(request, user, db, active="health"))
    page.headers.update(response.headers)
    return page


@router.get("/health-report-mock", response_class=HTMLResponse)
def health_report_mock_page(request: Request, response: Response, db: Session = Depends(get_db)):
    """The department's own risk-group report screen — mockup only."""
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


@router.get("/import-registry", response_class=HTMLResponse)
def import_registry_page(request: Request, response: Response, db: Session = Depends(get_db)):
    """นำเข้าทะเบียนพนักงาน: who the people are (D23). Must come before results —
    a person not in the register has their results held back."""
    user, redirect = _guard(request, response)
    if redirect:
        return redirect
    page = templates.TemplateResponse(request, "import_registry.html",
                                      _ctx(request, user, db, active="registry"))
    page.headers.update(response.headers)
    return page


@router.get("/reviews", response_class=HTMLResponse)
def reviews_page(request: Request, response: Response, db: Session = Depends(get_db)):
    """งานที่ต้องตรวจ: the mapping/identity/department/comment reviews and the conflicts."""
    user, redirect = _guard(request, response)
    if redirect:
        return redirect
    page = templates.TemplateResponse(request, "import_reviews.html",
                                      _ctx(request, user, db, active="reviews"))
    page.headers.update(response.headers)
    return page


@router.get("/manual-entry", response_class=HTMLResponse)
def manual_entry_page(request: Request, response: Response, db: Session = Depends(get_db)):
    """กรอกผลตรวจทีละคน — the path the manual keeps for one person at a time, and
    for correcting a typo (D23). Values are stored as typed; every change is logged."""
    user, redirect = _guard(request, response)
    if redirect:
        return redirect
    page = templates.TemplateResponse(request, "manual_entry.html",
                                      _ctx(request, user, db, active="manual"))
    page.headers.update(response.headers)
    return page


@router.get("/people", response_class=HTMLResponse)
def people_page(request: Request, response: Response, db: Session = Depends(get_db)):
    """ข้อมูลพนักงาน: the results that are in the system, one person at a time."""
    user, redirect = _guard(request, response)
    if redirect:
        return redirect
    page = templates.TemplateResponse(request, "import_people.html",
                                      _ctx(request, user, db, active="people"))
    page.headers.update(response.headers)
    return page


@router.get("/summary", response_class=HTMLResponse)
def summary_page(request: Request, response: Response, db: Session = Depends(get_db)):
    """ภาพรวมและส่งรายงาน: the reporting layer over the results already stored (D21)."""
    user, redirect = _guard(request, response)
    if redirect:
        return redirect
    page = templates.TemplateResponse(request, "import_summary.html",
                                      _ctx(request, user, db, active="summary"))
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
