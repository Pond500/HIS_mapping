"""
auth.py
=======
Sign-in for the staff web pages (the Env-Occ manual in docs/: เข้าสู่ระบบ, โปรไฟล์,
จัดการผู้ใช้งาน). Separate from the hospital API, which uses API keys (app/api_keys.py).

- Passwords: PBKDF2-SHA256 from the standard library, so no new dependency.
- Sessions: a signed cookie (no session table). It is re-issued on every request, so a
  session dies after SESSION_MINUTES without activity, as the manual describes.
- The signing key comes from APP_SECRET, or a key file created under STORAGE_DIR the
  first time the app runs (so sessions survive a restart).
"""

import base64
import hashlib
import hmac
import os
import secrets
import time

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import AppUser
from app.paths import ROOT_PATH

COOKIE = "envocc_session"
SESSION_MINUTES = int(os.environ.get("SESSION_MINUTES", "60"))
ITERATIONS = 200_000

ROLE_TH = {
    "superadmin": "ผู้ดูแลระบบส่วนกลาง",
    "admin": "ผู้ดูแลหน่วยบริการ",
    "doctor": "แพทย์",
    "staff": "เจ้าหน้าที่",
}
# who may create/edit whom: never above your own rank
RANK = {"staff": 1, "doctor": 2, "admin": 3, "superadmin": 4}

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _secret() -> bytes:
    key = os.environ.get("APP_SECRET")
    if key:
        return key.encode()
    path = os.path.join(os.environ.get("STORAGE_DIR", os.path.join(ROOT, "storage")), "session_key")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        with open(os.open(path, os.O_CREAT | os.O_WRONLY, 0o600), "w") as fh:
            fh.write(secrets.token_urlsafe(48))
    with open(path) as fh:
        return fh.read().strip().encode()


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${_b64(salt)}${_b64(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds, salt, want = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), _unb64(salt), int(rounds))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(_b64(dk), want)


def new_password(n: int = 10) -> str:
    """A readable one-off password; the admin passes it on to the user."""
    alphabet = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(n))


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


# ---------------------------------------------------------------------------
# Session cookie
# ---------------------------------------------------------------------------

def make_token(user_id: int) -> str:
    body = f"{user_id}.{int(time.time())}"
    sig = hmac.new(_secret(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64(sig)}"


def read_token(token: str) -> int | None:
    """The user id in a valid, unexpired token, else None."""
    try:
        user_id, issued, sig = token.split(".")
        body = f"{user_id}.{issued}"
    except ValueError:
        return None
    want = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, want):
        return None
    if time.time() - int(issued) > SESSION_MINUTES * 60:
        return None
    return int(user_id)


def set_session(response: Response, user_id: int) -> None:
    response.set_cookie(COOKIE, make_token(user_id), max_age=SESSION_MINUTES * 60,
                        httponly=True, samesite="lax", path=ROOT_PATH or "/")


def clear_session(response: Response) -> None:
    response.delete_cookie(COOKIE, path=ROOT_PATH or "/")


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------

def current_user(request: Request, response: Response) -> AppUser | None:
    """The signed-in user, or None. Refreshes the cookie so the hour counts from
    the last request, not from the sign-in."""
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    user_id = read_token(token)
    if user_id is None:
        return None
    with SessionLocal() as db:
        user = db.get(AppUser, user_id)
        if user is None or not user.is_active:
            return None
        db.expunge(user)
    set_session(response, user_id)
    return user


def require_user(user: AppUser | None = Depends(current_user)) -> AppUser:
    if user is None:
        raise HTTPException(401, {"code": "not_signed_in", "message": "กรุณาเข้าสู่ระบบอีกครั้ง"})
    return user


def require_roles(*roles: str):
    def check(user: AppUser = Depends(require_user)) -> AppUser:
        if user.role not in roles:
            raise HTTPException(403, {"code": "forbidden", "message": "สิทธิ์ของคุณไม่สามารถใช้ส่วนนี้ได้"})
        return user
    return check


def may_manage(actor: AppUser, role: str) -> bool:
    """An admin may only create or edit users of their own rank or lower (manual: จัดการผู้ใช้งาน).
    Doctors are created through the doctor sign-up flow, never here."""
    if role == "doctor":
        return False
    return RANK.get(actor.role, 0) >= RANK.get(role, 99) and actor.role in ("superadmin", "admin")


def same_scope(actor: AppUser, hospital_id: int | None) -> bool:
    """Superadmin works across hospitals; everyone else only inside their own."""
    return actor.role == "superadmin" or (hospital_id is not None and hospital_id == actor.hospital_id)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
