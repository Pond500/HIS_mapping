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

from app.database import get_db
from app.graph import service
from app.models import SourceFile
from app.pipeline.run import get_or_create_hospital

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ALLOWED = ("csv", "xlsx", "xls")

router = APIRouter(prefix="/api", tags=["upload"])


def storage_dir() -> str:
    return os.environ.get("STORAGE_DIR", os.path.join(ROOT, "storage", "uploads"))


def register_file(db: Session, filename: str, content: bytes, hospital: str | None) -> SourceFile:
    """Stores the original bytes and creates the SourceFile row (committed)."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    sha = hashlib.sha256(content).hexdigest()
    os.makedirs(storage_dir(), exist_ok=True)
    stored_path = os.path.join(storage_dir(), f"{sha}.{ext}")
    with open(stored_path, "wb") as fh:
        fh.write(content)
    h = get_or_create_hospital(db, hospital)
    sf = SourceFile(hospital_id=h.id, filename=filename, file_type=ext, sha256=sha,
                    stored_path=stored_path, status="processing", stats={}, errors=[])
    db.add(sf)
    db.commit()
    db.refresh(sf)
    return sf


@router.post("/upload")
async def upload_file(file: UploadFile = File(...), hospital: str = Form("UNSPECIFIED"),
                      db: Session = Depends(get_db)):
    filename = file.filename or "unknown"
    if filename.rsplit(".", 1)[-1].lower() not in ALLOWED:
        return {"success": False, "error": "รองรับเฉพาะไฟล์ .csv .xlsx และ .xls"}
    sf = register_file(db, filename, await file.read(), hospital)
    try:
        st = service.run_upload(sf.id)
    except Exception as e:  # process_file already rolled back and marked the file failed
        return {"success": False, "upload_id": sf.id, "error": f"{type(e).__name__}: {e}"}
    stats = st["stats"] or {}
    return {
        "success": True,
        "upload_id": sf.id,
        "status": st["status"],
        "waiting_for_human": st["waiting_for_human"],
        "format_detected": ", ".join(f"{s['name']}({s['layout']})" for s in stats.get("sheets", [])),
        "total_rows": stats.get("total_rows", 0),
        "success_rows": stats.get("success_rows", 0),
        "error_rows": stats.get("error_rows", 0),
        "stats": stats,
        "errors": [f"รอตรวจ {k}: {n} รายการ" for k, n in stats.get("reviews_by_kind", {}).items()],
    }
