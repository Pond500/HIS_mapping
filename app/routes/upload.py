"""
Upload route
============
POST /api/upload — store the original file, then run the conversion pipeline.
"""

import hashlib
import os

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import SourceFile
from app.pipeline.run import get_or_create_hospital, process_file

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STORAGE_DIR = os.environ.get("STORAGE_DIR", os.path.join(ROOT, "storage", "uploads"))
ALLOWED = ("csv", "xlsx", "xls")

router = APIRouter(prefix="/api", tags=["upload"])


@router.post("/upload")
async def upload_file(file: UploadFile = File(...), hospital: str = Form("UNSPECIFIED"),
                      db: Session = Depends(get_db)):
    filename = file.filename or "unknown"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED:
        return {"success": False, "error": "รองรับเฉพาะไฟล์ .csv .xlsx และ .xls"}

    content = await file.read()
    sha = hashlib.sha256(content).hexdigest()
    os.makedirs(STORAGE_DIR, exist_ok=True)
    stored_path = os.path.join(STORAGE_DIR, f"{sha}.{ext}")
    with open(stored_path, "wb") as fh:
        fh.write(content)

    h = get_or_create_hospital(db, hospital)
    sf = SourceFile(hospital_id=h.id, filename=filename, file_type=ext, sha256=sha,
                    stored_path=stored_path, status="processing", stats={}, errors=[])
    db.add(sf)
    db.commit()
    db.refresh(sf)

    try:
        stats = process_file(db, sf)
    except Exception as e:  # already rolled back and marked failed by process_file
        return {"success": False, "upload_id": sf.id, "error": f"{type(e).__name__}: {e}"}

    return {
        "success": True,
        "upload_id": sf.id,
        "status": sf.status,
        "format_detected": ", ".join(f"{s['name']}({s['layout']})" for s in stats["sheets"]),
        "total_rows": stats["total_rows"],
        "success_rows": stats["success_rows"],
        "error_rows": stats["error_rows"],
        "stats": stats,
        "errors": [f"รอตรวจ {k}: {n} รายการ" for k, n in stats["reviews_by_kind"].items()],
    }
