"""
Mapping Routes
==============
API endpoints for managing the HIS Lab name to Template mappings in the database.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc
from pydantic import BaseModel

from app.database import LabMapping, get_db

router = APIRouter(prefix="/api/mappings", tags=["mappings"])


class LabMappingCreate(BaseModel):
    his_lab_name: str
    template_column: str
    unit_factor: float = 1.0


@router.get("/")
def get_mappings(db: Session = Depends(get_db)):
    """ดึงข้อมูล mapping ทั้งหมด เรียงตามเวลาที่เพิ่มเข้ามา"""
    mappings = db.query(LabMapping).order_by(desc(LabMapping.created_at)).all()
    return [m.to_dict() for m in mappings]


@router.post("/")
def create_mapping(mapping: LabMappingCreate, db: Session = Depends(get_db)):
    """เพิ่มเงื่อนไข Mapping ใหม่"""
    his_lab_name = mapping.his_lab_name.lower().strip()
    
    # เช็คซ้ำ
    existing = db.query(LabMapping).filter(LabMapping.his_lab_name == his_lab_name).first()
    if existing:
        raise HTTPException(status_code=400, detail="ชื่อ Lab นี้ถูกแมปไปแล้ว")

    new_mapping = LabMapping(
        his_lab_name=his_lab_name,
        template_column=mapping.template_column,
        unit_factor=mapping.unit_factor
    )
    db.add(new_mapping)
    db.commit()
    db.refresh(new_mapping)
    
    return new_mapping.to_dict()


@router.delete("/{mapping_id}")
def delete_mapping(mapping_id: int, db: Session = Depends(get_db)):
    """ลบการแมปออก"""
    mapping = db.query(LabMapping).get(mapping_id)
    if not mapping:
        raise HTTPException(status_code=404, detail="ไม่พบการแมปนี้")
        
    db.delete(mapping)
    db.commit()
    return {"status": "deleted", "id": mapping_id}
