"""
Summary routes (D21)
====================
The reporting layer on top of what the pipeline already produced. It adds no new
data: it groups the stored results by หน่วยบริการ (hospital) + รอบปี (year of
visit_date) + แผนก (department_id), the three dimensions a file from an HIS
actually carries.

GET  /api/summary/options                      hospitals and years that have data
GET  /api/summary?hospital=&year=&department=  the numbers behind the dashboard
GET  /api/summary/submissions?hospital=&year=  what has been handed over before
POST /api/summary/submit                       record that this round was sent

There is deliberately no "risk factor" breakdown like the department's own screen:
a file from an HIS carries no company, no risk factor and no risk level, and a chart
drawn from data we do not have would be a guess presented as a fact.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import extract, func
from sqlalchemy.orm import Session

from app.auth import require_user
from app.database import get_db
from app.models import AppUser, Conflict, Employee, Hospital, PendingReview, ReportSubmission, SourceFile
from app.template import TEMPLATE_FIELDS

router = APIRouter(prefix="/api/summary", tags=["summary"])

RESULT_FIELDS = [f for f in TEMPLATE_FIELDS if f.group != "person"]
# the four columns stored as 1 = ปกติ / 2 = ผิดปกติ
CATEGORICAL = [f.column for f in RESULT_FIELDS if f.kind == "categorical"]
CATEGORICAL_TH = {
    "chest_xray": "เอกซเรย์ทรวงอก",
    "ekg": "คลื่นไฟฟ้าหัวใจ",
    "hearing_ability": "สมรรถภาพการได้ยิน",
    "far_vision_test": "สมรรถภาพการมองเห็น",
}


class SubmitIn(BaseModel):
    hospital: str
    year: int
    note: str | None = None


def _scope(db: Session, user: AppUser, hospital: str | None) -> Hospital:
    """Which hospital this request is about. Same rule as the upload (D20)."""
    if user.role == "superadmin":
        code = (hospital or "").strip()
        if not code:
            raise HTTPException(400, {"message": "กรุณาเลือกหน่วยบริการ"})
        h = db.query(Hospital).filter(Hospital.code == code).one_or_none()
        if h is None:
            raise HTTPException(404, {"message": f"ไม่พบหน่วยบริการรหัส {code}"})
        return h
    if user.hospital_id is None:
        raise HTTPException(400, {"message": "บัญชีนี้ยังไม่ได้ผูกกับหน่วยบริการ"})
    h = db.get(Hospital, user.hospital_id)
    if h is None:
        raise HTTPException(400, {"message": "ไม่พบหน่วยบริการของบัญชีนี้"})
    return h


@router.get("/options")
def options(db: Session = Depends(get_db), user: AppUser = Depends(require_user)):
    """Only hospitals and years that actually have results: no empty pickers."""
    hospitals = []
    if user.role == "superadmin":
        rows = (db.query(Hospital.code, Hospital.name, func.count(Employee.id))
                .join(Employee, Employee.hospital_id == Hospital.id)
                .group_by(Hospital.code, Hospital.name).order_by(Hospital.code).all())
        hospitals = [{"code": c, "name": n, "people": p} for c, n, p in rows]
    else:
        h = db.get(Hospital, user.hospital_id) if user.hospital_id else None
        if h:
            people = db.query(func.count(Employee.id)).filter(Employee.hospital_id == h.id).scalar() or 0
            hospitals = [{"code": h.code, "name": h.name, "people": people}]

    q = db.query(extract("year", Employee.visit_date).label("y"), func.count(Employee.id))
    if user.role != "superadmin" and user.hospital_id:
        q = q.filter(Employee.hospital_id == user.hospital_id)
    years = [{"year": int(y), "people": n} for y, n in
             q.group_by("y").order_by("y") if y is not None]
    years.reverse()
    return {"hospitals": hospitals, "years": years, "role": user.role}


@router.get("")
def summary(hospital: str | None = None, year: int | None = None,
            department: str | None = Query(None, max_length=50),
            db: Session = Depends(get_db), user: AppUser = Depends(require_user)):
    h = _scope(db, user, hospital)
    q = db.query(Employee).filter(Employee.hospital_id == h.id)
    if year:
        q = q.filter(extract("year", Employee.visit_date) == year)
    if department:
        q = q.filter(Employee.department_id == department)
    people = q.all()

    total = len(people)
    n_results = len(RESULT_FIELDS)

    # "ตรวจแล้ว" means this person has at least one result column filled in. Completeness
    # is counted, never assumed: a person with no result at all is shown as missing, which
    # is what the department's own screen calls ไม่พบข้อมูล.
    filled_counts = []
    complete = partial = none = 0
    for e in people:
        got = sum(1 for f in RESULT_FIELDS if getattr(e, f.column) is not None)
        filled_counts.append(got)
        if got == 0:
            none += 1
        elif got >= n_results * 0.8:
            complete += 1
        else:
            partial += 1

    by_department = {}
    for e, got in zip(people, filled_counts):
        d = e.department_id or "ไม่ระบุแผนก"
        row = by_department.setdefault(d, {"department": d, "people": 0, "with_results": 0})
        row["people"] += 1
        if got:
            row["with_results"] += 1

    findings = []
    for col in CATEGORICAL:
        normal = sum(1 for e in people if getattr(e, col) == 1)
        abnormal = sum(1 for e in people if getattr(e, col) == 2)
        findings.append({"column": col, "label": CATEGORICAL_TH.get(col, col),
                         "normal": normal, "abnormal": abnormal,
                         "missing": total - normal - abnormal})

    # What is still waiting for a human in this hospital. The page warns with it before
    # a hand-over: an answer given here can still change what the exported file says,
    # and a name column confirmed later fills into rows that are already stored.
    review_rows = (db.query(PendingReview.kind, func.count(PendingReview.id))
                   .join(SourceFile, SourceFile.id == PendingReview.source_file_id)
                   .filter(SourceFile.hospital_id == h.id, PendingReview.status == "open")
                   .group_by(PendingReview.kind).all())
    open_reviews = {kind: n for kind, n in review_rows}
    open_conflicts = (db.query(func.count(Conflict.id))
                      .join(SourceFile, SourceFile.id == Conflict.source_file_id)
                      .filter(SourceFile.hospital_id == h.id, Conflict.status == "open").scalar() or 0)
    without_name = sum(1 for e in people if not (e.first_name or e.last_name))

    last_q = db.query(ReportSubmission).filter(ReportSubmission.hospital_id == h.id)
    if year:
        last_q = last_q.filter(ReportSubmission.year == year)
    last = last_q.order_by(ReportSubmission.submitted_at.desc()).first()

    return {
        "hospital": {"code": h.code, "name": h.name},
        "year": year,
        "department": department,
        "people": total,
        "cells": {"filled": sum(filled_counts), "possible": total * n_results,
                  "per_person": n_results},
        "completeness": {"complete": complete, "partial": partial, "none": none},
        "departments": sorted(by_department.values(), key=lambda r: r["department"]),
        "findings": findings,
        "open_work": {"reviews": open_reviews, "reviews_total": sum(open_reviews.values()),
                      "conflicts": open_conflicts, "people_without_name": without_name},
        "last_submission": None if last is None else {
            "id": last.id, "people": last.people, "submitted_by": last.submitted_by,
            "submitted_at": last.submitted_at.isoformat() if last.submitted_at else None,
        },
    }


@router.get("/submissions")
def submissions(hospital: str | None = None, db: Session = Depends(get_db),
                user: AppUser = Depends(require_user)):
    h = _scope(db, user, hospital)
    rows = (db.query(ReportSubmission).filter(ReportSubmission.hospital_id == h.id)
            .order_by(ReportSubmission.submitted_at.desc()).limit(200).all())
    return [{"id": r.id, "year": r.year, "people": r.people, "note": r.note,
             "submitted_by": r.submitted_by,
             "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
             "summary": r.summary} for r in rows]


@router.post("/submit")
def submit(body: SubmitIn, db: Session = Depends(get_db), user: AppUser = Depends(require_user)):
    """
    Records that this round was handed to the department. It does not transmit
    anything: the department has not published a way in, so claiming "sent" on a
    screen while nothing left the building would be a lie the user acts on.
    """
    h = _scope(db, user, body.hospital)
    snapshot = summary(hospital=body.hospital, year=body.year, department=None, db=db, user=user)
    if snapshot["people"] == 0:
        raise HTTPException(400, {"message": "รอบนี้ยังไม่มีข้อมูลผลตรวจ จึงยังส่งไม่ได้"})

    row = ReportSubmission(
        hospital_id=h.id, year=body.year, people=snapshot["people"],
        summary={k: snapshot[k] for k in ("cells", "completeness", "departments", "findings")},
        note=(body.note or None), submitted_by=user.username, submitted_at=datetime.utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "people": row.people, "year": row.year,
            "submitted_at": row.submitted_at.isoformat()}
