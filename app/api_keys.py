"""
api_keys.py
===========
API keys for the external API (/api/v1, D19).

A key belongs to one hospital: a file sent with it is registered under that
hospital, whatever the caller says. Only the SHA-256 of a key is stored; the key
itself is shown once, when it is created (scripts/manage_api_keys.py).
Callers send it in the X-API-Key header.
"""

import hashlib
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import ApiKey, Hospital
from app.pipeline.run import get_or_create_hospital

PREFIX = "hism_"


def new_key() -> str:
    return PREFIX + secrets.token_urlsafe(32)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def create_key(db: Session, hospital_code: str, name: str) -> tuple[ApiKey, str]:
    """Returns the stored row and the key. The key is not stored and cannot be shown again."""
    h = get_or_create_hospital(db, hospital_code)
    key = new_key()
    row = ApiKey(hospital_id=h.id, name=name, key_hash=hash_key(key), prefix=key[:12])
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, key


class RateLimiter:
    """At most `per_minute` requests per key in any 60 s window. In-process: the POC runs
    one app process per server (see docs/api.md)."""

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self._hits: dict[int, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key_id: int) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key_id]
            while hits and now - hits[0] > 60:
                hits.popleft()
            if len(hits) >= self.per_minute:
                return False
            hits.append(now)
            return True


_limiter = RateLimiter(int(os.environ.get("API_RATE_PER_MIN", "30")))


@dataclass(frozen=True)
class Caller:
    key_id: int
    hospital_id: int
    hospital_code: str


def error(status: int, code: str, message: str, **kw) -> HTTPException:
    """Every API error has the same shape: {"detail": {"code": ..., "message": ...}}."""
    return HTTPException(status, {"code": code, "message": message}, **kw)


_header = APIKeyHeader(name="X-API-Key", auto_error=False, description="API key ที่หน่วยงานกลางออกให้โรงพยาบาล")


def caller(key: str | None = Security(_header)) -> Caller:
    """FastAPI dependency: the hospital behind the request's key, or 401 / 429."""
    if not key:
        raise error(401, "missing_key", "ต้องส่ง API key ใน header X-API-Key")
    with SessionLocal() as db:
        row = db.query(ApiKey).filter(ApiKey.key_hash == hash_key(key),
                                      ApiKey.revoked_at.is_(None)).one_or_none()
        if row is None:
            raise error(401, "invalid_key", "API key ไม่ถูกต้อง หรือถูกยกเลิกแล้ว")
        row.last_used_at = func.now()
        db.commit()
        who = Caller(row.id, row.hospital_id, db.get(Hospital, row.hospital_id).code)
    if not _limiter.allow(who.key_id):
        raise error(429, "rate_limited", "เรียกถี่เกินกำหนด ลองใหม่ในอีก 1 นาที", headers={"Retry-After": "60"})
    return who
