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


def _n(col, group, precision=(10, 2)):
    return Field(col, col, "numeric", group, precision=precision)


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
    _n("venous_blood_lead", "toxicology"),
    _n("wbc", "cbc"),
    _n("hb", "cbc"),
    _n("hct", "cbc"),
    _n("plt", "cbc", (12, 2)),
    _n("neutrophil", "cbc"),
    _n("lymphocyte", "cbc"),
    _n("monocyte", "cbc"),
    _n("eosinophil", "cbc"),
    _n("basophil", "cbc"),
    _n("creatinine", "kidney"),
    _n("sgot_ast", "liver"),
    _n("sgpt_alt", "liver"),
    _n("alp", "liver"),
    _n("tb", "liver"),
    _n("db", "liver"),
    _n("uric_acid", "metabolic"),
    _c("chest_xray", "xray"),
    _t("xray_comment", "xray"),
    _t("profusion", "xray", 10),  # ILO scale e.g. "1/0" — text, not numeric
    _t("primary_lesion", "xray", 20),
    _t("secondary_lesion", "xray", 20),
    _n("rbc_che", "cholinesterase", (12, 2)),
    _n("plasma_che_bche", "cholinesterase", (12, 2)),
    _c("ekg", "ekg"),
    _t("ekg_comment", "ekg"),
    _n("bmi", "vitals"),
    _n("bp_systolic", "vitals"),
    _n("bp_diastolic", "vitals"),
    _n("pulse_rate", "vitals"),
    _n("spirometry_fvc_percent", "spirometry"),
    _n("spirometry_fev1_percent", "spirometry"),
    _n("spirometry_fvc", "spirometry"),
    _n("spirometry_fev1", "spirometry"),
    _n("spirometry_fev1_fvc", "spirometry"),
    _n("spirometry_height", "spirometry"),
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
