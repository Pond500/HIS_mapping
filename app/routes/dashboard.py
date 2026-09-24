"""
Dashboard Routes
================
API endpoints for the monitoring dashboard.
"""

import io
from decimal import Decimal

import openpyxl
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, func, or_, text
from sqlalchemy.orm import Session

from app.auth import require_roles, require_user
from app.database import get_db
from app.models import (AgentDecision, CheckupBatch, Company, CompanyExtraColumn, Conflict,
                        Department, Employee, EmployeeCheckup, ExtraResult, LabMapping,
                        PendingReview, SourceFile, ValueHistory, ValueProvenance,
                        WalkthroughSurvey)
from app.template import COLUMNS, HEADERS

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/stats")
def get_stats(db: Session = Depends(get_db), user=Depends(require_user)):
    """สถิติรวมสำหรับ dashboard."""
    total = db.query(func.count(EmployeeCheckup.id)).scalar() or 0
    total_uploads = db.query(func.count(SourceFile.id)).scalar() or 0

    # 0 = ปกติ, 1 = ผิดปกติ in the department's schema (D23). These counts read the
    # stored form, so they must use the stored codes, not the template's 1/2.
    def counts(column):
        col = getattr(EmployeeCheckup, column)
        return {"normal": db.query(func.count(EmployeeCheckup.id)).filter(col == 0).scalar() or 0,
                "abnormal": db.query(func.count(EmployeeCheckup.id)).filter(col == 1).scalar() or 0}

    xray, ekg = counts("chest_xray"), counts("ekg")
    hearing, vision = counts("hearing_ability"), counts("far_vision_test")

    # Latest upload
    latest = db.query(SourceFile).order_by(desc(SourceFile.uploaded_at)).first()

    return {
        "total_employees": total,
        "total_uploads": total_uploads,
        "latest_upload": latest.to_dict() if latest else None,
        "abnormal_counts": {"xray": xray, "ekg": ekg, "hearing": hearing, "vision": vision},
        "total_abnormal": sum(c["abnormal"] for c in (xray, ekg, hearing, vision)),
    }


@router.get("/employees")
def get_employees(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    search: str = Query("", max_length=100),
    incomplete: bool = False,
    company_id: int | None = None,
    round_id: int | None = None,
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    """
    ดึงข้อมูลพนักงานแบบ paginated + search.

    Since D23 a row here is a person in the register, not a person-visit, and the
    count of their checkup rounds comes with them.

    `incomplete` lists the people whose registry fields the department requires but
    a lab file cannot supply. They are a queue to be filled from a register file,
    not damaged records, and their results are stored either way.

    `round_id` adds `checked_this_round` (CONTEXT.md "สถานะผลตรวจร่างกาย"): there
    are only two states today, ตรวจแล้ว and ไม่พบข้อมูล — no way yet for a person to
    be marked absent.
    """
    query = (db.query(Employee, Department, Company)
             .join(Department, Department.id == Employee.department_pk)
             .join(Company, Company.id == Department.company_id))
    if company_id is not None:
        query = query.filter(Company.id == company_id)
    if incomplete:
        missing = [getattr(Employee, c).is_(None) for c in Employee.REQUIRED_BY_DDC]
        query = query.filter(or_(*missing))

    if search:
        like = f"%{search}%"
        query = query.filter(
            (Employee.cid.ilike(like)) |
            (Employee.first_name.ilike(like)) |
            (Employee.last_name.ilike(like)) |
            (Department.name.ilike(like))
        )

    total = query.count()
    rows = (query.order_by(desc(Employee.created_at))
            .offset((page - 1) * per_page).limit(per_page).all())
    counts = dict(db.query(EmployeeCheckup.employee_id, func.count(EmployeeCheckup.id))
                  .group_by(EmployeeCheckup.employee_id).all())
    checked_round: set[int] = set()
    if round_id is not None:
        checked_round = {eid for (eid,) in db.query(EmployeeCheckup.employee_id)
                         .filter(EmployeeCheckup.checkup_batch_id == round_id)}

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page,
        "data": [{**e.to_dict(), "department": d.name, "company": c.name,
                  "company_id": c.id, "checkups": counts.get(e.id, 0),
                  **({"checked_this_round": e.id in checked_round} if round_id is not None else {})}
                 for e, d, c in rows],
    }


