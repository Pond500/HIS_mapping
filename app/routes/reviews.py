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

from app.auth import require_user
from app.database import get_db
from app.database import SessionLocal
from app.graph import service
from app.pipeline.run import process_file
from app.models import (
    CheckupBatch, Department, Employee, PendingReview, SourceFile, WalkthroughSurvey,
)
from app.pipeline import units as U
from app.template import COLUMNS, FIELDS_BY_COLUMN, RESULT_COLUMNS

router = APIRouter(prefix="/api", tags=["reviews"])


class Decision(BaseModel):
    review_id: int
    action: Literal["approve", "set", "extra", "ignore", "skip", "identity", "comment", "department",
                    "register", "move_department", "use_register"]
    target: str | None = None
    unit: str | None = None       # unit the values are written in (for "set"); factor computed from it
    factor: float | None = None   # explicit factor (overrides unit)
    role: str | None = None       # identity review: which role the chosen column holds
    header: str | None = None     # identity review: the column header
    value: int | None = None      # comment review: 1 normal / 2 abnormal (applies to every row with this text)
    code: str | None = None       # department review: the code for this department name (D18)
    first_name: str | None = None  # unregistered_person: the name to file them under
    last_name: str | None = None


class DecisionBody(BaseModel):
    decisions: list[Decision]
    by: str = "reviewer"


def _review_dict(r: PendingReview) -> dict:
    return {"id": r.id, "source_file_id": r.source_file_id, "kind": r.kind, "payload": r.payload,
            "status": r.status, "decision": r.decision, "created_at": r.created_at.isoformat() if r.created_at else None}


@router.get("/template/columns")
def template_columns(all: bool = False, user=Depends(require_user)):
    """
    Result columns for the reviewer's "set" choice.

    `all=true` adds the five person columns and each column's template header and
    group, so a page can lay out a person's results without hard-coding the 45
    columns again: template.py stays the single source of truth.
    """
    from app.agents.catalog import DESC
    columns = COLUMNS if all else RESULT_COLUMNS
    out = []
    for c in columns:
        f = FIELDS_BY_COLUMN[c]
        row = {"column": c, "kind": f.kind, "unit": f.unit, "desc": DESC.get(c, f.header)}
        if all:
            row.update(header=f.header, group=f.group)
        out.append(row)
    return out


@router.get("/reviews")
def list_reviews(status: str = "open", file_id: int | None = None, limit: int = 5000,
                 db: Session = Depends(get_db), user=Depends(require_user)):
    """
    The cap used to be a silent 500. Reviews are the only way an item waiting for a
    human is visible at all, so anything past the cap waited forever with nothing on
    the screen to say so: on 2026-09-16 one database held 521 open reviews and the page
    showed 3 of the 24 mapping questions. Callers now choose the cap and can tell they
    hit it, because the answer comes back exactly `limit` long.
    """
    q = db.query(PendingReview).filter(PendingReview.status == status)
    if file_id is not None:
        q = q.filter(PendingReview.source_file_id == file_id)
    return [_review_dict(r) for r in q.order_by(desc(PendingReview.id)).limit(max(1, limit))]


@router.get("/files/{file_id}")
def file_status(file_id: int, db: Session = Depends(get_db), user=Depends(require_user)):
    if db.get(SourceFile, file_id) is None:
        raise HTTPException(404, "ไม่พบไฟล์")
    db.close()   # never hold a transaction open while the graph/checkpointer works
    return service.status(file_id)


def _company_of_file(db: Session, sf: SourceFile) -> int | None:
    if sf.company_id:
        return sf.company_id
    batch = db.get(CheckupBatch, sf.checkup_batch_id) if sf.checkup_batch_id else None
    if batch is None:
        return None
    survey = db.get(WalkthroughSurvey, batch.survey_id)
    return survey.company_id if survey else None


