"""
accounts.py
===========
Sign-in and user management for the staff web pages (Env-Occ manual: เข้าสู่ระบบ,
หน้าโปรไฟล์, จัดการผู้ใช้งาน).

    POST   /api/auth/login      {username, password}
    POST   /api/auth/logout
    GET    /api/auth/me
    PATCH  /api/auth/profile    {name, surname, email, password}
    GET    /api/users           list (own hospital; superadmin sees all)
    POST   /api/users           create -> returns the one-off password to pass on
    PATCH  /api/users/{id}      edit name/surname/role/password
    DELETE /api/users/{id}      deactivate (history is kept)

There is no mail server yet, so a new user's password is shown once to the admin who
created it. The manual has it emailed; that is a phase-2 change.
"""

import re

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app import auth
from app.auth import get_db, require_user
from app.models import AppUser, Hospital
from app.pipeline.run import get_or_create_hospital

router = APIRouter(prefix="/api", tags=["accounts"])


def error(status: int, code: str, message: str):
    from fastapi import HTTPException
    return HTTPException(status, {"code": code, "message": message})


class LoginIn(BaseModel):
    username: str
    password: str


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")   # good enough; no new dependency


def _check_email(v: str | None) -> str | None:
    if v is not None and not EMAIL_RE.match(v.strip()):
        raise ValueError("รูปแบบอีเมลไม่ถูกต้อง")
    return v.strip() if v else v


class ProfileIn(BaseModel):
    name: str | None = None
    surname: str | None = None
    email: str | None = None
    password: str | None = Field(default=None, min_length=8)

    _email = field_validator("email")(_check_email)


class UserIn(BaseModel):
    email: str
    name: str = ""
    surname: str = ""
    role: str = "staff"
    hospital: str | None = None      # hospital code; None = the actor's own hospital

    _email = field_validator("email")(_check_email)


class UserPatch(BaseModel):
    name: str | None = None
    surname: str | None = None
    role: str | None = None
    password: str | None = Field(default=None, min_length=8)
    license_no: str | None = None


def _out(db: Session, u: AppUser) -> dict:
    d = u.to_dict()
    h = db.get(Hospital, u.hospital_id) if u.hospital_id else None
    d["hospital"] = h.code if h else None
    d["role_th"] = auth.ROLE_TH.get(u.role, u.role)
    return d


# ---------------------------------------------------------------------------
# Sign in / out
# ---------------------------------------------------------------------------

@router.post("/auth/login")
def login(body: LoginIn, response: Response, db: Session = Depends(get_db)):
    user = db.query(AppUser).filter(func.lower(AppUser.username) == body.username.strip().lower()).one_or_none()
    if user is None:
        raise error(401, "no_user", "ไม่พบชื่อผู้ใช้นี้ในระบบ")
    if not user.is_active:
        raise error(403, "inactive", "บัญชีนี้ถูกปิดการใช้งาน")
    if not auth.verify_password(body.password, user.password_hash):
        raise error(401, "bad_password", "รหัสผ่านไม่ถูกต้อง")
    user.last_login_at = func.now()
    db.commit()
    auth.set_session(response, user.id)
    return {"ok": True, "user": _out(db, user)}


@router.post("/auth/logout")
def logout(response: Response):
    auth.clear_session(response)
    return {"ok": True}


@router.get("/auth/me")
def me(request: Request, response: Response, db: Session = Depends(get_db)):
    user = auth.current_user(request, response)
    if user is None:
        return {"signed_in": False}
    return {"signed_in": True, "user": _out(db, db.get(AppUser, user.id))}


@router.patch("/auth/profile")
def edit_profile(body: ProfileIn, user: AppUser = Depends(require_user), db: Session = Depends(get_db)):
    me = db.get(AppUser, user.id)
    if body.name is not None:
        me.name = body.name.strip()
    if body.surname is not None:
        me.surname = body.surname.strip()
    if body.email is not None:
        me.email = str(body.email)
    if body.password:
        me.password_hash = auth.hash_password(body.password)
    db.commit()
    return {"ok": True, "user": _out(db, me)}


# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------

