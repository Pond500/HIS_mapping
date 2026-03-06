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
from sqlalchemy import func, desc
from sqlalchemy.orm import Session

from app.database import Employee, UploadLog, get_db

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/stats")
def get_stats(db: Session = Depends(get_db)):
    """สถิติรวมสำหรับ dashboard."""
    total = db.query(func.count(Employee.id)).scalar() or 0
    total_uploads = db.query(func.count(UploadLog.id)).scalar() or 0

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
    latest = db.query(UploadLog).order_by(desc(UploadLog.created_at)).first()

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
    emp = db.query(Employee).get(employee_id)
    if not emp:
        return {"error": "ไม่พบข้อมูล"}
    return emp.to_dict()


@router.get("/upload-logs")
def get_upload_logs(db: Session = Depends(get_db)):
    """ประวัติการ upload."""
    logs = db.query(UploadLog).order_by(desc(UploadLog.created_at)).limit(50).all()
    return [l.to_dict() for l in logs]


@router.delete("/employees")
def delete_all_employees(db: Session = Depends(get_db)):
    """ลบข้อมูลทั้งหมด."""
    count = db.query(Employee).delete()
    db.query(UploadLog).delete()
    db.commit()
    return {"deleted": count}


@router.get("/export")
def export_excel(db: Session = Depends(get_db)):
    """Export ข้อมูลทั้งหมดเป็น Excel."""
    employees = db.query(Employee).order_by(Employee.cid).all()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Employees"

    headers = [
        "เลขบัตรประชาชน", "ชื่อ", "นามสกุล", "ID แผนก", "วันที่ตรวจ (ปปปป-ดด-วว)",
        "venous_blood_lead", "wbc", "hb", "hct", "plt",
        "neutrophil", "lymphocyte", "monocyte", "eosinophil", "basophil",
        "creatinine", "sgot_ast", "sgpt_alt", "alp", "tb", "db",
        "uric_acid", "chest_xray", "xray_comment", "profusion",
        "primary_lesion", "secondary_lesion", "rbc_che", "plasma_che_bche",
        "ekg", "ekg_comment", "bmi", "bp_systolic", "bp_diastolic", "pulse_rate",
        "spirometry_fvc_percent", "spirometry_fev1_percent",
        "spirometry_fvc", "spirometry_fev1", "spirometry_fev1_fvc", "spirometry_height",
        "hearing_ability", "hearing_comment", "far_vision_test", "far_vision_comment",
    ]
    db_fields = [
        "cid", "first_name", "last_name", "department_id", "visit_date",
        "venous_blood_lead", "wbc", "hb", "hct", "plt",
        "neutrophil", "lymphocyte", "monocyte", "eosinophil", "basophil",
        "creatinine", "sgot_ast", "sgpt_alt", "alp", "tb", "db",
        "uric_acid", "chest_xray", "xray_comment", "profusion",
        "primary_lesion", "secondary_lesion", "rbc_che", "plasma_che_bche",
        "ekg", "ekg_comment", "bmi", "bp_systolic", "bp_diastolic", "pulse_rate",
        "spirometry_fvc_percent", "spirometry_fev1_percent",
        "spirometry_fvc", "spirometry_fev1", "spirometry_fev1_fvc", "spirometry_height",
        "hearing_ability", "hearing_comment", "far_vision_test", "far_vision_comment",
    ]

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