@router.get("/employees/{employee_id}")
def get_employee(employee_id: int, db: Session = Depends(get_db), user=Depends(require_user)):
    """One person: who they are, plus every round they have results for."""
    emp = db.get(Employee, employee_id)
    if not emp:
        return {"error": "ไม่พบข้อมูล"}
    dept = db.get(Department, emp.department_pk)
    company = db.get(Company, dept.company_id) if dept else None
    rounds = []
    for c in (db.query(EmployeeCheckup)
              .filter(EmployeeCheckup.employee_id == emp.id)
              .order_by(desc(EmployeeCheckup.id))):
        batch = db.get(CheckupBatch, c.checkup_batch_id)
        # ผลตรวจเพิ่มเติมของบริษัท (CONTEXT.md "คอลัมน์ของบริษัท") — only the named
        # ones; a legacy unnamed extra_results row (column_id NULL) has no place to
        # show a label, so it stays out of this person view same as before.
        extras = [{"name": col.name, "kind": col.kind, "unit": col.unit,
                   "value": float(x.value_num) if x.value_num is not None else x.value_text}
                 for x, col in (db.query(ExtraResult, CompanyExtraColumn)
                                .join(CompanyExtraColumn, CompanyExtraColumn.id == ExtraResult.column_id)
                                .filter(ExtraResult.checkup_id == c.id))]
        rounds.append({**c.to_dict(),
                       "appoint_date": batch.appoint_date.isoformat() if batch else None,
                       "is_approved": batch.is_approved if batch else False,
                       "extras": extras})
    return {**emp.to_dict(), "department": dept.name if dept else None,
            "company": company.name if company else None,
            "missing_registry_fields": [c for c in Employee.REQUIRED_BY_DDC
                                        if getattr(emp, c) is None],
            "rounds": rounds}


@router.get("/upload-logs")
def get_upload_logs(db: Session = Depends(get_db), user=Depends(require_user)):
    """ประวัติการ upload."""
    logs = db.query(SourceFile).order_by(desc(SourceFile.uploaded_at)).limit(50).all()
    return [l.to_dict() for l in logs]


@router.delete("/employees")
def delete_all_employees(db: Session = Depends(get_db),
                         user=Depends(require_roles("superadmin"))):
    """ลบข้อมูลผลตรวจและไฟล์ทั้งหมด (mapping และโรงพยาบาลยังอยู่)."""
    count = db.query(Employee).count()
    # The workplaces and their departments stay: they are a register someone typed
    # in, not data that came out of a file.
    db.execute(text("TRUNCATE employees, employee_checkups, source_files "
                    "RESTART IDENTITY CASCADE"))
    db.commit()
    return {"deleted": count}


@router.get("/export")
def export_excel(round_id: int | None = None, db: Session = Depends(get_db),
                 user=Depends(require_user)):
    """The 45-column template, rebuilt from the three tables.

    This is the working export, not the submission to the department (that is
    /api/summary/submit, which writes their own column names). It reads the same
    view that measurement will be switched back on through, so both describe one
    thing: v_employee_results_45.
    """
    sql = "SELECT * FROM v_employee_results_45"
    params = {}
    if round_id is not None:
        sql += " WHERE checkup_id IN (SELECT id FROM employee_checkups WHERE checkup_batch_id = :b)"
        params["b"] = round_id
    rows = db.execute(text(sql + " ORDER BY cid"), params).mappings().all()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Employees"

    for col_idx, h in enumerate(HEADERS, 1):
        ws.cell(row=1, column=col_idx, value=h)

    for row_idx, row in enumerate(rows, 2):
        for col_idx, field in enumerate(COLUMNS, 1):
            val = row.get(field)
            if field == "visit_date" and val:
                val = f"{val.year + 543}-{val.month:02d}-{val.day:02d}"   # ปี พ.ศ.
            elif isinstance(val, Decimal):
                val = float(val)
            ws.cell(row=row_idx, column=col_idx, value=val)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=export_result.xlsx"},
    )


