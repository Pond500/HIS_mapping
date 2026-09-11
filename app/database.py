"""
database.py
===========
PostgreSQL connection + SQLAlchemy models
"""

import os
from datetime import datetime

from dotenv import load_dotenv
from sqlalchemy import (
    Column, DateTime, Integer, Numeric, SmallInteger, String, Text,
    create_engine
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# ---------------------------------------------------------------------------
# Database URL
# ---------------------------------------------------------------------------

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]  # set in .env (see .env.example)

engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class Employee(Base):
    __tablename__ = "employees"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # ข้อมูลส่วนตัว
    cid = Column(String(13), nullable=False)
    first_name = Column(String(100))
    last_name = Column(String(100))
    department_id = Column(String(50))
    visit_date = Column(DateTime)

    # Toxicology
    venous_blood_lead = Column(Numeric(10, 2))

    # CBC
    wbc = Column(Numeric(10, 2))
    hb = Column(Numeric(10, 2))
    hct = Column(Numeric(10, 2))
    plt = Column(Numeric(12, 2))
    neutrophil = Column(Numeric(10, 2))
    lymphocyte = Column(Numeric(10, 2))
    monocyte = Column(Numeric(10, 2))
    eosinophil = Column(Numeric(10, 2))
    basophil = Column(Numeric(10, 2))

    # Kidney
    creatinine = Column(Numeric(10, 2))

    # Liver
    sgot_ast = Column(Numeric(10, 2))
    sgpt_alt = Column(Numeric(10, 2))
    alp = Column(Numeric(10, 2))
    tb = Column(Numeric(10, 2))
    db = Column(Numeric(10, 2))

    # Metabolic
    uric_acid = Column(Numeric(10, 2))

    # X-ray
    chest_xray = Column(SmallInteger)
    xray_comment = Column(Text)
    profusion = Column(Numeric(10, 2))
    primary_lesion = Column(String(20))
    secondary_lesion = Column(String(20))

    # Cholinesterase
    rbc_che = Column(Numeric(12, 2))
    plasma_che_bche = Column(Numeric(12, 2))

    # EKG
    ekg = Column(SmallInteger)
    ekg_comment = Column(Text)

    # Vital signs
    bmi = Column(Numeric(10, 2))
    bp_systolic = Column(Numeric(10, 2))
    bp_diastolic = Column(Numeric(10, 2))
    pulse_rate = Column(Numeric(10, 2))

    # Spirometry
    spirometry_fvc_percent = Column(Numeric(10, 2))
    spirometry_fev1_percent = Column(Numeric(10, 2))
    spirometry_fvc = Column(Numeric(10, 2))
    spirometry_fev1 = Column(Numeric(10, 2))
    spirometry_fev1_fvc = Column(Numeric(10, 2))
    spirometry_height = Column(Numeric(10, 2))

    # Hearing
    hearing_ability = Column(SmallInteger)
    hearing_comment = Column(Text)

    # Vision
    far_vision_test = Column(SmallInteger)
    far_vision_comment = Column(Text)

    # Metadata
    upload_id = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "cid": self.cid,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "department_id": self.department_id,
            "visit_date": self.visit_date.strftime("%Y-%m-%d") if self.visit_date else None,
            "venous_blood_lead": float(self.venous_blood_lead) if self.venous_blood_lead else None,
            "wbc": float(self.wbc) if self.wbc else None,
            "hb": float(self.hb) if self.hb else None,
            "hct": float(self.hct) if self.hct else None,
            "plt": float(self.plt) if self.plt else None,
            "neutrophil": float(self.neutrophil) if self.neutrophil else None,
            "lymphocyte": float(self.lymphocyte) if self.lymphocyte else None,
            "monocyte": float(self.monocyte) if self.monocyte else None,
            "eosinophil": float(self.eosinophil) if self.eosinophil else None,
            "basophil": float(self.basophil) if self.basophil else None,
            "creatinine": float(self.creatinine) if self.creatinine else None,
            "sgot_ast": float(self.sgot_ast) if self.sgot_ast else None,
            "sgpt_alt": float(self.sgpt_alt) if self.sgpt_alt else None,
            "alp": float(self.alp) if self.alp else None,
            "tb": float(self.tb) if self.tb else None,
            "db": float(self.db) if self.db else None,
            "uric_acid": float(self.uric_acid) if self.uric_acid else None,
            "chest_xray": self.chest_xray,
            "xray_comment": self.xray_comment,
            "profusion": float(self.profusion) if self.profusion else None,
            "primary_lesion": self.primary_lesion,
            "secondary_lesion": self.secondary_lesion,
            "rbc_che": float(self.rbc_che) if self.rbc_che else None,
            "plasma_che_bche": float(self.plasma_che_bche) if self.plasma_che_bche else None,
            "ekg": self.ekg,
            "ekg_comment": self.ekg_comment,
            "bmi": float(self.bmi) if self.bmi else None,
            "bp_systolic": float(self.bp_systolic) if self.bp_systolic else None,
            "bp_diastolic": float(self.bp_diastolic) if self.bp_diastolic else None,
            "pulse_rate": float(self.pulse_rate) if self.pulse_rate else None,
            "spirometry_fvc_percent": float(self.spirometry_fvc_percent) if self.spirometry_fvc_percent else None,
            "spirometry_fev1_percent": float(self.spirometry_fev1_percent) if self.spirometry_fev1_percent else None,
            "spirometry_fvc": float(self.spirometry_fvc) if self.spirometry_fvc else None,
            "spirometry_fev1": float(self.spirometry_fev1) if self.spirometry_fev1 else None,
            "spirometry_fev1_fvc": float(self.spirometry_fev1_fvc) if self.spirometry_fev1_fvc else None,
            "spirometry_height": float(self.spirometry_height) if self.spirometry_height else None,
            "hearing_ability": self.hearing_ability,
            "hearing_comment": self.hearing_comment,
            "far_vision_test": self.far_vision_test,
            "far_vision_comment": self.far_vision_comment,
            "upload_id": self.upload_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class UploadLog(Base):
    __tablename__ = "upload_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    filename = Column(String(500), nullable=False)
    file_type = Column(String(10))
    total_rows = Column(Integer, default=0)
    success_rows = Column(Integer, default=0)
    error_rows = Column(Integer, default=0)
    errors = Column(Text)
    status = Column(String(20), default="processing")
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "filename": self.filename,
            "file_type": self.file_type,
            "total_rows": self.total_rows,
            "success_rows": self.success_rows,
            "error_rows": self.error_rows,
            "errors": self.errors,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class LabMapping(Base):
    __tablename__ = "lab_mappings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    his_lab_name = Column(String(200), unique=True, nullable=False)
    template_column = Column(String(100), nullable=False)
    unit_factor = Column(Numeric(10, 4), default=1.0)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "his_lab_name": self.his_lab_name,
            "template_column": self.template_column,
            "unit_factor": float(self.unit_factor) if self.unit_factor else 1.0,
        }


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(bind=engine)
    
    # Auto-seed the database
    db = SessionLocal()
    try:
        if db.query(LabMapping).count() == 0:
            import sys
            import os
            
            # Use original mapping inside config
            sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
            from mapping_config import LAB_NAME_TO_TEMPLATE
            
            mappings = []
            for lab_name, template_col in LAB_NAME_TO_TEMPLATE.items():
                mappings.append(LabMapping(
                    his_lab_name=lab_name.lower().strip(),
                    template_column=template_col,
                    unit_factor=1.0
                ))
            db.bulk_save_objects(mappings)
            db.commit()
            print(f"🌱 Seeded {len(mappings)} LabMappings to database.")
    except Exception as e:
        db.rollback()
        print(f"Error seeding db: {e}")
    finally:
        db.close()
