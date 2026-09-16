"""
Upload route
============
POST /api/upload — keep the original file, then run the agent graph
(app/graph). The file may finish, or wait for a reviewer (status
"awaiting_review"; see app/routes/reviews.py).
"""

import hashlib
import os

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.auth import require_user
from app.database import SessionLocal
from app.graph import service
from app.models import AppUser, Hospital, SourceFile
from app.pipeline.run import get_or_create_hospital

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ALLOWED = ("csv", "xlsx", "xls")

router = APIRouter(prefix="/api", tags=["upload"])


def storage_dir() -> str:
    return os.environ.get("STORAGE_DIR", os.path.join(ROOT, "storage", "uploads"))


def register_file(db: Session, filename: str, content: bytes, hospital: str | None,
                  api_key_id: int | None = None) -> SourceFile:
    """Stores the original bytes and creates the SourceFile row (committed)."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    sha = hashlib.sha256(content).hexdigest()
    os.makedirs(storage_dir(), exist_ok=True)
    stored_path = os.path.join(storage_dir(), f"{sha}.{ext}")
    with open(stored_path, "wb") as fh:
        fh.write(content)
    h = get_or_create_hospital(db, hospital)
    sf = SourceFile(hospital_id=h.id, filename=filename, file_type=ext, sha256=sha,
                    stored_path=stored_path, status="processing", stats={}, errors=[], api_key_id=api_key_id)
    db.add(sf)
    db.commit()
    db.refresh(sf)
    return sf


def hospital_code_for(db: Session, user: AppUser, requested: str) -> str:
    """
    The hospital a file is filed under comes from the signed-in account, never from
    what the browser sends (D20). Only a superadmin may name one, and only one that
    already exists: a typo must not quietly create a hospital and scatter the learned
    mappings across it.
    """
    if user.role == "superadmin":
        code = (requested or "").strip()
        if not code:
            raise ValueError("กรุณาเลือกหน่วยบริการก่อนส่งไฟล์")
        h = db.query(Hospital).filter(Hospital.code == code).one_or_none()
        if h is None:
            raise ValueError(f"ไม่พบหน่วยบริการรหัส {code} ในระบบ")
        return h.code
    if user.hospital_id is None:
        raise ValueError("บัญชีนี้ยังไม่ได้ผูกกับหน่วยบริการ กรุณาติดต่อผู้ดูแลระบบ")
    h = db.get(Hospital, user.hospital_id)
    if h is None:
        raise ValueError("ไม่พบหน่วยบริการของบัญชีนี้ กรุณาติดต่อผู้ดูแลระบบ")
    return h.code


@router.get("/hospitals")
def list_hospitals(user: AppUser = Depends(require_user)):
    """The picker a superadmin uses on the import page. Everyone else uses their own."""
    with SessionLocal() as db:
        rows = db.query(Hospital).order_by(Hospital.code).all()
        return {"hospitals": [{"code": h.code, "name": h.name} for h in rows]}


@router.post("/upload")
async def upload_file(file: UploadFile = File(...), hospital: str = Form(""),
                      user: AppUser = Depends(require_user)):
    filename = file.filename or "unknown"
    if filename.rsplit(".", 1)[-1].lower() not in ALLOWED:
        return {"success": False, "error": "รองรับเฉพาะไฟล์ .csv .xlsx และ .xls"}
    content = await file.read()
    # Short-lived session, closed BEFORE the graph runs: no transaction may stay open while it
    # works (LLM calls take tens of seconds, and Postgres DDL such as the checkpointer's
    # CREATE INDEX CONCURRENTLY waits for every open transaction — that deadlocked once).
    with SessionLocal() as db:
        try:
            code = hospital_code_for(db, user, hospital)
        except ValueError as e:
            return {"success": False, "error": str(e)}
        file_id = register_file(db, filename, content, code).id
    try:
        st = service.run_upload(file_id)
    except Exception as e:  # process_file already rolled back and marked the file failed
        return {"success": False, "upload_id": file_id, "error": f"{type(e).__name__}: {e}"}
    stats = st["stats"] or {}
    return {
        "success": True,
        "upload_id": file_id,
        "status": st["status"],
        "waiting_for_human": st["waiting_for_human"],
        "format_detected": ", ".join(f"{s['name']}({s['layout']})" for s in stats.get("sheets", [])),
        "total_rows": stats.get("total_rows", 0),
        "success_rows": stats.get("success_rows", 0),
        "error_rows": stats.get("error_rows", 0),
        "stats": stats,
        "errors": [f"รอตรวจ {k}: {n} รายการ" for k, n in stats.get("reviews_by_kind", {}).items()],
    }
