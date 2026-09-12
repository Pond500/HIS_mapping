"""
Review routes (D9)
==================
GET  /api/reviews?status=open&file_id=…   items waiting for a human, with the evidence
GET  /api/files/{id}                       status of one uploaded file
POST /api/files/{id}/decisions             reviewer decisions -> resume the file's graph
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.database import get_db
from app.graph import service
from app.models import PendingReview, SourceFile
from app.pipeline import units as U
from app.template import FIELDS_BY_COLUMN, RESULT_COLUMNS

router = APIRouter(prefix="/api", tags=["reviews"])


class Decision(BaseModel):
    review_id: int
    action: Literal["approve", "set", "extra", "ignore", "skip"]
    target: str | None = None
    unit: str | None = None       # unit the values are written in (for "set"); factor computed from it
    factor: float | None = None   # explicit factor (overrides unit)


class DecisionBody(BaseModel):
    decisions: list[Decision]
    by: str = "reviewer"


def _review_dict(r: PendingReview) -> dict:
    return {"id": r.id, "source_file_id": r.source_file_id, "kind": r.kind, "payload": r.payload,
            "status": r.status, "decision": r.decision, "created_at": r.created_at.isoformat() if r.created_at else None}


@router.get("/template/columns")
def template_columns():
    """Result columns for the reviewer's "set" choice."""
    from app.agents.catalog import DESC
    return [{"column": c, "kind": FIELDS_BY_COLUMN[c].kind, "unit": FIELDS_BY_COLUMN[c].unit, "desc": DESC[c]}
            for c in RESULT_COLUMNS]


@router.get("/reviews")
def list_reviews(status: str = "open", file_id: int | None = None, db: Session = Depends(get_db)):
    q = db.query(PendingReview).filter(PendingReview.status == status)
    if file_id is not None:
        q = q.filter(PendingReview.source_file_id == file_id)
    return [_review_dict(r) for r in q.order_by(desc(PendingReview.id)).limit(500)]


@router.get("/files/{file_id}")
def file_status(file_id: int, db: Session = Depends(get_db)):
    if db.get(SourceFile, file_id) is None:
        raise HTTPException(404, "ไม่พบไฟล์")
    return service.status(file_id)


@router.post("/files/{file_id}/decisions")
def decide(file_id: int, body: DecisionBody, db: Session = Depends(get_db)):
    decisions = []
    for d in body.decisions:
        r = db.get(PendingReview, d.review_id)
        if r is None or r.source_file_id != file_id or r.kind != "mapping":
            raise HTTPException(400, f"รายการ {d.review_id} ไม่ใช่รายการจับคู่ของไฟล์นี้")
        out = {"label": r.payload["label"], "unit": r.payload.get("unit"), "action": d.action, "by": body.by}
        if d.action == "set":
            if d.target not in RESULT_COLUMNS:
                raise HTTPException(400, f"ไม่มีคอลัมน์ {d.target} ใน template")
            factor = d.factor
            if factor is None:
                factor = U.factor(d.target, d.unit) if FIELDS_BY_COLUMN[d.target].kind == "numeric" else 1.0
            if factor is None:
                raise HTTPException(400, f"ไม่รู้จักหน่วย '{d.unit}' สำหรับ {d.target}")
            out.update(target=d.target, factor=factor)
        decisions.append(out)
    return service.decide(file_id, decisions)
