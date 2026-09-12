"""
mapper.py
=========
Resolves a label (lab name in a long file, header in a wide file) to a
template column, extra result, or "ignore" — exact matches only, hospital
layer first, then the central dictionary (D6). No fuzzy matching: an
unknown label is a review item, and the Mapper agent (week 2) proposes it.
"""

import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import TARGET_EXTRA, TARGET_IGNORE, LabMapping
from app.pipeline import units as U
from app.pipeline.profiler import unit_like
from app.template import FIELDS_BY_COLUMN, RESULT_COLUMNS

TARGET_BP = "__bp__"          # "120/80" -> bp_systolic + bp_diastolic
BP_LABELS = {"bp", "blood pressure", "ความดันโลหิต", "ความดัน", "bp (mmhg)"}
TEMPLATE_NAMES = {c: c for c in RESULT_COLUMNS}   # a file using the template's own names
# mappings learned for a specific (label, unit) store the complete factor in unit_factor
LEARNED_ORIGINS = {"human", "agent_approved", "agent_auto"}
IDENTITY_PREFIX = "__id:"     # target_column "__id:first_name" = a hospital's confirmed identity header


@dataclass
class _TemplateName:
    """Stands in for a LabMapping row when the label is a template column name."""
    target_column: str
    id: int | None = None
    source_unit: str | None = None
    unit_factor: float = 1.0
    origin: str = "rule"


def norm_label(s) -> str:
    return re.sub(r"\s+", " ", str(s)).strip().lower()


def split_unit(label: str) -> tuple[str, str | None]:
    """'Hb (g/L)' -> ('Hb', 'g/L'). Only strips a trailing (...) that looks like a unit."""
    m = re.fullmatch(r"(.*?)\s*[\(\[]\s*([^()\[\]]+?)\s*[\)\]]\s*", label)
    if m and (unit_like(m.group(2)) or m.group(2).strip().lower().startswith("%")):
        return m.group(1), m.group(2)
    return label, None


@dataclass
class Resolution:
    target: str | None          # template column, __bp__, __extra__, __ignore__, or None = unresolved
    factor: float = 1.0
    unit: str | None = None
    source: str | None = None   # hospital / central / rule
    mapping_id: int | None = None
    reason: str | None = None   # why unresolved (shown to the reviewer)
    suggestion: str | None = None


class Mapper:
    def __init__(self, db: Session, hospital_id: int | None):
        self.hospital, self.central, self.identity = {}, {}, {}
        q = db.query(LabMapping).filter((LabMapping.hospital_id == hospital_id) | LabMapping.hospital_id.is_(None))
        for m in q:
            if m.target_column.startswith(IDENTITY_PREFIX):
                if m.hospital_id is not None:
                    self.identity[m.source_name] = m.target_column[len(IDENTITY_PREFIX):]
                continue
            layer = self.central if m.hospital_id is None else self.hospital
            layer[(m.source_name, (m.source_unit or "").lower() or None)] = m

    def identity_aliases(self) -> dict:
        """{hkey(header): role} confirmed by this hospital's reviewers (see profiler.alias_role)."""
        return dict(self.identity)

    def known_labels(self) -> set[str]:
        return {k[0] for k in list(self.central) + list(self.hospital)}

    def _lookup(self, name: str, unit: str | None):
        """Hospital layer, then the template's own column names, then the central dictionary."""
        m = self.hospital.get((name, (unit or "").lower() or None)) or self.hospital.get((name, None))
        if m:
            return m, "hospital"
        if name in TEMPLATE_NAMES:
            return _TemplateName(TEMPLATE_NAMES[name]), "rule"
        m = self.central.get((name, (unit or "").lower() or None)) or self.central.get((name, None))
        if m:
            return m, "central"
        return None, None

    def resolve(self, label, unit_hint: str | None = None) -> Resolution:
        full = norm_label(label)
        base, hdr_unit = split_unit(str(label).strip())
        base = norm_label(base)
        unit = unit_hint or hdr_unit

        if full in BP_LABELS or base in BP_LABELS:
            return Resolution(TARGET_BP, 1.0, unit, "rule")

        m, src = self._lookup(full, unit)
        if not m and base != full:
            m, src = self._lookup(base, unit)
        if not m:
            return Resolution(None, unit=unit, reason="ไม่พบชื่อนี้ในพจนานุกรม")

        target = m.target_column
        if target in (TARGET_EXTRA, TARGET_IGNORE):
            return Resolution(target, 1.0, unit, src, m.id)
        if m.origin in LEARNED_ORIGINS:
            return Resolution(target, float(m.unit_factor), unit, src, m.id)
        if m.source_unit and unit and m.source_unit.lower() == (unit or "").lower():
            return Resolution(target, float(m.unit_factor), unit, src, m.id)   # approved unit-specific mapping
        f = U.factor(target, unit) if FIELDS_BY_COLUMN[target].kind == "numeric" else 1.0
        if f is None:
            return Resolution(None, unit=unit, reason=f"หน่วย '{unit}' ไม่ตรงกับคอลัมน์ {target}",
                              suggestion=target)
        return Resolution(target, f * float(m.unit_factor or 1), unit, src, m.id)