def _blank_template(headers: list[str], sheet_title: str) -> StreamingResponse:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_title
    ws.append(headers)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{sheet_title}.xlsx"'})


@router.get("/registry/template")
def registry_template(user=Depends(require_user)):
    """A blank file with the register's own column names (Thai), for a hospital to
    fill in and upload back through /api/upload/registry. Headers only — the column
    order does not matter to the reader, which resolves labels by content, but a
    reviewer filling one in benefits from names they recognise."""
    from app.template import REGISTRY_FIELDS, REGISTRY_LABEL_TH
    headers = [REGISTRY_LABEL_TH.get(f.column, f.header) for f in REGISTRY_FIELDS]
    return _blank_template(headers, "ทะเบียนพนักงาน")


@router.get("/results/template")
def results_template(user=Depends(require_user)):
    """A blank file with the standard 45-column template's own headers."""
    return _blank_template(list(HEADERS), "ผลตรวจ")


AUTO_ORIGINS = ("seed", "agent_auto")          # mapping_id NULL = template/rule match, also automatic
HUMAN_ORIGINS = ("human", "agent_approved")


@router.get("/metrics")
def metrics(db: Session = Depends(get_db), user=Depends(require_user)):
    """
    Measured system numbers (D5). No assumed staff times here — the time-saving calculator on
    the page takes the agency's own numbers.

    automatic  cells stored through a rule, the dictionary or an AI mapping accepted on agreement
    assisted   cells stored through a mapping a reviewer approved or set
    waiting    cells still waiting for a reviewer (estimated from open reviews)
    """
    rows = (db.query(ValueProvenance.mapping_id, LabMapping.origin, func.count(ValueProvenance.id))
            .outerjoin(LabMapping, LabMapping.id == ValueProvenance.mapping_id)
            .group_by(ValueProvenance.mapping_id, LabMapping.origin).all())
    automatic = sum(n for mid, origin, n in rows if mid is None or origin in AUTO_ORIGINS)
    assisted = sum(n for mid, origin, n in rows if origin in HUMAN_ORIGINS)
    # a value a reviewer chose on the conflicts page was a human decision, whatever its mapping
    replaced = db.query(func.count(ValueHistory.id)).filter(ValueHistory.reason == "conflict_resolved").scalar()
    automatic, assisted = automatic - replaced, assisted + replaced
    waiting = 0
    for kind, payload in db.query(PendingReview.kind, PendingReview.payload).filter(PendingReview.status == "open"):
        waiting += int((payload or {}).get("count") or 0) if kind == "mapping" else 1
    files = db.query(SourceFile).filter(SourceFile.status != "failed").all()
    durations = [f.stats.get("duration_s") for f in files if (f.stats or {}).get("duration_s") is not None]
    cost = float(db.query(func.coalesce(func.sum(AgentDecision.cost_usd), 0)).scalar() or 0)
    decided = db.query(func.count(PendingReview.id)).filter(PendingReview.status != "open").scalar()
    total = automatic + assisted + waiting
    return {
        "files": len(files),
        "hospitals": len({f.hospital_id for f in files}),     # hospitals that actually sent files
        "people": db.query(func.count(Employee.id)).scalar(),
        "people_visits": db.query(func.count(EmployeeCheckup.id)).scalar(),
        "cells": {"automatic": automatic, "assisted": assisted, "waiting": waiting},
        "automation_rate": automatic / total if total else None,
        "open_reviews": db.query(func.count(PendingReview.id)).filter(PendingReview.status == "open").scalar(),
        "human_decisions": decided,
        "open_conflicts": db.query(func.count(Conflict.id)).filter(Conflict.status == "open").scalar(),
        "llm_calls": db.query(func.count(AgentDecision.id)).scalar(),
        "llm_cost_usd": round(cost, 4),
        "llm_cost_per_file_usd": round(cost / len(files), 4) if files else None,
        "avg_seconds_per_file": round(sum(durations) / len(durations), 1) if durations else None,
    }