@router.get("/users")
def list_users(q: str = "", user: AppUser = Depends(require_user), db: Session = Depends(get_db)):
    if user.role not in ("superadmin", "admin"):
        raise error(403, "forbidden", "สิทธิ์ของคุณไม่สามารถใช้ส่วนนี้ได้")
    rows = db.query(AppUser)
    if user.role != "superadmin":
        rows = rows.filter(AppUser.hospital_id == user.hospital_id)
    if q:
        like = f"%{q.strip()}%"
        rows = rows.filter(or_(AppUser.name.ilike(like), AppUser.surname.ilike(like),
                               AppUser.username.ilike(like), AppUser.email.ilike(like)))
    return [_out(db, u) for u in rows.order_by(AppUser.id).all()]


@router.post("/users", status_code=201)
def create_user(body: UserIn, user: AppUser = Depends(require_user), db: Session = Depends(get_db)):
    if not auth.may_manage(user, body.role):
        raise error(403, "forbidden",
                    "สร้างได้เฉพาะสิทธิ์ที่ไม่สูงกว่าตัวเอง และสิทธิ์แพทย์ต้องผ่านการลงทะเบียนแพทย์เท่านั้น")
    hospital_id = user.hospital_id
    if body.hospital and user.role == "superadmin":
        hospital_id = get_or_create_hospital(db, body.hospital).id
    if hospital_id is None:
        raise error(400, "no_hospital", "ต้องระบุสังกัดหน่วยบริการ")
    if db.query(AppUser).filter(func.lower(AppUser.email) == str(body.email).lower()).count():
        raise error(409, "email_taken", "อีเมลนี้มีผู้ใช้งานแล้ว")
    username = _free_username(db, body.role)
    password = auth.new_password()
    row = AppUser(username=username, name=body.name or username, surname=body.surname,
                  email=str(body.email), password_hash=auth.hash_password(password), role=body.role,
                  hospital_id=hospital_id, created_by=f"{user.name} {user.surname}".strip() or user.username)
    db.add(row)
    db.commit()
    db.refresh(row)
    # no mail server yet: the password is shown once to the admin who created the user
    return {"ok": True, "user": _out(db, row), "password": password}


@router.patch("/users/{user_id}")
def edit_user(user_id: int, body: UserPatch, user: AppUser = Depends(require_user),
              db: Session = Depends(get_db)):
    row = db.get(AppUser, user_id)
    if row is None or not auth.same_scope(user, row.hospital_id):
        raise error(404, "not_found", "ไม่พบผู้ใช้งานนี้")
    if not auth.may_manage(user, row.role) and row.id != user.id:
        raise error(403, "forbidden", "สิทธิ์ของคุณแก้ไขผู้ใช้รายนี้ไม่ได้")
    if body.role and body.role != row.role:
        if not auth.may_manage(user, body.role):
            raise error(403, "forbidden", "ให้สิทธิ์ได้ไม่เกินสิทธิ์ของตัวเอง")
        row.role = body.role
    if body.name is not None:
        row.name = body.name.strip()
    if body.surname is not None:
        row.surname = body.surname.strip()
    if body.license_no is not None:
        row.license_no = body.license_no.strip()
    if body.password:
        row.password_hash = auth.hash_password(body.password)
    db.commit()
    return {"ok": True, "user": _out(db, row)}


@router.delete("/users/{user_id}")
def deactivate_user(user_id: int, user: AppUser = Depends(require_user), db: Session = Depends(get_db)):
    row = db.get(AppUser, user_id)
    if row is None or not auth.same_scope(user, row.hospital_id):
        raise error(404, "not_found", "ไม่พบผู้ใช้งานนี้")
    if row.id == user.id:
        raise error(400, "self", "ปิดการใช้งานบัญชีตัวเองไม่ได้")
    if not auth.may_manage(user, row.role):
        raise error(403, "forbidden", "สิทธิ์ของคุณปิดการใช้งานผู้ใช้รายนี้ไม่ได้")
    row.is_active = False
    db.commit()
    return {"ok": True}


def _free_username(db: Session, role: str) -> str:
    """Usernames follow the manual's style: doctor-275, admin-272, staff-14."""
    prefix = {"superadmin": "admin", "admin": "admin", "doctor": "doctor", "staff": "staff"}[role]
    n = db.query(func.count(AppUser.id)).scalar() + 1
    while db.query(AppUser).filter(AppUser.username == f"{prefix}-{n}").count():
        n += 1
    return f"{prefix}-{n}"
