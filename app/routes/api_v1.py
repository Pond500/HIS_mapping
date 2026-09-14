"""
api_v1.py
=========
External API for hospital HIS systems (D19): send a file, then poll its status.

Its own FastAPI app, mounted at /api/v1 with docs at /api/v1/docs, so the internal
staff API (/api/...) is not part of it and a reverse proxy can expose /api/v1 alone.
Callers only ever see the status of their own hospital's files: there is no way to
read people's results through this API.

A file is registered and answered right away (202); the agent graph runs in the
background, at most API_MAX_PARALLEL files at a time.
"""

import hashlib
import logging
import os
import threading
from typing import Literal

from fastapi import BackgroundTasks, Depends, FastAPI, File, Query, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy import func

from app.api_keys import Caller, caller, error
from app.database import SessionLocal
from app.graph import service
from app.models import PendingReview, SourceFile
from app.routes.upload import ALLOWED, register_file

log = logging.getLogger(__name__)

MAX_BYTES = int(float(os.environ.get("API_MAX_UPLOAD_MB", "20")) * 1024 * 1024)
_slots = threading.BoundedSemaphore(int(os.environ.get("API_MAX_PARALLEL", "2")))

MESSAGES = {
    "processing": "ได้รับไฟล์แล้ว กำลังประมวลผล",
    "awaiting_review": "บันทึกส่วนที่แน่ใจแล้ว ส่วนที่เหลือรอเจ้าหน้าที่หน่วยงานกลางตรวจ",
    "completed": "นำเข้าเสร็จแล้ว",
    "failed": "ประมวลผลไม่สำเร็จ เจ้าหน้าที่หน่วยงานกลางจะตรวจสอบ",
}

api = FastAPI(
    title="HIS Mapping — API สำหรับโรงพยาบาล",
    version="1.0",
    description=(
        "ระบบ HIS ของโรงพยาบาลส่งไฟล์ผลตรวจสุขภาพ (CSV / XLSX / XLS หน้าตาแบบไหนก็ได้) "
        "เข้าหน่วยงานกลาง แล้วดูสถานะของไฟล์ได้\n\n"
        "ทุก request ต้องส่ง API key ใน header `X-API-Key` · ข้อผิดพลาดทุกแบบมีรูปแบบ "
        "`{\"detail\": {\"code\": ..., \"message\": ...}}`"
    ),
    docs_url="/docs",
    redoc_url=None,
)


class FileStatus(BaseModel):
    file_id: int
    filename: str
    status: Literal["processing", "awaiting_review", "completed", "failed"]
    message: str
    items_waiting_for_staff: int = 0
    received_at: str | None = None
    duplicate: bool = False     # the same file was already received; this is the earlier one
    status_url: str


def _out(db, sf: SourceFile, duplicate: bool = False) -> FileStatus:
    waiting = 0
    if sf.status == "awaiting_review":
        waiting = db.query(func.count(PendingReview.id)).filter(
            PendingReview.source_file_id == sf.id, PendingReview.status == "open").scalar()
    return FileStatus(file_id=sf.id, filename=sf.filename, status=sf.status,
                      message=MESSAGES.get(sf.status, sf.status), items_waiting_for_staff=waiting,
                      received_at=sf.uploaded_at.isoformat() if sf.uploaded_at else None,
                      duplicate=duplicate, status_url=f"/api/v1/files/{sf.id}")


def _process(file_id: int) -> None:
    with _slots:
        try:
            service.run_upload(file_id)
        except Exception:
            log.exception("API file %s failed", file_id)
            with SessionLocal() as db:   # process_file marks its own failures; this catches the rest
                sf = db.get(SourceFile, file_id)
                if sf is not None and sf.status == "processing":
                    sf.status = "failed"
                    db.commit()


