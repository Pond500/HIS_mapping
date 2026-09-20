"""
manual.py
=========
กรอกผลตรวจทีละคน (D23).

The bulk path is the AI import; this is the other one the department's manual
has and we agreed to keep: one person walks in, or a value was typed wrong and
has to be corrected.

Two things make this different from the import, and both are on purpose:

  * What is typed here is stored as typed. There is no unit conversion, because
    the person is looking at the form's own labels, which already state the unit
    the department stores — mg/dL, 10^3/uL, ปกติ/ผิดปกติ. Converting what someone
    read off a label would change a number they can see.
  * Every change is written to value_history with the name of whoever made it.
    An imported value can always be traced to a file, sheet and cell; a typed one
    can only be traced to a person, so that trace has to exist.

    GET  /api/rounds/{id}/people     who can be filled in for this round
    GET  /api/checkups/{id}          one person's results in one round
    PUT  /api/checkups               save (creates the row if this is the first value)
"""

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import require_user
from app.pipeline import normalize as N
from app.database import get_db
from app.models import (
    AppUser, CheckupBatch, Company, Department, Employee, EmployeeCheckup,
    ValueHistory, WalkthroughSurvey,
)
from app.template import FIELDS_BY_COLUMN, TEMPLATE_FIELDS, ddc_unit

router = APIRouter(prefix="/api", tags=["manual"])

RESULT_FIELDS = [f for f in TEMPLATE_FIELDS if f.group != "person"]
RESULT_COLUMNS = {f.column for f in RESULT_FIELDS}


class CheckupIn(BaseModel):
    round_id: int
    employee_id: int
    values: dict[str, object]
    comment: str | None = None


def _company_of_round(db: Session, b: CheckupBatch) -> int:
    return db.get(WalkthroughSurvey, b.survey_id).company_id


def _parse(column: str, raw):
    """-> value, or raises with a message naming the field. Never guesses."""
    field = FIELDS_BY_COLUMN[column]
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    if field.kind == "numeric":
        try:
            return Decimal(str(raw).strip())
        except (InvalidOperation, ValueError):
            raise HTTPException(400, {"message": f"{column}: “{raw}” ไม่ใช่ตัวเลข"})
    if field.kind == "categorical":
        # stored in the department's codes (D23): 0 = ปกติ, 1 = ผิดปกติ
        try:
            v = int(str(raw).strip())
        except ValueError:
            raise HTTPException(400, {"message": f"{column}: ต้องเป็น 0 (ปกติ) หรือ 1 (ผิดปกติ)"})
        if v not in (0, 1):
            raise HTTPException(400, {"message": f"{column}: ต้องเป็น 0 (ปกติ) หรือ 1 (ผิดปกติ)"})
        return v
    return str(raw).strip()


@router.get("/rounds/{round_id}/people")
def people_for_round(round_id: int, db: Session = Depends(get_db), user=Depends(require_user)):
    """Everyone in this workplace's register, and whether they already have a row."""
    b = db.get(CheckupBatch, round_id)
    if b is None:
        raise HTTPException(404, {"message": "ไม่พบรอบตรวจ"})
    company_id = _company_of_round(db, b)
    existing = {c.employee_id: c.id for c in db.query(EmployeeCheckup)
                .filter(EmployeeCheckup.checkup_batch_id == b.id)}
    rows = (db.query(Employee, Department)
            .join(Department, Department.id == Employee.department_pk)
            .filter(Department.company_id == company_id)
            .order_by(Employee.first_name, Employee.last_name).all())
    return [{"employee_id": e.id, "cid": e.cid,
             "name": " ".join(x for x in (e.first_name, e.last_name) if x) or e.cid,
             "department": d.name, "checkup_id": existing.get(e.id)}
            for e, d in rows]


@router.get("/checkups/fields")
def fields(user=Depends(require_user)):
    """The form's fields, with the unit the value is stored in (D23)."""
    return [{"column": f.column, "header": f.header, "kind": f.kind,
             "group": f.group, "unit": ddc_unit(f.column)} for f in RESULT_FIELDS]


@router.get("/checkups/{checkup_id}")
def get_checkup(checkup_id: int, db: Session = Depends(get_db), user=Depends(require_user)):
    c = db.get(EmployeeCheckup, checkup_id)
    if c is None:
        raise HTTPException(404, {"message": "ไม่พบผลตรวจ"})
    return c.to_dict()


@router.put("/checkups")
def save_checkup(body: CheckupIn, db: Session = Depends(get_db),
                 user: AppUser = Depends(require_user)):
    b = db.get(CheckupBatch, body.round_id)
    if b is None:
        raise HTTPException(404, {"message": "ไม่พบรอบตรวจ"})
    person = db.get(Employee, body.employee_id)
    if person is None:
        raise HTTPException(404, {"message": "ไม่พบพนักงานในทะเบียน"})
    dept = db.get(Department, person.department_pk)
    if dept.company_id != _company_of_round(db, b):
        # The register is per workplace; filing someone under another company's
        # round would put their results where nobody will look for them.
        raise HTTPException(400, {"message": "คนนี้ไม่ได้อยู่ในทะเบียนของสถานประกอบการในรอบนี้"})

    unknown = set(body.values) - RESULT_COLUMNS
    if unknown:
        raise HTTPException(400, {"message": f"ไม่รู้จักช่อง: {', '.join(sorted(unknown))}"})

    checkup = (db.query(EmployeeCheckup)
               .filter(EmployeeCheckup.employee_id == person.id,
                       EmployeeCheckup.checkup_batch_id == b.id).one_or_none())
    created = checkup is None
    if created:
        checkup = EmployeeCheckup(employee_id=person.id, checkup_batch_id=b.id)
        db.add(checkup)
        db.flush()

    changed = 0
    for column, raw in body.values.items():
        new = _parse(column, raw)
        old = getattr(checkup, column)
        if N.same_value(FIELDS_BY_COLUMN[column].kind, old, new):
            continue
        setattr(checkup, column, new)
        # A typed value has no file, sheet or cell to point at. The history row is
        # the only record of where it came from, so it is not optional.
        db.add(ValueHistory(checkup_id=checkup.id, column=column,
                            old_value=None if old is None else str(old),
                            new_value=None if new is None else str(new),
                            reason="manual_entry", changed_by=user.username))
        changed += 1

    if body.comment is not None and body.comment != (checkup.comment or ""):
        checkup.comment = body.comment or None
        changed += 1

    db.commit()
    db.refresh(checkup)
    return {"checkup_id": checkup.id, "created": created, "changed": changed}
