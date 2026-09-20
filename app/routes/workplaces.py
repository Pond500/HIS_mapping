"""
workplaces.py
=============
ทะเบียนสถานประกอบการ — the workplaces whose employees get checked, and the
departments inside them (D23).

This is a shared national register, not one per hospital: the department keys a
company by (juristic_id, branch_name), and the same factory may be served by
several hospitals. That also means a member of staff at one hospital can see the
client list of another — see D20-หนี้, which this widens and which has to be
closed before real data.

    GET    /api/companies                      the register, with department counts
    POST   /api/companies                      add one
    PATCH  /api/companies/{id}                 edit one
    GET    /api/companies/{id}/departments
    POST   /api/companies/{id}/departments     add a department
    DELETE /api/departments/{id}               only while nothing points at it
"""

import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import require_user
from app.database import get_db
from app.models import Company, Department, Employee

router = APIRouter(prefix="/api", tags=["workplaces"])


class CompanyIn(BaseModel):
    juristic_id: str
    name: str
    branch_name: str = ""
    fid: str | None = None
    address: str | None = None
    industry_group: str | None = None
    industry_group_code: str | None = None
    employee_numbers: int | None = None

    @field_validator("juristic_id")
    @classmethod
    def _thirteen_digits(cls, v: str) -> str:
        v = re.sub(r"\D", "", v or "")
        if len(v) != 13:
            raise ValueError("เลขนิติบุคคลต้องเป็นตัวเลข 13 หลัก")
        return v

    @field_validator("name")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not (v or "").strip():
            raise ValueError("ต้องระบุชื่อสถานประกอบการ")
        return v.strip()


class CompanyPatch(BaseModel):
    name: str | None = None
    branch_name: str | None = None
    fid: str | None = None
    address: str | None = None
    industry_group: str | None = None
    industry_group_code: str | None = None
    employee_numbers: int | None = None


class DepartmentIn(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not (v or "").strip():
            raise ValueError("ต้องระบุชื่อแผนก")
        return v.strip()


def _company_dict(c: Company, departments: int = 0, people: int = 0) -> dict:
    return {"id": c.id, "juristic_id": c.juristic_id, "fid": c.fid, "name": c.name,
            "branch_name": c.branch_name, "address": c.address,
            "industry_group": c.industry_group, "industry_group_code": c.industry_group_code,
            "employee_numbers": c.employee_numbers,
            "departments": departments, "people": people,
            "created_at": c.created_at.isoformat() if c.created_at else None}


@router.get("/companies")
def list_companies(search: str | None = None, db: Session = Depends(get_db),
                   user=Depends(require_user)):
    dept_counts = dict(db.query(Department.company_id, func.count(Department.id))
                       .group_by(Department.company_id).all())
    people_counts = dict(db.query(Department.company_id, func.count(Employee.id))
                         .join(Employee, Employee.department_pk == Department.id)
                         .group_by(Department.company_id).all())
    q = db.query(Company)
    if search:
        like = f"%{search.strip()}%"
        q = q.filter((Company.name.ilike(like)) | (Company.juristic_id.ilike(like))
                     | (Company.branch_name.ilike(like)))
    return [_company_dict(c, dept_counts.get(c.id, 0), people_counts.get(c.id, 0))
            for c in q.order_by(Company.name, Company.branch_name)]


@router.post("/companies", status_code=201)
def add_company(body: CompanyIn, db: Session = Depends(get_db), user=Depends(require_user)):
    branch = (body.branch_name or "").strip()
    dup = (db.query(Company)
           .filter(Company.juristic_id == body.juristic_id, Company.branch_name == branch)
           .one_or_none())
    if dup is not None:
        # The department's own unique key. Saying so plainly beats a 500 from the
        # constraint, and beats quietly creating a second copy of one workplace.
        raise HTTPException(409, f"มีสถานประกอบการนี้อยู่แล้ว: {dup.name} "
                                 f"({dup.branch_name or 'สำนักงานใหญ่'})")
    c = Company(**{**body.model_dump(), "branch_name": branch})
    db.add(c)
    db.commit()
    return _company_dict(c)


@router.patch("/companies/{company_id}")
def edit_company(company_id: int, body: CompanyPatch, db: Session = Depends(get_db),
                 user=Depends(require_user)):
    c = db.get(Company, company_id)
    if c is None:
        raise HTTPException(404, "ไม่พบสถานประกอบการ")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(c, k, v)
    db.commit()
    return _company_dict(c)


@router.get("/companies/{company_id}/departments")
def list_departments(company_id: int, db: Session = Depends(get_db), user=Depends(require_user)):
    if db.get(Company, company_id) is None:
        raise HTTPException(404, "ไม่พบสถานประกอบการ")
    counts = dict(db.query(Employee.department_pk, func.count(Employee.id))
                  .group_by(Employee.department_pk).all())
    return [{"id": d.id, "name": d.name, "people": counts.get(d.id, 0)}
            for d in db.query(Department).filter(Department.company_id == company_id)
                       .order_by(Department.name)]


@router.post("/companies/{company_id}/departments", status_code=201)
def add_department(company_id: int, body: DepartmentIn, db: Session = Depends(get_db),
                   user=Depends(require_user)):
    if db.get(Company, company_id) is None:
        raise HTTPException(404, "ไม่พบสถานประกอบการ")
    dup = (db.query(Department)
           .filter(Department.company_id == company_id, Department.name == body.name)
           .one_or_none())
    if dup is not None:
        raise HTTPException(409, f"มีแผนก “{body.name}” อยู่แล้ว")
    d = Department(name=body.name, company_id=company_id)
    db.add(d)
    db.commit()
    return {"id": d.id, "name": d.name, "people": 0}


@router.delete("/departments/{department_id}")
def remove_department(department_id: int, db: Session = Depends(get_db),
                      user=Depends(require_user)):
    d = db.get(Department, department_id)
    if d is None:
        raise HTTPException(404, "ไม่พบแผนก")
    people = db.query(func.count(Employee.id)).filter(Employee.department_pk == d.id).scalar()
    if people:
        # Deleting would cascade into their results. A department with people in
        # it is renamed or left alone, never removed from under them.
        raise HTTPException(409, f"ลบไม่ได้: มีพนักงาน {people} คนอยู่ในแผนกนี้")
    db.delete(d)
    db.commit()
    return {"deleted": department_id}
