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

from app.models import (
    TARGET_EXTRA, TARGET_EXTRA_COL_PREFIX, TARGET_IGNORE, CompanyColumnAlias, CompanyExtraColumn,
    LabMapping,
)
from app.pipeline import units as U
from app.pipeline.profiler import unit_like
from app.template import FIELDS_BY_COLUMN, RESULT_COLUMNS

TARGET_BP = "__bp__"          # "120/80" -> bp_systolic + bp_diastolic
BP_LABELS = {"bp", "blood pressure", "ความดันโลหิต", "ความดัน", "bp (mmhg)"}
TEMPLATE_NAMES = {c: c for c in RESULT_COLUMNS}   # a file using the template's own names
# mappings learned for a specific (label, unit) store the complete factor in unit_factor
LEARNED_ORIGINS = {"human", "agent_approved", "agent_auto"}
IDENTITY_PREFIX = "__id:"     # target_column "__id:first_name" = a hospital's confirmed identity header
DEPT_PREFIX = "__dept:"       # target_column "__dept:QC" = this hospital's department name -> code (D18)


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
    target: str | None          # template column, __bp__, __extra__, __ignore__, __extracol:N, or None = unresolved
    factor: float = 1.0
    unit: str | None = None
    source: str | None = None   # hospital / central / rule / company
    mapping_id: int | None = None
    reason: str | None = None   # why unresolved (shown to the reviewer)
    suggestion: str | None = None
    # set only when the label matches a company column by name but this file's unit
    # doesn't match the unit that column was first defined with (CONTEXT.md "คอลัมน์ของ
    # บริษัท"): a question for a human, never a silent mix of two units under one name.
    company_column_conflict: dict | None = None


class Mapper:
    def __init__(self, db: Session, hospital_id: int | None, company_id: int | None = None):
        self.hospital, self.central, self.identity, self.dept = {}, {}, {}, {}
        q = db.query(LabMapping).filter((LabMapping.hospital_id == hospital_id) | LabMapping.hospital_id.is_(None))
        for m in q:
            if m.target_column.startswith(IDENTITY_PREFIX):
                if m.hospital_id is not None:
                    self.identity[m.source_name] = m.target_column[len(IDENTITY_PREFIX):]
                continue
            if m.target_column.startswith(DEPT_PREFIX):
                if m.hospital_id is not None:
                    self.dept[m.source_name] = m.target_column[len(DEPT_PREFIX):]
                continue
            layer = self.central if m.hospital_id is None else self.hospital
            layer[(m.source_name, (m.source_unit or "").lower() or None)] = m
        # a company's own columns (CONTEXT.md): shared by every hospital that serves
        # that company, same as its register of departments and employees already is.
        # Keyed like `self.hospital` (source_name, source_unit) -> column, via aliases
        # so a differently-spelled label a reviewer picked for an existing column
        # ("Fe serum" for "ค่าเหล็กในเลือด") resolves to it again automatically too.
        self.company_id = company_id
        self.company: dict[tuple[str, str | None], CompanyExtraColumn] = {}
        self.company_names: dict[str, CompanyExtraColumn] = {}
        if company_id is not None:
            cols = {c.id: c for c in
                   db.query(CompanyExtraColumn).filter(CompanyExtraColumn.company_id == company_id)}
            for c in cols.values():
                self.company_names[norm_label(c.name)] = c
            for a in db.query(CompanyColumnAlias).filter(CompanyColumnAlias.company_id == company_id):
                col = cols.get(a.column_id)
                if col:
                    self.company[(a.source_name, (a.source_unit or "").lower() or None)] = col

    def dept_code(self, name) -> str | None:
        return self.dept.get(norm_label(name))

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
        # an old nameless "__extra__" mapping, in a company's file: the company column
        # it should be is the company's answer, not the hospital's (CONTEXT.md)
        legacy_extra = bool(m) and m.target_column == TARGET_EXTRA and self.company_id is not None
        if not m or legacy_extra:
            unit_key = (unit or "").lower() or None
            aliased = (self.company.get((full, unit_key)) or self.company.get((full, None))
                      or (self.company.get((base, unit_key)) or self.company.get((base, None))
                          if base != full else None))
            if aliased:
                # a person already answered for exactly this label (and, with the unit,
                # accepted it) — asking again would never end
                return Resolution(f"{TARGET_EXTRA_COL_PREFIX}{aliased.id}", 1.0, unit, "company")
            col = self.company_names.get(full) or (self.company_names.get(base) if base != full else None)
            if col:
                col_unit = (col.unit or "").lower() or None
                file_unit = (unit or "").lower() or None
                if col.kind == "text" or col_unit == file_unit:
                    return Resolution(f"{TARGET_EXTRA_COL_PREFIX}{col.id}", 1.0, unit, "company")
                return Resolution(None, unit=unit,
                                  reason=f"เคยตั้งคอลัมน์ “{col.name}” ของบริษัทนี้ไว้ด้วยหน่วย "
                                         f"{col.unit or '(ไม่ระบุ)'} แต่ไฟล์นี้เขียนหน่วย {unit or '(ไม่ระบุ)'} — ไม่ตรงกัน",
                                  company_column_conflict={"id": col.id, "name": col.name, "unit": col.unit})
            if legacy_extra:
                return Resolution(None, unit=unit,
                                  reason="เคยเก็บเป็นผลตรวจนอกแบบฟอร์มแบบไม่มีชื่อ — "
                                         "ตอนนี้ต้องตั้งเป็นคอลัมน์ของบริษัทนี้ก่อน")
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
