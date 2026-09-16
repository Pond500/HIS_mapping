"""
registration.py
===============
ขึ้นทะเบียนหน่วยบริการ (Env-Occ manual, pages 6–14).

A hospital fills the six steps of app/registration_form.py, uploads PDFs, and submits.
Central staff then check the papers: either they ask for fixes (the unit edits and
submits again) or they approve and issue the certificate.

    GET    /api/registration                 my hospital's current application + history
    POST   /api/registration                 start one (or return the open draft)
    PATCH  /api/registration/{id}/step/{sid} save one step
    POST   /api/registration/{id}/documents  upload a PDF (multipart)
    DELETE /api/registration/{id}/documents  remove one uploaded PDF
    POST   /api/registration/{id}/submit     send it in (only when nothing is missing)
    POST   /api/registration/{id}/cancel     throw the draft away
    GET    /api/registration/{id}/file       download one uploaded PDF or the certificate

    staff only:
    GET    /api/registration/review          applications waiting for staff
    POST   /api/registration/{id}/request-changes   {notes: [{key, label, note}]}
    POST   /api/registration/{id}/approve
    POST   /api/registration/{id}/issue      (multipart: the signed certificate PDF)
"""

import hashlib
import os
from datetime import date

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import registration_form as form
from app.auth import get_db, require_user
from app.models import AppUser, Hospital, ServiceRegistration
from app.routes.accounts import error

router = APIRouter(prefix="/api/registration", tags=["registration"])

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MAX_BYTES = int(float(os.environ.get("REGISTRATION_MAX_UPLOAD_MB", "10")) * 1024 * 1024)
STAFF = ("superadmin",)          # central staff review applications
EDITABLE = ("draft", "changes_requested")


def storage_dir(reg_id: int) -> str:
    base = os.environ.get("STORAGE_DIR", os.path.join(ROOT, "storage"))
    return os.path.join(base, "registrations", str(reg_id))


class StepIn(BaseModel):
    values: dict


class Note(BaseModel):
    key: str = ""
    label: str
    note: str = ""


class NotesIn(BaseModel):
    notes: list[Note]


def _mine(db: Session, user: AppUser, reg_id: int) -> ServiceRegistration:
    reg = db.get(ServiceRegistration, reg_id)
    if reg is None:
        raise error(404, "not_found", "ไม่พบคำขอขึ้นทะเบียนนี้")
    if user.role not in STAFF and reg.hospital_id != user.hospital_id:
        raise error(404, "not_found", "ไม่พบคำขอขึ้นทะเบียนนี้")
    return reg


def _out(db: Session, reg: ServiceRegistration) -> dict:
    d = reg.to_dict()
    h = db.get(Hospital, reg.hospital_id)
    d["hospital"] = h.code if h else None
    d["hospital_name"] = h.name if h else None
    d["status_th"] = form.STATUS_TH.get(reg.status, reg.status)
    d["missing"] = form.missing_everywhere(reg.data or {}, reg.documents or {})
    return d


# ---------------------------------------------------------------------------
# The hospital's own application
# ---------------------------------------------------------------------------

@router.get("")
def my_registration(user: AppUser = Depends(require_user), db: Session = Depends(get_db)):
    if user.hospital_id is None:
        return {"current": None, "history": [], "steps": form.STEPS, "timeline": form.TIMELINE}
    rows = (db.query(ServiceRegistration).filter(ServiceRegistration.hospital_id == user.hospital_id)
            .order_by(ServiceRegistration.id.desc()).all())
    current = next((r for r in rows if r.status != "cancelled"), None)
    return {"current": _out(db, current) if current else None,
            "history": [_out(db, r) for r in rows],
            "steps": form.STEPS, "timeline": form.TIMELINE}


@router.post("", status_code=201)
def start(user: AppUser = Depends(require_user), db: Session = Depends(get_db)):
    if user.hospital_id is None:
        raise error(400, "no_hospital", "บัญชีของคุณยังไม่มีสังกัดหน่วยบริการ")
    open_one = (db.query(ServiceRegistration)
                .filter(ServiceRegistration.hospital_id == user.hospital_id,
                        ServiceRegistration.status.in_(EDITABLE + ("submitted",)))
                .order_by(ServiceRegistration.id.desc()).first())
    if open_one is not None:
        return _out(db, open_one)
    reg = ServiceRegistration(hospital_id=user.hospital_id, created_by=user.id, status="draft", stage=1,
                              data={}, documents={}, review_notes=[], delivery={})
    db.add(reg)
    db.commit()
    db.refresh(reg)
    return _out(db, reg)


