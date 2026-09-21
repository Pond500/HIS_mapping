"""
Summary and hand-over (D21, D23)
================================
The reporting layer on top of what the pipeline already produced. It adds no new
data: it groups the stored results by รอบตรวจ, which since D23 is the unit the
department actually receives — one workplace, one appointment date, one set of
people.

GET  /api/summary/options                 rounds that have something in them
GET  /api/summary?round_id=               the numbers behind the dashboard
GET  /api/summary/submissions             what has been handed over before
POST /api/summary/submit                  build the file and record the hand-over
GET  /api/summary/download/{id}           the file that was handed over

There is deliberately no "risk factor" breakdown like the department's own screen.
Risk factors come from the Walk Through questionnaire, which is still a mockup, and
a chart drawn from data we do not have would be a guess presented as a fact.
"""

import hashlib
import io
import os
from datetime import datetime

import openpyxl
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import require_user
from app.database import get_db
from app.models import (
    AppUser, CheckupBatch, CheckupType, Company, Conflict, Department, Employee,
    EmployeeCheckup, Hospital, PendingReview, ReportSubmission, SourceFile,
    WalkthroughSurvey,
)
from app.template import REGISTRY_FIELDS, TEMPLATE_FIELDS

router = APIRouter(prefix="/api/summary", tags=["summary"])

RESULT_FIELDS = [f for f in TEMPLATE_FIELDS if f.group != "person"]
CATEGORICAL = [f.column for f in RESULT_FIELDS if f.kind == "categorical"]
CATEGORICAL_TH = {
    "chest_xray": "เอกซเรย์ทรวงอก",
    "ekg": "คลื่นไฟฟ้าหัวใจ",
    "hearing_ability": "สมรรถภาพการได้ยิน",
    "far_vision_test": "สมรรถภาพการมองเห็น",
}


class SubmitIn(BaseModel):
    round_id: int
    note: str | None = None
    # A hand-over with questions or conflicts still open is refused unless a person says,
    # in so many words, that they want it anyway. The default is the safe answer.
    confirm_open_work: bool = False


def _round_or_404(db: Session, round_id: int) -> CheckupBatch:
    b = db.get(CheckupBatch, round_id)
    if b is None:
        raise HTTPException(404, {"message": "ไม่พบรอบตรวจ"})
    return b


def _round_label(db: Session, b: CheckupBatch) -> dict:
    survey = db.get(WalkthroughSurvey, b.survey_id)
    company = db.get(Company, survey.company_id) if survey else None
    return {"id": b.id, "company": company.name if company else None,
            "company_id": company.id if company else None,
            "appoint_date": b.appoint_date.isoformat(),
            "checkup_type": db.get(CheckupType, b.checkup_type).name,
            "is_approved": b.is_approved}


@router.get("/options")
def options(db: Session = Depends(get_db), user: AppUser = Depends(require_user)):
    """Only rounds that have results in them: no empty pickers."""
    counts = dict(db.query(EmployeeCheckup.checkup_batch_id, func.count(EmployeeCheckup.id))
                  .group_by(EmployeeCheckup.checkup_batch_id).all())
    rounds = []
    for b in db.query(CheckupBatch).order_by(CheckupBatch.appoint_date.desc()):
        if counts.get(b.id):
            rounds.append({**_round_label(db, b), "people": counts[b.id]})
    return {"rounds": rounds, "role": user.role}


