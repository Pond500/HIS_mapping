"""
Conflict routes (D13)
=====================
A later file gave a different value for a cell that already had one. The stored
value stays until a human decides; every change is written to value_history.

GET  /api/conflicts?status=open&file_id=…      conflicts with both values and where each came from
POST /api/conflicts/{id}/resolve               {"action": "keep" | "replace", "by"}
POST /api/files/{file_id}/conflicts/accept-all {"by"}  — the hospital re-sent a corrected file
"""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.auth import require_user
from app.database import get_db
from app.models import (
    CheckupBatch, Conflict, Employee, EmployeeCheckup, PendingReview, SourceFile,
    ValueHistory, ValueProvenance,
)
from app.template import FIELDS_BY_COLUMN

router = APIRouter(prefix="/api", tags=["conflicts"])


class Resolve(BaseModel):
    action: Literal["keep", "replace"]
    by: str = "reviewer"


class AcceptAll(BaseModel):
    by: str = "reviewer"


def _typed(column: str, text: str):
    kind = FIELDS_BY_COLUMN[column].kind
    if kind == "numeric":
        return Decimal(text)
    if kind == "categorical":
        return int(float(text))
    return text


def _conflict_dict(db: Session, c: Conflict) -> dict:
    checkup = db.get(EmployeeCheckup, c.checkup_id)
    e = db.get(Employee, checkup.employee_id)
    batch = db.get(CheckupBatch, checkup.checkup_batch_id)
    stored_prov = (db.query(ValueProvenance)
                   .filter(ValueProvenance.checkup_id == c.checkup_id, ValueProvenance.column == c.column)
                   .order_by(desc(ValueProvenance.id)).first())
    stored_file = db.get(SourceFile, stored_prov.source_file_id) if stored_prov else None
    incoming_file = db.get(SourceFile, c.source_file_id)
    return {
        "id": c.id, "status": c.status, "column": c.column,
        "cid": e.cid, "name": " ".join(x for x in (e.first_name, e.last_name) if x),
        "visit_date": (checkup.checkup_date or batch.appoint_date).isoformat(),
        "current_value": c.current_value, "incoming_value": c.incoming_value,
        "current_from": {"file": stored_file.filename if stored_file else None,
                         "sheet": stored_prov.sheet if stored_prov else None,
                         "cell": stored_prov.cell if stored_prov else None},
        "incoming_from": {"file": incoming_file.filename if incoming_file else None,
                          "sheet": (c.provenance or {}).get("sheet"), "cell": (c.provenance or {}).get("cell")},
        "source_file_id": c.source_file_id,
        "resolved_by": c.resolved_by,
    }


def _resolve(db: Session, c: Conflict, action: str, by: str):
    if c.status != "open":
        raise HTTPException(409, f"ข้อมูลขัดแย้ง #{c.id} ถูกตัดสินไปแล้ว ({c.status})")
    if action == "replace":
        checkup = db.get(EmployeeCheckup, c.checkup_id)
        old = getattr(checkup, c.column)
        setattr(checkup, c.column, _typed(c.column, c.incoming_value))
        db.add(ValueHistory(checkup_id=checkup.id, column=c.column,
                            old_value=None if old is None else str(old),
                            new_value=c.incoming_value, reason="conflict_resolved",
                            source_file_id=c.source_file_id, changed_by=by))
        prov = {k: v for k, v in (c.provenance or {}).items()
                if k in ("sheet", "cell", "raw_name", "raw_value", "raw_unit", "mapping_id")}
        db.add(ValueProvenance(checkup_id=checkup.id, column=c.column,
                               source_file_id=c.source_file_id, **prov))
        c.status = "replaced"
    else:
        c.status = "kept"
    c.resolved_by, c.resolved_at = by, datetime.utcnow()


def _refresh_file_status(db: Session, file_id: int):
    """A file is complete once nothing about it waits for a human."""
    sf = db.get(SourceFile, file_id)
    if sf is None or sf.status == "failed":
        return
    waiting = (db.query(PendingReview).filter(PendingReview.source_file_id == file_id,
                                              PendingReview.status == "open").count()
               + db.query(Conflict).filter(Conflict.source_file_id == file_id, Conflict.status == "open").count())
    sf.status = "awaiting_review" if waiting else "completed"


@router.get("/conflicts")
def list_conflicts(status: str = "open", file_id: int | None = None, limit: int = 5000,
                   db: Session = Depends(get_db), user=Depends(require_user)):
    """Same cap story as list_reviews: an unseen conflict is an undecided conflict."""
    q = db.query(Conflict).filter(Conflict.status == status)
    if file_id is not None:
        q = q.filter(Conflict.source_file_id == file_id)
    return [_conflict_dict(db, c) for c in q.order_by(Conflict.id).limit(max(1, limit))]


@router.post("/conflicts/{conflict_id}/resolve")
def resolve(conflict_id: int, body: Resolve, db: Session = Depends(get_db), user=Depends(require_user)):
    c = db.get(Conflict, conflict_id)
    if c is None:
        raise HTTPException(404, "ไม่พบข้อมูลขัดแย้ง")
    # The name comes from the signed-in account, never from the request: the browser
    # was trusted to say who decided, and history is the only trace of that.
    _resolve(db, c, body.action, user.username)
    db.flush()
    _refresh_file_status(db, c.source_file_id)
    db.commit()
    return _conflict_dict(db, c)


@router.post("/files/{file_id}/conflicts/accept-all")
def accept_all(file_id: int, body: AcceptAll, db: Session = Depends(get_db), user=Depends(require_user)):
    open_ = db.query(Conflict).filter(Conflict.source_file_id == file_id, Conflict.status == "open").all()
    for c in open_:
        _resolve(db, c, "replace", user.username)
    db.flush()
    _refresh_file_status(db, file_id)
    db.commit()
    return {"file_id": file_id, "replaced": len(open_)}