@router.patch("/{reg_id}/step/{step_id}")
def save_step(reg_id: int, step_id: str, body: StepIn, user: AppUser = Depends(require_user),
              db: Session = Depends(get_db)):
    reg = _mine(db, user, reg_id)
    if step_id not in form.STEP_BY_ID:
        raise error(404, "no_step", "ไม่พบขั้นตอนนี้")
    if reg.status not in EDITABLE:
        raise error(409, "locked", "คำขอนี้ส่งไปแล้ว แก้ไขได้เฉพาะตอนเป็นแบบร่างหรือเมื่อถูกตีกลับ")
    data = dict(reg.data or {})
    data[step_id] = body.values
    reg.data = data
    if step_id == "step6":
        reg.delivery = {k: v for k, v in body.values.items() if k.startswith(("delivery", "receiver"))}
    db.commit()
    return _out(db, reg)


@router.post("/{reg_id}/documents")
async def upload_document(reg_id: int, key: str = Form(...), file: UploadFile = File(...),
                          person: int | None = Form(None), doc_no: str = Form(""),
                          issued_on: str = Form(""), expires_on: str = Form(""),
                          issuer: str = Form(""),
                          user: AppUser = Depends(require_user), db: Session = Depends(get_db)):
    """Attach a PDF. `person` is the index in a people field (แพทย์ / พยาบาล)."""
    reg = _mine(db, user, reg_id)
    if reg.status not in EDITABLE:
        raise error(409, "locked", "คำขอนี้ส่งไปแล้ว แนบเอกสารเพิ่มไม่ได้")
    if not (file.filename or "").lower().endswith(".pdf"):
        raise error(415, "pdf_only", "รองรับเฉพาะไฟล์ PDF")
    content = await file.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise error(413, "too_large", f"ไฟล์ใหญ่เกิน {MAX_BYTES // (1024 * 1024)} MB")
    if not content:
        raise error(400, "empty_file", "ไฟล์ว่าง")
    sha = hashlib.sha256(content).hexdigest()
    folder = storage_dir(reg.id)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{sha}.pdf")
    with open(path, "wb") as fh:
        fh.write(content)
    item = {"filename": (file.filename or "document.pdf")[:300], "sha256": sha, "size": len(content),
            "doc_no": doc_no.strip(), "issued_on": issued_on.strip(), "expires_on": expires_on.strip(),
            "issuer": issuer.strip()}
    if person is None:
        docs = dict(reg.documents or {})
        docs[key] = [*docs.get(key, []), item]
        reg.documents = docs
    else:
        reg.data = _person_docs(reg.data, key, person, item, add=True)
    db.commit()
    return {"ok": True, "document": item, "registration": _out(db, reg)}


@router.delete("/{reg_id}/documents")
def delete_document(reg_id: int, key: str, sha256: str, person: int | None = None,
                    user: AppUser = Depends(require_user), db: Session = Depends(get_db)):
    reg = _mine(db, user, reg_id)
    if reg.status not in EDITABLE:
        raise error(409, "locked", "คำขอนี้ส่งไปแล้ว ลบเอกสารไม่ได้")
    if person is None:
        docs = dict(reg.documents or {})
        docs[key] = [d for d in docs.get(key, []) if d.get("sha256") != sha256]
        reg.documents = docs
    else:
        reg.data = _person_docs(reg.data, key, person, {"sha256": sha256}, add=False)
    db.commit()
    return _out(db, reg)


def _person_docs(data: dict, key: str, person: int, item: dict, add: bool) -> dict:
    """Add or remove one document inside people[person] of a step, leaving the rest alone.

    `key` is "<people field>:<document key>", e.g. "doctors:license"."""
    field_key, _, doc_key = key.partition(":")
    doc_key = doc_key or "license"
    data = dict(data or {})
    for step_id, values in list(data.items()):
        people = (values or {}).get(field_key)
        if not isinstance(people, list) or not (0 <= person < len(people)):
            continue
        people = [dict(p) for p in people]
        docs = dict(people[person].get("documents") or {})
        current = list(docs.get(doc_key, []))
        docs[doc_key] = ([*current, item] if add
                         else [d for d in current if d.get("sha256") != item.get("sha256")])
        people[person]["documents"] = docs
        values = dict(values)
        values[field_key] = people
        data[step_id] = values
        break
    return data


@router.post("/{reg_id}/submit")
def submit(reg_id: int, user: AppUser = Depends(require_user), db: Session = Depends(get_db)):
    reg = _mine(db, user, reg_id)
    if reg.status not in EDITABLE:
        raise error(409, "locked", "คำขอนี้ส่งไปแล้ว")
    missing = form.missing_everywhere(reg.data or {}, reg.documents or {})
    if missing:
        raise error(400, "incomplete", "กรอกข้อมูลและแนบเอกสารให้ครบทุกข้อก่อนยื่น")
    reg.status = "submitted"
    reg.stage = 2
    reg.submitted_at = func.now()
    reg.review_notes = []
    db.commit()
    return _out(db, reg)