@router.get("")
def summary(round_id: int, db: Session = Depends(get_db),
            user: AppUser = Depends(require_user)):
    b = _round_or_404(db, round_id)
    survey = db.get(WalkthroughSurvey, b.survey_id)
    hospital = db.get(Hospital, b.hospital_id)

    rows = (db.query(EmployeeCheckup, Employee, Department)
            .join(Employee, Employee.id == EmployeeCheckup.employee_id)
            .join(Department, Department.id == Employee.department_pk)
            .filter(EmployeeCheckup.checkup_batch_id == b.id).all())

    total = len(rows)
    n_results = len(RESULT_FIELDS)

    # Completeness is counted, never assumed: someone with no result at all is shown
    # as missing, which is what the department's own screen calls ไม่พบข้อมูล.
    complete = partial = none = 0
    filled_total = 0
    by_department: dict[str, dict] = {}
    incomplete_registry = 0

    for checkup, person, dept in rows:
        got = sum(1 for f in RESULT_FIELDS if getattr(checkup, f.column) is not None)
        filled_total += got
        if got == 0:
            none += 1
        elif got >= n_results * 0.8:
            complete += 1
        else:
            partial += 1
        row = by_department.setdefault(dept.name, {"department": dept.name, "people": 0,
                                                   "with_results": 0})
        row["people"] += 1
        if got:
            row["with_results"] += 1
        if not person.registry_complete:
            incomplete_registry += 1

    findings = []
    for col in CATEGORICAL:
        # 0 = ปกติ, 1 = ผิดปกติ — the department's codes, which is what is stored (D23)
        normal = sum(1 for c, _, _ in rows if getattr(c, col) == 0)
        abnormal = sum(1 for c, _, _ in rows if getattr(c, col) == 1)
        findings.append({"column": col, "label": CATEGORICAL_TH.get(col, col),
                         "normal": normal, "abnormal": abnormal,
                         "missing": total - normal - abnormal})

    # What is still waiting for a human on this round's files. The page warns with it
    # before a hand-over: an answer given here can still change what the file says.
    review_rows = (db.query(PendingReview.kind, func.count(PendingReview.id))
                   .join(SourceFile, SourceFile.id == PendingReview.source_file_id)
                   .filter(SourceFile.checkup_batch_id == b.id, PendingReview.status == "open")
                   .group_by(PendingReview.kind).all())
    open_reviews = {kind: n for kind, n in review_rows}
    open_conflicts = (db.query(func.count(Conflict.id))
                      .join(SourceFile, SourceFile.id == Conflict.source_file_id)
                      .filter(SourceFile.checkup_batch_id == b.id,
                              Conflict.status == "open").scalar() or 0)

    last = (db.query(ReportSubmission)
            .filter(ReportSubmission.checkup_batch_id == b.id)
            .order_by(ReportSubmission.submitted_at.desc()).first())

    return {
        "round": _round_label(db, b),
        "survey_date": survey.survey_date.isoformat() if survey else None,
        "hospital": {"code": hospital.code, "name": hospital.name} if hospital else None,
        "people": total,
        "cells": {"filled": filled_total, "possible": total * n_results,
                  "per_person": n_results},
        "completeness": {"complete": complete, "partial": partial, "none": none},
        "departments": sorted(by_department.values(), key=lambda r: r["department"]),
        "findings": findings,
        "open_work": {"reviews": open_reviews, "reviews_total": sum(open_reviews.values()),
                      "conflicts": open_conflicts,
                      "incomplete_registry": incomplete_registry},
        "last_submission": None if last is None else {
            "id": last.id, "people": last.people, "submitted_by": last.submitted_by,
            "submitted_at": last.submitted_at.isoformat() if last.submitted_at else None,
        },
    }


# ---------------------------------------------------------------------------
# The file the department receives
# ---------------------------------------------------------------------------

#: employee_checkups columns, in the dictionary's own spelling. Built from
#: template.py so the two cannot drift: it stays the single source of truth.
CHECKUP_COLUMNS = ["citizen_id", "checkup_date"] + [f.column for f in RESULT_FIELDS]


def build_submission_file(db: Session, b: CheckupBatch) -> bytes:
    """Two sheets, named and shaped like the department's own tables (D23-ก).

    Values are written exactly as stored, which is already their form: 10^3/uL for
    wbc and plt, 0/1 for the categorical columns. No second conversion happens here,
    because a conversion that exists in two places is a conversion that will
    eventually disagree with itself.
    """
    rows = (db.query(EmployeeCheckup, Employee, Department)
            .join(Employee, Employee.id == EmployeeCheckup.employee_id)
            .join(Department, Department.id == Employee.department_pk)
            .filter(EmployeeCheckup.checkup_batch_id == b.id)
            .order_by(Employee.cid).all())

    wb = openpyxl.Workbook()

    ws = wb.active
    ws.title = "employees"
    reg_headers = [f.header for f in REGISTRY_FIELDS]
    ws.append(reg_headers)
    for _, person, dept in rows:
        line = []
        for f in REGISTRY_FIELDS:
            if f.column == "department_id":
                line.append(dept.name)
            else:
                v = getattr(person, f.column)
                line.append(float(v) if f.kind == "numeric" and v is not None else v)
        ws.append(line)

    ws2 = wb.create_sheet("employee_checkups")
    ws2.append(CHECKUP_COLUMNS)
    for checkup, person, _ in rows:
        line = [person.cid, (checkup.checkup_date or b.appoint_date).isoformat()]
        for f in RESULT_FIELDS:
            v = getattr(checkup, f.column)
            line.append(float(v) if f.kind == "numeric" and v is not None else v)
        ws2.append(line)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _submission_path(sha: str) -> str:
    root = os.environ.get("STORAGE_DIR", os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "storage", "uploads"))
    out = os.path.join(os.path.dirname(root), "submissions")
    os.makedirs(out, exist_ok=True)
    return os.path.join(out, f"{sha}.xlsx")


