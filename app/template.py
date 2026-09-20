"""
template.py
===========
Single source of truth for the 45-column result template.

Everything that needs the template (DB model, export, validation, agents)
reads TEMPLATE_FIELDS. Order matches result_template_v1.1.xlsx.
"""

from dataclasses import dataclass
from decimal import Decimal
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
    # ILO scale e.g. "1/0" — text, not numeric. 50, not 10: the department's own
    # template writes "no profusion" in this column, which 10 could not hold.
    _t("profusion", "xray", 50),
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

# ---------------------------------------------------------------------------
# Storing in the department's form (D23)
# ---------------------------------------------------------------------------
# The pipeline keeps working in the canonical units above — every locked test
# set and every measured number depends on them. The conversion happens once, on
# the way into employee_checkups, and the value as the file wrote it stays in
# ValueProvenance.raw_value, so a wrong reading of the dictionary is reversible.

#: column -> (unit as the department stores it, factor from our canonical unit)
DDC_UNITS: dict[str, tuple[str, float]] = {
    "wbc": ("10^3/uL", 0.001),
    "plt": ("10^3/uL", 0.001),
}

#: categorical columns the dictionary documents as 0=ปกติ / 1=ผิดปกติ, while we
#: store 1=ปกติ / 2=ผิดปกติ. Note the department's own sample file uses 1/2 like
#: us — D23 chose to follow the written dictionary, and D23-ถาม has this as a
#: question to confirm before real data is sent.
DDC_ZERO_BASED = ("chest_xray", "ekg", "hearing_ability", "far_vision_test")

#: Columns the dictionary gives in a unit we cannot reach from ours by
#: arithmetic alone. rbc_che is U/g Hb there and U/L here, and going between
#: them needs that person's haemoglobin — a second measurement, which may be
#: missing, and whose own unit would have to be right too. Deriving it silently
#: would be exactly the kind of invented number this system exists to prevent,
#: so these are stored unconverted and listed for the department to confirm.
DDC_UNCONVERTIBLE = {"rbc_che": "U/g Hb ต้องใช้ค่า Hb ของคนคนนั้นมาหาร คำนวณเองไม่ได้"}


def ddc_value(column: str, value):
    """Our canonical value -> the form the department's table stores."""
    if value is None:
        return None
    if column in DDC_ZERO_BASED:
        return int(value) - 1          # 1/2 -> 0/1
    if column in DDC_UNITS:
        # Decimal, not float: 8383 * 0.001 in binary floating point is
        # 8.383000000000001, and that tail would travel all the way into the
        # file handed to the department.
        return (Decimal(str(value)) * Decimal(str(DDC_UNITS[column][1]))).normalize()
    return value


def ddc_unit(column: str) -> str | None:
    field = FIELDS_BY_COLUMN.get(column)
    if column in DDC_UNITS:
        return DDC_UNITS[column][0]
    return field.unit if field else None


# ---------------------------------------------------------------------------
# The employee registry (D23)
# ---------------------------------------------------------------------------
# A second, separate field set. The department keeps who a person is
# (`employees`) apart from what their results were (`employee_checkups`), and a
# HIS lab file never carries the registry fields. They arrive in their own file,
# through the same AI pipeline, mapped against this list instead.
#
# `header` is the department's own column name, so an export lands on their
# schema without a second translation.

REGISTRY_FIELDS: list[Field] = [
    Field("cid", "citizen_id", "id", "person", size=13),
    Field("first_name", "firstname", "text", "person", size=100),
    Field("last_name", "lastname", "text", "person", size=100),
    Field("title", "title", "text", "person", size=50),
    Field("department_id", "department_id", "text", "person", size=50),
    Field("gender", "gender", "text", "person", size=10),        # male / female
    Field("birth_year", "birth_year", "numeric", "person", precision=(4, 0), lo=2400, hi=2600),
    Field("nationality", "nationality", "text", "person", size=50),
    Field("position", "position", "text", "person", size=200),
    Field("work_experience", "work_experience", "numeric", "person", precision=(5, 2), lo=0, hi=70),
    Field("medical_condition", "medical_condition", "text", "person"),
]

REGISTRY_BY_COLUMN = {f.column: f for f in REGISTRY_FIELDS}

# Which field set a file is being read against. `pending_reviews.field_set` and
# the review screen both carry it, so a reviewer is never offered a lab column
# for a registry file or the other way round.
FIELD_SETS = {"result": TEMPLATE_FIELDS, "registry": REGISTRY_FIELDS}

FIELDS_BY_COLUMN = {f.column: f for f in TEMPLATE_FIELDS}
FIELDS_BY_HEADER = {f.header: f for f in TEMPLATE_FIELDS}
COLUMNS = [f.column for f in TEMPLATE_FIELDS]
HEADERS = [f.header for f in TEMPLATE_FIELDS]

# Result columns a lab/exam name can map to (excludes person/visit identity)
RESULT_COLUMNS = [f.column for f in TEMPLATE_FIELDS if f.group != "person"]

assert len(TEMPLATE_FIELDS) == 45
