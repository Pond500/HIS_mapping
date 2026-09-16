"""
Dashboard Routes
================
API endpoints for the monitoring dashboard.
"""

import io
from datetime import datetime

import openpyxl
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, func, text
from sqlalchemy.orm import Session

from app.auth import require_roles, require_user
from app.database import get_db
from app.models import (AgentDecision, Conflict, Employee, LabMapping, PendingReview, SourceFile, ValueHistory,
                        ValueProvenance)
from app.template import COLUMNS, HEADERS

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/stats")
def get_stats(db: Session = Depends(get_db), user=Depends(require_user)):
    """สถิติรวมสำหรับ dashboard."""
    total = db.query(func.count(Employee.id)).scalar() or 0
    total_uploads = db.query(func.count(SourceFile.id)).scalar() or 0

    # Count abnormal results
    xray_abnormal = db.query(func.count(Employee.id)).filter(Employee.chest_xray == 2).scalar() or 0
    ekg_abnormal = db.query(func.count(Employee.id)).filter(Employee.ekg == 2).scalar() or 0
    hearing_abnormal = db.query(func.count(Employee.id)).filter(Employee.hearing_ability == 2).scalar() or 0
    vision_abnormal = db.query(func.count(Employee.id)).filter(Employee.far_vision_test == 2).scalar() or 0

    # Count normal results
    xray_normal = db.query(func.count(Employee.id)).filter(Employee.chest_xray == 1).scalar() or 0
    ekg_normal = db.query(func.count(Employee.id)).filter(Employee.ekg == 1).scalar() or 0
    hearing_normal = db.query(func.count(Employee.id)).filter(Employee.hearing_ability == 1).scalar() or 0
    vision_normal = db.query(func.count(Employee.id)).filter(Employee.far_vision_test == 1).scalar() or 0

    # Latest upload
    latest = db.query(SourceFile).order_by(desc(SourceFile.uploaded_at)).first()

    return {
        "total_employees": total,
        "total_uploads": total_uploads,
        "latest_upload": latest.to_dict() if latest else None,
        "abnormal_counts": {
            "xray": {"normal": xray_normal, "abnormal": xray_abnormal},
            "ekg": {"normal": ekg_normal, "abnormal": ekg_abnormal},
            "hearing": {"normal": hearing_normal, "abnormal": hearing_abnormal},
            "vision": {"normal": vision_normal, "abnormal": vision_abnormal},
        },
        "total_abnormal": xray_abnormal + ekg_abnormal + hearing_abnormal + vision_abnormal,
    }


@router.get("/employees")
def get_employees(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    search: str = Query("", max_length=100),
    missing_name: bool = False,
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    """
    ดึงข้อมูลพนักงานแบบ paginated + search.

    `missing_name` lists the people whose results are stored but whose name column
    the profiler could not find: the answer is waiting as an `identity` review, and
    re-running the file fills the names into these same rows (store.py fills blanks
    only). They are a queue, not damaged records.
    """
    query = db.query(Employee)
    if missing_name:
        query = query.filter(Employee.first_name.is_(None), Employee.last_name.is_(None))

    if search:
        query = query.filter(
            (Employee.cid.ilike(f"%{search}%")) |
            (Employee.first_name.ilike(f"%{search}%")) |
            (Employee.last_name.ilike(f"%{search}%")) |
            (Employee.department_id.ilike(f"%{search}%"))
        )

    total = query.count()
    employees = (
        query.order_by(desc(Employee.created_at))
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page,
        "data": [e.to_dict() for e in employees],
    }


@router.get("/employees/{employee_id}")
def get_employee(employee_id: int, db: Session = Depends(get_db), user=Depends(require_user)):
    """ดูรายละเอียดพนักงานรายคน."""
    emp = db.get(Employee, employee_id)
    if not emp:
        return {"error": "ไม่พบข้อมูล"}
    return emp.to_dict()


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
    db.execute(text("TRUNCATE employees, source_files RESTART IDENTITY CASCADE"))
    db.commit()
    return {"deleted": count}


@router.get("/export")
def export_excel(db: Session = Depends(get_db), user=Depends(require_user)):
    """Export ข้อมูลทั้งหมดเป็น Excel."""
    employees = db.query(Employee).order_by(Employee.cid).all()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Employees"

    headers = HEADERS
    db_fields = COLUMNS

    for col_idx, h in enumerate(headers, 1):
        ws.cell(row=1, column=col_idx, value=h)

    for row_idx, emp in enumerate(employees, 2):
        d = emp.to_dict()
        for col_idx, field in enumerate(db_fields, 1):
            val = d.get(field)
            if field == "visit_date" and val:
                # Convert to Buddhist Era
                try:
                    dt = datetime.strptime(val, "%Y-%m-%d")
                    val = f"{dt.year + 543}-{dt.month:02d}-{dt.day:02d}"
                except Exception:
                    pass
            ws.cell(row=row_idx, column=col_idx, value=val)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=export_result.xlsx"},
    )


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
        "people_visits": db.query(func.count(Employee.id)).scalar(),
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