@router.get("/submissions")
def submissions(round_id: int | None = None, db: Session = Depends(get_db),
                user: AppUser = Depends(require_user)):
    q = db.query(ReportSubmission)
    if round_id is not None:
        q = q.filter(ReportSubmission.checkup_batch_id == round_id)
    rows = q.order_by(ReportSubmission.submitted_at.desc()).limit(200).all()
    return [{"id": r.id, "year": r.year, "people": r.people, "note": r.note,
             "round_id": r.checkup_batch_id, "file_sha256": r.file_sha256,
             "submitted_by": r.submitted_by,
             "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
             "summary": r.summary} for r in rows]


@router.post("/submit")
def submit(body: SubmitIn, db: Session = Depends(get_db), user: AppUser = Depends(require_user)):
    """
    Builds the file and records that this round was handed over. It does not
    transmit anything: the department has not published a way in, so saying "sent"
    on a screen while nothing left the building would be a lie the user acts on.
    """
    b = _round_or_404(db, body.round_id)
    snapshot = summary(round_id=body.round_id, db=db, user=user)
    if snapshot["people"] == 0:
        raise HTTPException(400, {"message": "รอบนี้ยังไม่มีข้อมูลผลตรวจ จึงยังส่งไม่ได้"})

    ow = snapshot["open_work"]
    waiting = ow["reviews_total"] + ow["conflicts"]
    if waiting and not body.confirm_open_work:
        # Every value here is meant to be right or flagged for a person. A file sent with
        # questions still open is a file whose flagged values are missing or unsettled, and
        # it used to go out with only a warning on the screen.
        raise HTTPException(409, {"message": f"ยังมีงานค้าง {waiting} รายการ (คำถามและข้อมูลขัดแย้ง) "
                                             f"เคลียร์ที่หน้างานที่ต้องตรวจก่อน หรือยืนยันว่าส่งทั้งที่ยังค้าง",
                                  "code": "open_work", "open_work": ow})

    content = build_submission_file(db, b)
    sha = hashlib.sha256(content).hexdigest()
    with open(_submission_path(sha), "wb") as fh:
        fh.write(content)

    row = ReportSubmission(
        hospital_id=b.hospital_id, checkup_batch_id=b.id, year=b.appoint_date.year,
        people=snapshot["people"],
        summary={**{k: snapshot[k] for k in ("cells", "completeness", "departments",
                                             "findings", "open_work")},
                 # who chose to send it with things still open is part of the record
                 "sent_with_open_work": bool(waiting), "confirmed_by": user.username if waiting else None},
        file_sha256=sha, note=(body.note or None), submitted_by=user.username,
        submitted_at=datetime.utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "people": row.people, "year": row.year,
            "file_sha256": sha, "submitted_at": row.submitted_at.isoformat()}


@router.get("/download/{submission_id}")
def download(submission_id: int, db: Session = Depends(get_db),
             user: AppUser = Depends(require_user)):
    """The exact bytes that were handed over, not a fresh export.

    A later file can change what a fresh export would say; the record and the
    document must not be able to disagree about what was sent.
    """
    row = db.get(ReportSubmission, submission_id)
    if row is None or not row.file_sha256:
        raise HTTPException(404, {"message": "ไม่พบชุดที่ส่ง"})
    path = _submission_path(row.file_sha256)
    if not os.path.exists(path):
        raise HTTPException(404, {"message": "ไม่พบไฟล์ของชุดที่ส่ง (อาจถูกลบออกจาก storage)"})
    return StreamingResponse(
        open(path, "rb"),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="submission-{row.id}.xlsx"'})
