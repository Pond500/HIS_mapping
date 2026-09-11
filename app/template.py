"""
template.py
===========
Single source of truth for the 45-column result template.

Everything that needs the template (DB model, export, validation, agents)
reads TEMPLATE_FIELDS. Order matches result_template_v1.1.xlsx.
"""

from dataclasses import dataclass
from typing import Literal

Kind = Literal["id", "text", "date", "numeric", "categorical"]


@dataclass(frozen=True)
class Field:
    column: str          # DB column name (English)
    header: str          # column header in the template file
    kind: Kind
    group: str
    size: int | None = None        # String length for text fields
    precision: tuple[int, int] = (10, 2)  # Numeric(p, s) for numeric fields
    unit: str | None = None        # canonical unit stored in the DB
    # plausible adult range in the canonical unit (not the normal range):
    # values outside it are almost surely a unit or mapping error
    lo: float | None = None
    hi: float | None = None


def _n(col, group, unit, lo, hi, precision=(10, 2)):
    return Field(col, col, "numeric", group, precision=precision, unit=unit, lo=lo, hi=hi)


def _t(col, group, size=None):
    return Field(col, col, "text", group, size=size)


def _c(col, group):
    # 1 = ปกติ/เหมาะสม, 2 = ผิดปกติ/อาจไม่เหมาะสม
    return Field(col, col, "categorical", group)


TEMPLATE_FIELDS: list[Field] = [
    Field("cid", "เลขบัตรประชาชน", "id", "person", size=13),
    Field("first_name", "ชื่อ", "text", "person", size=100),
    Field("last_name", "นามสกุล", "text", "person", size=100),
    Field("department_id", "ID แผนก", "text", "person", size=50),
    Field("visit_date", "วันที่ตรวจ (ปปปป-ดด-วว)", "date", "person"),
    _n("venous_blood_lead", "toxicology", "µg/dL", 0, 150),
    _n("wbc", "cbc", "cells/µL", 1000, 50000),
    _n("hb", "cbc", "g/dL", 4, 22),
    _n("hct", "cbc", "%", 12, 65),
    _n("plt", "cbc", "cells/µL", 10000, 1500000, (12, 2)),
    _n("neutrophil", "cbc", "%", 0, 100),
    _n("lymphocyte", "cbc", "%", 0, 100),
    _n("monocyte", "cbc", "%", 0, 100),
    _n("eosinophil", "cbc", "%", 0, 100),
    _n("basophil", "cbc", "%", 0, 100),
    _n("creatinine", "kidney", "mg/dL", 0.1, 15),
    _n("sgot_ast", "liver", "U/L", 1, 2000),
    _n("sgpt_alt", "liver", "U/L", 1, 2000),
    _n("alp", "liver", "U/L", 10, 2000),
    _n("tb", "liver", "mg/dL", 0, 30),
    _n("db", "liver", "mg/dL", 0, 20),
    _n("uric_acid", "metabolic", "mg/dL", 0.5, 20),
    _c("chest_xray", "xray"),
    _t("xray_comment", "xray"),
    _t("profusion", "xray", 10),  # ILO scale e.g. "1/0" — text, not numeric
    _t("primary_lesion", "xray", 20),
    _t("secondary_lesion", "xray", 20),
    _n("rbc_che", "cholinesterase", "U/L", 1000, 20000, (12, 2)),
    _n("plasma_che_bche", "cholinesterase", "U/L", 1000, 20000, (12, 2)),
    _c("ekg", "ekg"),
    _t("ekg_comment", "ekg"),
    _n("bmi", "vitals", "kg/m²", 10, 70),
    _n("bp_systolic", "vitals", "mmHg", 60, 260),
    _n("bp_diastolic", "vitals", "mmHg", 30, 160),
    _n("pulse_rate", "vitals", "bpm", 30, 220),
    _n("spirometry_fvc_percent", "spirometry", "% predicted", 10, 160),
    _n("spirometry_fev1_percent", "spirometry", "% predicted", 10, 160),
    _n("spirometry_fvc", "spirometry", "L", 0.5, 8),
    _n("spirometry_fev1", "spirometry", "L", 0.3, 7),
    _n("spirometry_fev1_fvc", "spirometry", "%", 20, 100),
    _n("spirometry_height", "spirometry", "cm", 120, 210),
    _c("hearing_ability", "hearing"),
    _t("hearing_comment", "hearing"),
    _c("far_vision_test", "vision"),
    _t("far_vision_comment", "vision"),
]

FIELDS_BY_COLUMN = {f.column: f for f in TEMPLATE_FIELDS}
FIELDS_BY_HEADER = {f.header: f for f in TEMPLATE_FIELDS}
COLUMNS = [f.column for f in TEMPLATE_FIELDS]
HEADERS = [f.header for f in TEMPLATE_FIELDS]

# Result columns a lab/exam name can map to (excludes person/visit identity)
RESULT_COLUMNS = [f.column for f in TEMPLATE_FIELDS if f.group != "person"]

assert len(TEMPLATE_FIELDS) == 45