@router.post("/{reg_id}/cancel")
def cancel(reg_id: int, user: AppUser = Depends(require_user), db: Session = Depends(get_db)):
    reg = _mine(db, user, reg_id)
    if reg.status != "draft":
        raise error(409, "locked", "ยกเลิกได้เฉพาะแบบร่าง")
    reg.status = "cancelled"
    db.commit()
    return {"ok": True}


@router.get("/{reg_id}/file")
def download(reg_id: int, sha256: str = "", certificate: bool = False,
             user: AppUser = Depends(require_user), db: Session = Depends(get_db)):
    reg = _mine(db, user, reg_id)
    if certificate:
        if not reg.certificate_path or not os.path.exists(reg.certificate_path):
            raise error(404, "no_certificate", "ยังไม่มีใบขึ้นทะเบียน")
        if user.role not in STAFF and not reg.certificate_downloaded:
            reg.certificate_downloaded = True       # manual: the unit may download it once
            db.commit()
        return FileResponse(reg.certificate_path, media_type="application/pdf",
                            filename=f"registration-{reg.id}.pdf")
    path = os.path.join(storage_dir(reg.id), f"{sha256}.pdf")
    if not sha256 or not os.path.exists(path):
        raise error(404, "not_found", "ไม่พบไฟล์นี้")
    return FileResponse(path, media_type="application/pdf")


# ---------------------------------------------------------------------------
# Central staff
# ---------------------------------------------------------------------------

@router.get("/review")
def review_queue(status: str = "submitted", user: AppUser = Depends(require_user),
                 db: Session = Depends(get_db)):
    if user.role not in STAFF:
        raise error(403, "forbidden", "เฉพาะเจ้าหน้าที่ส่วนกลาง")
    rows = db.query(ServiceRegistration)
    if status:
        rows = rows.filter(ServiceRegistration.status == status)
    return [_out(db, r) for r in rows.order_by(ServiceRegistration.submitted_at).all()]


@router.post("/{reg_id}/request-changes")
def request_changes(reg_id: int, body: NotesIn, user: AppUser = Depends(require_user),
                    db: Session = Depends(get_db)):
    if user.role not in STAFF:
        raise error(403, "forbidden", "เฉพาะเจ้าหน้าที่ส่วนกลาง")
    reg = _mine(db, user, reg_id)
    if reg.status != "submitted":
        raise error(409, "not_submitted", "คำขอนี้ยังไม่ได้ยื่น หรือดำเนินการไปแล้ว")
    if not body.notes:
        raise error(400, "no_notes", "ต้องระบุรายการที่ต้องแก้ไขอย่างน้อย 1 ข้อ")
    reg.status = "changes_requested"
    reg.stage = 2
    reg.reviewed_at = func.now()
    reg.review_notes = [n.model_dump() | {"fixed": False} for n in body.notes]
    db.commit()
    return _out(db, reg)


@router.post("/{reg_id}/approve")
def approve(reg_id: int, user: AppUser = Depends(require_user), db: Session = Depends(get_db)):
    if user.role not in STAFF:
        raise error(403, "forbidden", "เฉพาะเจ้าหน้าที่ส่วนกลาง")
    reg = _mine(db, user, reg_id)
    if reg.status != "submitted":
        raise error(409, "not_submitted", "อนุมัติได้เฉพาะคำขอที่ยื่นแล้ว")
    reg.status = "approved"
    reg.stage = 5
    reg.approved_at = func.now()
    reg.review_notes = []
    db.commit()
    return _out(db, reg)


@router.post("/{reg_id}/issue")
async def issue(reg_id: int, file: UploadFile = File(...), expires_on: str = Form(""),
                user: AppUser = Depends(require_user), db: Session = Depends(get_db)):
    """Attach the signed certificate; the unit may then download it (once)."""
    if user.role not in STAFF:
        raise error(403, "forbidden", "เฉพาะเจ้าหน้าที่ส่วนกลาง")
    reg = _mine(db, user, reg_id)
    if reg.status != "approved":
        raise error(409, "not_approved", "ต้องอนุมัติคำขอก่อน")
    if not (file.filename or "").lower().endswith(".pdf"):
        raise error(415, "pdf_only", "รองรับเฉพาะไฟล์ PDF")
    content = await file.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise error(413, "too_large", f"ไฟล์ใหญ่เกิน {MAX_BYTES // (1024 * 1024)} MB")
    folder = storage_dir(reg.id)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "certificate.pdf")
    with open(path, "wb") as fh:
        fh.write(content)
    reg.certificate_path = path
    reg.certificate_downloaded = False
    reg.status = "issued"
    reg.stage = 6
    reg.issued_at = func.now()
    if expires_on.strip():
        try:
            reg.expires_on = date.fromisoformat(expires_on.strip())
        except ValueError:
            raise error(400, "bad_date", "วันหมดอายุต้องเป็นรูปแบบ YYYY-MM-DD")
    db.commit()
    return _out(db, reg)
