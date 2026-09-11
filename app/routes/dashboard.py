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

from app.database import get_db
from app.models import Employee, SourceFile
from app.template import COLUMNS, HEADERS

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/stats")
def get_stats(db: Session = Depends(get_db)):
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
    db: Session = Depends(get_db),
):
    """ดึงข้อมูลพนักงานแบบ paginated + search."""
    query = db.query(Employee)

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
def get_employee(employee_id: int, db: Session = Depends(get_db)):
    """ดูรายละเอียดพนักงานรายคน."""
    emp = db.get(Employee, employee_id)
    if not emp:
        return {"error": "ไม่พบข้อมูล"}
    return emp.to_dict()


@router.get("/upload-logs")
def get_upload_logs(db: Session = Depends(get_db)):
    """ประวัติการ upload."""
    logs = db.query(SourceFile).order_by(desc(SourceFile.uploaded_at)).limit(50).all()
    return [l.to_dict() for l in logs]


@router.delete("/employees")
def delete_all_employees(db: Session = Depends(get_db)):
    """ลบข้อมูลผลตรวจและไฟล์ทั้งหมด (mapping และโรงพยาบาลยังอยู่)."""
    count = db.query(Employee).count()
    db.execute(text("TRUNCATE employees, source_files RESTART IDENTITY CASCADE"))
    db.commit()
    return {"deleted": count}


@router.get("/export")
def export_excel(db: Session = Depends(get_db)):
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
