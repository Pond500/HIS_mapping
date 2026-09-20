"""
rounds.py
=========
การสำรวจ Walk Through และรอบตรวจสุขภาพ (D23).

The department's chain is company -> survey -> round -> results, and every link
is NOT NULL. That is the whole reason the survey header is real rather than part
of the mockup: `employee_checkup_batches.survey_id` cannot be empty, so a round
— and therefore any result at all — cannot exist without one.

Only the header is stored here: which workplace, when, by whom. The risk
questionnaire the manual shows is still a mockup (D20), and nothing in this file
pretends otherwise.

    GET/POST   /api/surveys                    หัวการสำรวจ
    GET/POST   /api/rounds                     รอบตรวจ
    GET        /api/rounds/{id}                one round, with what is in it
    POST       /api/rounds/{id}/approve        รับรองผลทั้งรอบ
    GET        /api/checkup-types
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import require_user
from app.database import get_db
from app.models import (
    CheckupBatch, CheckupType, Company, EmployeeCheckup, SourceFile, WalkthroughSurvey,
)

router = APIRouter(prefix="/api", tags=["rounds"])


class SurveyIn(BaseModel):
    company_id: int
    survey_date: date
    surveyed_by: str | None = None
    note: str | None = None


class RoundIn(BaseModel):
    survey_id: int
    checkup_type: int
    appoint_date: date


class Approve(BaseModel):
    approved: bool = True


def _survey_dict(s: WalkthroughSurvey, company: Company, rounds: int = 0) -> dict:
    return {"id": s.id, "company_id": s.company_id, "company": company.name if company else None,
            "branch_name": company.branch_name if company else None,
            "survey_date": s.survey_date.isoformat(), "surveyed_by": s.surveyed_by,
            "note": s.note, "rounds": rounds}


@router.get("/checkup-types")
def checkup_types(db: Session = Depends(get_db), user=Depends(require_user)):
    return [{"id": t.id, "name": t.name} for t in db.query(CheckupType).order_by(CheckupType.id)]


@router.get("/surveys")
def list_surveys(company_id: int | None = None, db: Session = Depends(get_db),
                 user=Depends(require_user)):
    counts = dict(db.query(CheckupBatch.survey_id, func.count(CheckupBatch.id))
                  .group_by(CheckupBatch.survey_id).all())
    companies = {c.id: c for c in db.query(Company)}
    q = db.query(WalkthroughSurvey)
    if company_id is not None:
        q = q.filter(WalkthroughSurvey.company_id == company_id)
    return [_survey_dict(s, companies.get(s.company_id), counts.get(s.id, 0))
            for s in q.order_by(WalkthroughSurvey.survey_date.desc(), WalkthroughSurvey.id.desc())]


@router.post("/surveys", status_code=201)
def add_survey(body: SurveyIn, db: Session = Depends(get_db), user=Depends(require_user)):
    company = db.get(Company, body.company_id)
    if company is None:
        raise HTTPException(404, "ไม่พบสถานประกอบการ")
    s = WalkthroughSurvey(**body.model_dump())
    db.add(s)
    db.commit()
    return _survey_dict(s, company)


def _round_dict(db: Session, b: CheckupBatch) -> dict:
    survey = db.get(WalkthroughSurvey, b.survey_id)
    company = db.get(Company, survey.company_id) if survey else None
    people = (db.query(func.count(EmployeeCheckup.id))
              .filter(EmployeeCheckup.checkup_batch_id == b.id).scalar() or 0)
    files = (db.query(func.count(SourceFile.id))
             .filter(SourceFile.checkup_batch_id == b.id).scalar() or 0)
    return {"id": b.id, "survey_id": b.survey_id,
            "company_id": company.id if company else None,
            "company": company.name if company else None,
            "survey_date": survey.survey_date.isoformat() if survey else None,
            "checkup_type": b.checkup_type,
            "checkup_type_name": db.get(CheckupType, b.checkup_type).name,
            "appoint_date": b.appoint_date.isoformat(),
            "is_approved": b.is_approved, "approved_by": b.approved_by,
            "approved_at": b.approved_at.isoformat() if b.approved_at else None,
            "hospital_id": b.hospital_id, "people": people, "files": files}


@router.get("/rounds")
def list_rounds(company_id: int | None = None, db: Session = Depends(get_db),
                user=Depends(require_user)):
    q = db.query(CheckupBatch)
    if company_id is not None:
        q = (q.join(WalkthroughSurvey, WalkthroughSurvey.id == CheckupBatch.survey_id)
              .filter(WalkthroughSurvey.company_id == company_id))
    return [_round_dict(db, b) for b in q.order_by(CheckupBatch.appoint_date.desc(),
                                                   CheckupBatch.id.desc())]


@router.get("/rounds/{round_id}")
def get_round(round_id: int, db: Session = Depends(get_db), user=Depends(require_user)):
    b = db.get(CheckupBatch, round_id)
    if b is None:
        raise HTTPException(404, "ไม่พบรอบตรวจ")
    return _round_dict(db, b)


@router.post("/rounds", status_code=201)
def add_round(body: RoundIn, db: Session = Depends(get_db), user=Depends(require_user)):
    survey = db.get(WalkthroughSurvey, body.survey_id)
    if survey is None:
        raise HTTPException(404, "ไม่พบการสำรวจ Walk Through")
    if db.get(CheckupType, body.checkup_type) is None:
        raise HTTPException(404, "ไม่พบประเภทการตรวจ")
    dup = (db.query(CheckupBatch)
           .filter(CheckupBatch.survey_id == body.survey_id,
                   CheckupBatch.checkup_type == body.checkup_type,
                   CheckupBatch.appoint_date == body.appoint_date).one_or_none())
    if dup is not None:
        # the department's key for a round; a second one would split the same
        # visit's results across two rows
        raise HTTPException(409, "มีรอบตรวจของการสำรวจนี้ ประเภทนี้ และวันนัดนี้อยู่แล้ว")
    b = CheckupBatch(survey_id=body.survey_id, checkup_type=body.checkup_type,
                     appoint_date=body.appoint_date, hospital_id=user.hospital_id,
                     created_by=user.username)
    db.add(b)
    db.commit()
    return _round_dict(db, b)


@router.post("/rounds/{round_id}/approve")
def approve_round(round_id: int, body: Approve, db: Session = Depends(get_db),
                  user=Depends(require_user)):
    """รับรองผลทั้งรอบ. The dictionary points approved_by at a user, and the manual
    shows a doctor doing it — but D23 kept it open to anyone signed in, because
    this POC has one real user and a doctors-only gate would be a fiction."""
    b = db.get(CheckupBatch, round_id)
    if b is None:
        raise HTTPException(404, "ไม่พบรอบตรวจ")
    b.is_approved = body.approved
    b.approved_by = user.username if body.approved else None
    b.approved_at = func.now() if body.approved else None
    db.commit()
    db.refresh(b)
    return _round_dict(db, b)