def resume_unfinished() -> None:
    """Files still 'processing' at startup lost their background run with the last process
    (a restart or deploy). Run them again; re-processing a file is idempotent."""
    with SessionLocal() as db:
        ids = [i for (i,) in db.query(SourceFile.id).filter(SourceFile.status == "processing")]
    for i in ids:
        threading.Thread(target=_process, args=(i,), daemon=True).start()
    if ids:
        log.warning("resuming %d unfinished file(s): %s", len(ids), ids)


ERRORS = {
    400: {"description": "ไฟล์ว่าง"},
    401: {"description": "ไม่มี API key หรือ key ไม่ถูกต้อง / ถูกยกเลิก"},
    413: {"description": "ไฟล์ใหญ่เกินกำหนด"},
    415: {"description": "ชนิดไฟล์ไม่รองรับ"},
    429: {"description": "เรียกถี่เกินกำหนด"},
}


@api.post("/files", status_code=202, response_model=FileStatus, summary="ส่งไฟล์ผลตรวจ",
          responses={200: {"description": "ไฟล์เดียวกันเคยส่งแล้ว ตอบข้อมูลของครั้งก่อน", "model": FileStatus},
                     **ERRORS})
async def send_file(background: BackgroundTasks, response: Response,
                    file: UploadFile = File(..., description="CSV / XLSX / XLS"),
                    who: Caller = Depends(caller)):
    """รับไฟล์แล้วตอบเลขงาน (`file_id`) ทันที ระบบประมวลผลต่อเบื้องหลัง
    ดูผลได้ที่ `status_url` · ส่งไฟล์เดิมซ้ำจะได้เลขงานเดิม ไม่ประมวลผลซ้ำ"""
    filename = (file.filename or "unknown")[:500]
    if filename.rsplit(".", 1)[-1].lower() not in ALLOWED:
        raise error(415, "unsupported_type", "รองรับเฉพาะไฟล์ .csv .xlsx และ .xls")
    content = await file.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise error(413, "too_large", f"ไฟล์ใหญ่เกิน {MAX_BYTES // (1024 * 1024)} MB")
    if not content:
        raise error(400, "empty_file", "ไฟล์ว่าง")
    sha = hashlib.sha256(content).hexdigest()
    with SessionLocal() as db:
        earlier = db.query(SourceFile).filter(SourceFile.hospital_id == who.hospital_id,
                                              SourceFile.sha256 == sha,
                                              SourceFile.status != "failed").order_by(SourceFile.id.desc()).first()
        if earlier is not None:
            response.status_code = 200
            return _out(db, earlier, duplicate=True)
        sf = register_file(db, filename, content, who.hospital_code, api_key_id=who.key_id)
        out = _out(db, sf)
    background.add_task(_process, sf.id)
    return out


@api.get("/files/{file_id}", response_model=FileStatus, summary="ดูสถานะไฟล์",
         responses={401: ERRORS[401], 404: {"description": "ไม่พบไฟล์นี้ในโรงพยาบาลของ key นี้"}, 429: ERRORS[429]})
def file_status(file_id: int, who: Caller = Depends(caller)):
    with SessionLocal() as db:
        sf = db.get(SourceFile, file_id)
        if sf is None or sf.hospital_id != who.hospital_id:
            raise error(404, "not_found", "ไม่พบไฟล์นี้")
        return _out(db, sf)


@api.get("/files", response_model=list[FileStatus], summary="ไฟล์ที่ส่งล่าสุด",
         responses={401: ERRORS[401], 429: ERRORS[429]})
def list_files(limit: int = Query(20, ge=1, le=100), who: Caller = Depends(caller)):
    """ไฟล์ของโรงพยาบาลนี้ เรียงจากล่าสุด"""
    with SessionLocal() as db:
        rows = (db.query(SourceFile).filter(SourceFile.hospital_id == who.hospital_id)
                .order_by(SourceFile.id.desc()).limit(limit).all())
        return [_out(db, sf) for sf in rows]


@api.get("/health", include_in_schema=False)
def health():
    return {"ok": True}
