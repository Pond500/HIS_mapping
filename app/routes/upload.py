"""
Upload route
============
POST /api/upload — keep the original file, then run the agent graph
(app/graph). The file may finish, or wait for a reviewer (status
"awaiting_review"; see app/routes/reviews.py).
"""

import hashlib
import logging
import os
import threading

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.auth import require_user
from app.database import SessionLocal
from app.graph import progress, service
from app.models import AppUser, CheckupBatch, Company, Hospital, SourceFile
from app.models import PendingReview
from app.pipeline import registry
from app.pipeline.reader import read_file
from app.pipeline.run import get_or_create_hospital

log = logging.getLogger(__name__)
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ALLOWED = ("csv", "xlsx", "xls")

router = APIRouter(prefix="/api", tags=["upload"])


def storage_dir() -> str:
    return os.environ.get("STORAGE_DIR", os.path.join(ROOT, "storage", "uploads"))


def register_file(db: Session, filename: str, content: bytes, hospital: str | None,
                  api_key_id: int | None = None, field_set: str = "result",
                  checkup_batch_id: int | None = None, company_id: int | None = None) -> SourceFile:
    """Stores the original bytes and creates the SourceFile row (committed)."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    sha = hashlib.sha256(content).hexdigest()
    os.makedirs(storage_dir(), exist_ok=True)
    stored_path = os.path.join(storage_dir(), f"{sha}.{ext}")
    with open(stored_path, "wb") as fh:
        fh.write(content)
    h = get_or_create_hospital(db, hospital)
    sf = SourceFile(hospital_id=h.id, filename=filename, file_type=ext, sha256=sha,
                    stored_path=stored_path, status="processing", stats={}, errors=[],
                    api_key_id=api_key_id, field_set=field_set,
                    checkup_batch_id=checkup_batch_id, company_id=company_id)
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


def _result(file_id: int, st: dict) -> dict:
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


# Background runs share the API's limit: each one holds LLM calls and a DB pool slot.
_slots = threading.BoundedSemaphore(int(os.environ.get("API_MAX_PARALLEL", "2")))


def _process(file_id: int) -> None:
    with _slots:
        try:
            service.run_upload(file_id)
        except Exception as e:
            log.exception("upload %s failed", file_id)
            with SessionLocal() as db:   # process_file marks its own failures; this catches the rest
                sf = db.get(SourceFile, file_id)
                if sf is not None and sf.status == "processing":
                    sf.status, sf.errors = "failed", [f"{type(e).__name__}: {e}"]
                    db.commit()


def resume_unfinished() -> None:
    """Files still 'processing' at startup lost their run with the last process (a restart
    or deploy while a background upload was working). Run them again: re-processing a
    file is idempotent. Without this the page would wait on them forever."""
    with SessionLocal() as db:
        ids = [i for (i,) in db.query(SourceFile.id).filter(SourceFile.status == "processing")]
    for i in ids:
        threading.Thread(target=_process, args=(i,), daemon=True).start()
    if ids:
        log.warning("resuming %d unfinished file(s): %s", len(ids), ids)


@router.post("/upload")
async def upload_file(file: UploadFile = File(...), hospital: str = Form(""),
                      round_id: int = Form(0), background: bool = Form(False),
                      user: AppUser = Depends(require_user)):
    """A results file. It must name the round it belongs to (D23): that is where its
    date comes from, and which workplace's register its people are looked up in.

    `background=true` (the Health Report page) answers at once with the file id and
    runs the graph in a thread; the page follows it at /api/upload/{id}/progress. The
    default still waits for the whole run and answers with the result, which is what
    every other caller (scenarios, evaluation) relies on."""
    filename = file.filename or "unknown"
    if filename.rsplit(".", 1)[-1].lower() not in ALLOWED:
        return {"success": False, "error": "รองรับเฉพาะไฟล์ .csv .xlsx และ .xls"}
    if not round_id:
        return {"success": False, "error": "กรุณาเลือกรอบตรวจก่อนส่งไฟล์ผลตรวจ"}
    content = await file.read()
    # Short-lived session, closed BEFORE the graph runs: no transaction may stay open while it
    # works (LLM calls take tens of seconds, and Postgres DDL such as the checkpointer's
    # CREATE INDEX CONCURRENTLY waits for every open transaction — that deadlocked once).
    with SessionLocal() as db:
        try:
            code = hospital_code_for(db, user, hospital)
        except ValueError as e:
            return {"success": False, "error": str(e)}
        if db.get(CheckupBatch, round_id) is None:
            return {"success": False, "error": "ไม่พบรอบตรวจที่เลือก"}
        file_id = register_file(db, filename, content, code, checkup_batch_id=round_id).id
    if background:
        progress.start(file_id, filename)
        threading.Thread(target=_process, args=(file_id,), daemon=True).start()
        return {"success": True, "upload_id": file_id, "status": "processing"}
    try:
        st = service.run_upload(file_id)
    except Exception as e:  # process_file already rolled back and marked the file failed
        return {"success": False, "upload_id": file_id, "error": f"{type(e).__name__}: {e}"}
    return _result(file_id, st)


@router.get("/upload/{file_id}/progress")
def upload_progress(file_id: int, user: AppUser = Depends(require_user)):
    """Where a background upload is: its steps while it runs (progress.py), then the
    same answer a waiting upload gives. Steps may be gone (the app restarted and
    resumed the file), in which case only the status is known — said as such."""
    with SessionLocal() as db:
        sf = db.get(SourceFile, file_id)
        if sf is None:
            raise HTTPException(404, "ไม่พบไฟล์")
        status_, errors = sf.status, list(sf.errors or [])
    p = progress.get(file_id)
    if status_ == "processing":
        return {"success": True, "upload_id": file_id, "status": "processing", "progress": p}
    if status_ == "failed":
        return {"success": False, "upload_id": file_id, "status": "failed", "progress": p,
                "error": "; ".join(errors) or "ประมวลผลไม่สำเร็จ"}
    return {**_result(file_id, service.status(file_id)), "progress": p}


@router.post("/upload/registry")
async def upload_registry(file: UploadFile = File(...), hospital: str = Form(""),
                          company_id: int = Form(0),
                          user: AppUser = Depends(require_user)):
    """A register file: who the people are, not what was measured (D23).

    It runs through registry.py rather than the lab pipeline — different columns,
    no units, no ranges — but keeps the same promise: an unrecognised header, an
    invalid CID or a department that does not exist becomes a question, and the
    row waits rather than landing half-understood.
    """
    filename = file.filename or "unknown"
    if filename.rsplit(".", 1)[-1].lower() not in ALLOWED:
        return {"success": False, "error": "รองรับเฉพาะไฟล์ .csv .xlsx และ .xls"}
    if not company_id:
        return {"success": False, "error": "กรุณาเลือกสถานประกอบการก่อนส่งไฟล์ทะเบียน"}
    content = await file.read()
    with SessionLocal() as db:
        try:
            code = hospital_code_for(db, user, hospital)
        except ValueError as e:
            return {"success": False, "error": str(e)}
        if db.get(Company, company_id) is None:
            return {"success": False, "error": "ไม่พบสถานประกอบการที่เลือก"}
        sf = register_file(db, filename, content, code, field_set="registry",
                           company_id=company_id)
        try:
            sheets = read_file(content, sf.file_type)
            result = registry.import_registry(db, sheets, sf.hospital_id, company_id, sf.id)
            for r in result.reviews:
                db.add(PendingReview(source_file_id=sf.id, kind=r["kind"], payload=r["payload"],
                                     field_set="registry", status="open"))
            sf.stats = result.as_stats()
            sf.status = "awaiting_review" if result.reviews else "completed"
            db.commit()
        except Exception as e:
            db.rollback()
            sf = db.merge(sf)
            sf.status, sf.errors = "failed", [f"{type(e).__name__}: {e}"]
            db.commit()
            return {"success": False, "upload_id": sf.id, "error": f"{type(e).__name__}: {e}"}
        return {"success": True, "upload_id": sf.id, "status": sf.status, **result.as_stats()}