def _apply_people_decision(db: Session, sf: SourceFile, r: PendingReview, d: Decision, by: str) -> None:
    """The two decisions that change the register rather than a mapping (D23).

    They are applied here, against the database, instead of being handed to the
    graph: the graph answers "what does this label mean", and these answer "who is
    this person". Re-processing the file afterwards is what actually stores the
    results that were held back.
    """
    company_id = _company_of_file(db, sf)
    if company_id is None:
        raise HTTPException(400, "ไฟล์นี้ยังไม่ผูกกับสถานประกอบการ")

    if r.kind == "unregistered_person":
        dept_name = d.header or r.payload.get("department_in_file")
        dept = (db.query(Department)
                .filter(Department.company_id == company_id, Department.name == dept_name).one_or_none())
        if dept is None:
            raise HTTPException(400, f"ไม่มีแผนก “{dept_name}” ในสถานประกอบการนี้ "
                                     f"— เพิ่มแผนกที่หน้าทะเบียนสถานประกอบการก่อน")
        first, last = d.first_name, d.last_name
        if not first and not last:
            # The name in the file is a suggestion, not an answer; the reviewer may
            # correct it, but a person is never added with no name at all.
            parts = (r.payload.get("name_in_file") or "").split()
            first, last = (parts[0] if parts else None), (" ".join(parts[1:]) or None)
        if not first:
            raise HTTPException(400, "ต้องระบุชื่ออย่างน้อยหนึ่งช่องก่อนเพิ่มเข้าทะเบียน")
        db.add(Employee(cid=r.payload["cid"], department_pk=dept.id,
                        first_name=first, last_name=last, source_file_id=sf.id))
        return

    # department_change
    person = (db.query(Employee).join(Department, Department.id == Employee.department_pk)
              .filter(Employee.cid == r.payload["cid"], Department.company_id == company_id).first())
    if person is None:
        raise HTTPException(400, "ไม่พบคนนี้ในทะเบียนแล้ว")
    if d.action == "use_register":
        return                      # the file was wrong; the register stands, results land as they are
    target = (db.query(Department)
              .filter(Department.company_id == company_id,
                      Department.name == r.payload["department_in_file"]).one_or_none())
    if target is None:
        raise HTTPException(400, f"ไม่มีแผนก “{r.payload['department_in_file']}” ในสถานประกอบการนี้")
    # The department keys people by (citizen_id, department_id), so someone who has
    # genuinely moved is a second row, not an edited one — their history in the old
    # department stays where it happened.
    exists = (db.query(Employee)
              .filter(Employee.cid == person.cid, Employee.department_pk == target.id).one_or_none())
    if exists is None:
        db.add(Employee(cid=person.cid, department_pk=target.id, first_name=person.first_name,
                        last_name=person.last_name, title=person.title, gender=person.gender,
                        birth_year=person.birth_year, nationality=person.nationality,
                        position=person.position, work_experience=person.work_experience,
                        medical_condition=person.medical_condition, source_file_id=sf.id))


@router.post("/files/{file_id}/decisions")
def decide(file_id: int, body: DecisionBody, db: Session = Depends(get_db), user=Depends(require_user)):
    sf = db.get(SourceFile, file_id)
    if sf is None:
        raise HTTPException(404, "ไม่พบไฟล์")
    decisions, touched_people = [], False
    for d in body.decisions:
        r = db.get(PendingReview, d.review_id)
        if r is None or r.source_file_id != file_id or r.kind not in (
                "mapping", "identity", "comment", "department",
                "unregistered_person", "department_change"):
            raise HTTPException(400, f"รายการ {d.review_id} ไม่ใช่รายการจับคู่ของไฟล์นี้")
        if r.kind in ("unregistered_person", "department_change"):
            if d.action == "skip":
                continue
            if d.action not in ("register", "move_department", "use_register"):
                raise HTTPException(400, f"รายการ {d.review_id}: ต้องเลือกว่าจะทำอย่างไรกับคนนี้")
            _apply_people_decision(db, sf, r, d, body.by)
            r.status, r.decision, r.decided_by = "approved", {"action": d.action}, body.by
            touched_people = True
            continue
        if r.kind == "department":
            if d.action == "skip":
                continue
            from app.pipeline.normalize import looks_like_code
            if d.action != "department" or not d.code or not looks_like_code(d.code):
                raise HTTPException(400, f"รายการ {d.review_id}: ใส่รหัสแผนก (ตัวอักษรอังกฤษ/ตัวเลข เช่น QC, PROD-01)")
            decisions.append({"action": "department", "name": r.payload["name"], "code": d.code.strip(),
                              "by": body.by})
            continue
        if r.kind == "comment":
            if d.action == "skip":
                continue
            if d.action != "comment" or d.value not in (1, 2):
                raise HTTPException(400, f"รายการ {d.review_id}: เลือกปกติ (1) หรือผิดปกติ (2)")
            decisions.append({"action": "comment", "column": r.payload["column"], "text": r.payload["text"],
                              "value": d.value, "by": body.by})
            continue
        if r.kind == "identity":
            if d.action == "skip":
                continue
            if d.action != "identity" or d.role not in (r.payload.get("missing") or []) or not d.header:
                raise HTTPException(400, f"รายการ {d.review_id}: ต้องเลือกคอลัมน์ให้ข้อมูลที่หาไม่พบ")
            decisions.append({"action": "identity", "role": d.role, "header": d.header, "by": body.by})
            continue
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
    if touched_people:
        db.commit()
    # close the request's read transaction first: resuming the graph can run LLM calls
    # for minutes, and an open transaction blocks Postgres DDL (see app/routes/upload.py)
    db.close()
    if not decisions and touched_people:
        # Nothing for the graph to answer, but the file must run again: that is what
        # stores the results that were waiting on these people.
        with SessionLocal() as db2:
            process_file(db2, db2.get(SourceFile, file_id))
        return service.status(file_id)
    return service.decide(file_id, decisions)
