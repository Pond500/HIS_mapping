"""
registry.py
===========
นำเข้าทะเบียนพนักงาน (D23).

A register file is a different animal from a lab file. A lab file says
"this measurement, for this person"; a register file says "this is who the
person is". There are no units, no long/wide question, no plausible ranges —
just one row per person and a header to understand.

So this is its own small pipeline rather than a setting on the other one:

    read -> find the header row -> match each header to a registry field
         -> one Employee per row, or a review

What it keeps from the main pipeline, because these are the parts that matter:
  * exact matching only. An unrecognised header is a review, never a guess.
  * what a hospital's reviewer answers is remembered, as a LabMapping with
    target "__reg:<column>", so the same file next month needs no answers.
  * a CID that fails its checksum stops that row and says so.
  * nothing is overwritten silently: a changed value is a Conflict-shaped
    question, here surfaced as a review, and the stored value stands.

The AI mapper proposes header meanings exactly as it does for lab labels; the
proposals arrive through `evidence` and are shown with the review.
"""

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models import Department, Employee, LabMapping
from app.pipeline import normalize as N
from app.pipeline.mapper import norm_label
from app.template import REGISTRY_BY_COLUMN, REGISTRY_FIELDS, REGISTRY_LABEL_TH

REG_PREFIX = "__reg:"          # a learned header -> registry column, per hospital
REG_IGNORE = "__ignore__"      # ...or a header this hospital has said is not register data

#: Header spellings we accept without asking. Deliberately short: anything not
#: here becomes a question, which is how a wrong guess is avoided.
ALIASES: dict[str, str] = {}
for _col, _names in {
    "cid": ["cid", "citizen_id", "เลขบัตรประชาชน", "เลขประจำตัวประชาชน", "รหัสบัตรประชาชน",
            "เลขบัตร", "id card", "national id"],
    "first_name": ["first_name", "firstname", "ชื่อ", "ชื่อจริง", "name"],
    "last_name": ["last_name", "lastname", "นามสกุล", "surname"],
    "title": ["title", "คำนำหน้า", "คำนำหน้าชื่อ"],
    # "ชื่อแผนก" and "ID แผนก" both appear in the department's own register template,
    # with the name filled in and the id column left empty.
    "department_id": ["department", "department_id", "แผนก", "ฝ่าย", "หน่วยงาน", "แผนกงาน",
                      "ชื่อแผนก", "id แผนก", "รหัสแผนก"],
    "gender": ["gender", "sex", "เพศ"],
    "birth_year": ["birth_year", "ปีเกิด", "ปีเกิด (พ.ศ.)", "พ.ศ. เกิด"],
    "nationality": ["nationality", "สัญชาติ"],
    "position": ["position", "ตำแหน่ง", "ตำแหน่งงาน", "หน้าที่"],
    "work_experience": ["work_experience", "อายุงาน", "ประสบการณ์", "อายุงาน (ปี)", "ประสบการณ์ทำงาน"],
    "medical_condition": ["medical_condition", "โรคประจำตัว", "ประวัติสุขภาพ", "โรคประจำตัว/ประวัติ"],
}.items():
    for _n in _names:
        ALIASES[norm_label(_n)] = _col

GENDER = {"ชาย": "male", "หญิง": "female", "ช": "male", "ญ": "female",
          "m": "male", "f": "female", "male": "male", "female": "female",
          "นาย": "male", "นาง": "female", "นางสาว": "female"}


@dataclass
class RegistryResult:
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    reviews: list = field(default_factory=list)
    rows_read: int = 0

    def as_stats(self) -> dict:
        return {"added": self.added, "updated": self.updated, "unchanged": self.unchanged,
                "rows": self.rows_read, "reviews": len(self.reviews)}


def learned_headers(db: Session, hospital_id: int) -> dict[str, str]:
    """Answers this hospital has already given, keyed the way source_name is
    stored: normalised, so the same header in different case or spacing matches."""
    return {m.source_name: m.target_column[len(REG_PREFIX):]
            for m in db.query(LabMapping)
                       .filter(LabMapping.hospital_id == hospital_id,
                               LabMapping.target_column.like(f"{REG_PREFIX}%"))}


def find_header_row(rows: list[list]) -> int | None:
    """The first row where at least two headers are recognised. Two, not one,
    because a single match is as likely to be a stray word in a title."""
    for i, row in enumerate(rows[:20]):
        hits = sum(1 for v in row if N.text(v) and norm_label(N.text(v)) in ALIASES)
        if hits >= 2:
            return i
    return None


def _parse(column: str, raw):
    """-> (value, None) or (None, reason). Never guesses."""
    text = N.text(raw)
    if text is None:
        return None, None
    if column == "cid":
        d = N.cid_digits(text)
        if not N.cid_valid(d):
            return None, "เลขบัตรประชาชนไม่ถูกต้อง (checksum ไม่ผ่านหรือไม่ครบ 13 หลัก)"
        return d, None
    if column in ("first_name", "last_name"):
        try:
            return N.clean_name(text), None
        except N.Unparseable as e:
            return None, str(e)
    if column == "gender":
        g = GENDER.get(text.strip().lower())
        # The department's column is an enum of exactly male/female. Anything else
        # is left for a person rather than forced into one of the two.
        return (g, None) if g else (None, f"ไม่รู้จักค่าเพศ “{text}” (ต้องเป็น ชาย/หญิง)")
    if column in ("birth_year", "work_experience"):
        value, _ = N.parse_number(text)
        if value is None:
            return None, f"อ่านเป็นตัวเลขไม่ได้: “{text}”"
        if column == "birth_year":
            year = int(value)
            if year < 2300:            # a CE year in a column the department keeps in BE
                year += 543
            if not (2400 <= year <= 2600):
                return None, f"ปีเกิดอยู่นอกช่วงที่เป็นไปได้: “{text}”"
            return year, None
        if not (0 <= value <= 70):
            return None, f"อายุงานอยู่นอกช่วงที่เป็นไปได้: “{text}” ปี"
        return value, None
    return text, None


def import_registry(db: Session, sheets, hospital_id: int, company_id: int,
                    source_file_id: int | None = None,
                    evidence: dict | None = None) -> RegistryResult:
    """Reads a register file into `employees` for one workplace."""
    res = RegistryResult()
    evidence = evidence or {}
    learned = learned_headers(db, hospital_id)
    departments = {d.name: d.id for d in db.query(Department).filter(Department.company_id == company_id)}

    sheet = next((s for s in sheets if find_header_row(s.rows) is not None), None)
    if sheet is None:
        res.reviews.append({"kind": "profile", "payload": {
            "sheet": sheets[0].name if sheets else "?",
            "problem": "หาแถวหัวตารางของไฟล์ทะเบียนไม่พบ — ต้องมีคอลัมน์ที่ระบบรู้จักอย่างน้อย 2 คอลัมน์ "
                       "เช่น เลขบัตรประชาชน และ ชื่อ"}})
        return res

    head = find_header_row(sheet.rows)
    headers = [N.text(v) for v in sheet.rows[head]]
    columns: dict[int, str] = {}
    unknown: list[str] = []
    for i, h in enumerate(headers):
        if h is None:
            continue
        key = norm_label(h)
        col = learned.get(key) or ALIASES.get(key)
        if col == REG_IGNORE:
            continue                  # someone has already said this column is not register data
        if col:
            columns[i] = col
        else:
            unknown.append(h)

    for h in unknown:
        payload = {"label": h, "sheet": sheet.name, "field_set": "registry",
                   "targets": [f.column for f in REGISTRY_FIELDS],
                   "reason": f"ไม่รู้จักคอลัมน์ “{h}” ในไฟล์ทะเบียนพนักงาน"}
        if h in evidence:
            payload["proposal"] = evidence[h]
        res.reviews.append({"kind": "mapping", "payload": payload})

    if "cid" not in columns.values():
        res.reviews.append({"kind": "identity", "payload": {
            "sheet": sheet.name, "missing": ["cid"], "candidates": [{"header": h} for h in headers if h],
            "field_set": "registry",
            "reason": "ไม่พบคอลัมน์เลขบัตรประชาชน — ทะเบียนพนักงานต้องมีเลขบัตรเพื่อผูกกับผลตรวจ"}})
        return res

    seen_bad, asked_departments = set(), set()
    for r in range(head + 1, len(sheet.rows)):
        row = sheet.rows[r]
        if all(N.is_na(v) for v in row):
            continue
        res.rows_read += 1

        values, problems = {}, []
        for i, col in columns.items():
            value, reason = _parse(col, row[i] if i < len(row) else None)
            if reason:
                problems.append((col, N.text(row[i]), reason))
            elif value is not None:
                values[col] = value

        cid = values.get("cid")
        if cid is None:
            for col, raw, reason in problems:
                if col == "cid" and raw not in seen_bad:
                    seen_bad.add(raw)
                    res.reviews.append({"kind": "cid", "payload": {
                        "raw_cid": raw, "sheet": sheet.name, "row": r + 1,
                        "field_set": "registry", "reason": reason}})
            continue

        dept_name = values.pop("department_id", None)
        if not dept_name:
            # Its own kind, not `identity`: identity asks "which column holds this",
            # and there is no column to pick — the row itself is blank. Nobody can
            # answer that from the review screen, so it must not look answerable.
            res.reviews.append({"kind": "row_missing_department", "payload": {
                "cid": cid, "sheet": sheet.name, "row": r + 1, "field_set": "registry",
                "reason": "แถวนี้ไม่มีแผนก — ทะเบียนของกรมฯ ผูกคนกับแผนก จึงบันทึกไม่ได้"}})
            continue
        if dept_name not in departments:
            if dept_name in asked_departments:
                continue          # one question per department, not one per person in it
            asked_departments.add(dept_name)
            # A department is a row owned by the workplace (D23). Creating one from a
            # spelling in a file would quietly invent an organisational unit, so a
            # person says whether this is a real department or a misspelling.
            res.reviews.append({"kind": "unknown_department", "payload": {
                "cid": cid, "department_in_file": dept_name,
                "known_departments": sorted(departments), "field_set": "registry",
                "reason": f"ไม่มีแผนก “{dept_name}” ในสถานประกอบการนี้"}})
            continue
        dept_id = departments[dept_name]

        for col, raw, reason in problems:
            if col != "cid":
                res.reviews.append({"kind": "value", "payload": {
                    "cid": cid, "column": col, "raw": raw, "sheet": sheet.name,
                    "row": r + 1, "field_set": "registry", "reason": reason}})

        person = (db.query(Employee)
                  .filter(Employee.cid == cid, Employee.department_pk == dept_id).one_or_none())
        if person is None:
            person = Employee(cid=cid, department_pk=dept_id, source_file_id=source_file_id)
            for col, value in values.items():
                if col != "cid":
                    setattr(person, col, value)
            db.add(person)
            res.added += 1
            continue

        changed = False
        for col, value in values.items():
            if col == "cid":
                continue
            current = getattr(person, col)
            if current is None:
                setattr(person, col, value)
                changed = True
            elif not N.same_value(REGISTRY_BY_COLUMN[col].kind, current, value):
                # The stored value stands; the difference becomes a question (D13).
                # Its own kind, because unlike the other `value` reviews this one IS
                # answerable: both values are in front of the reviewer and the answer
                # is which of the two the register should hold.
                res.reviews.append({"kind": "registry_value", "payload": {
                    "cid": cid, "employee_id": person.id, "column": col,
                    "header": REGISTRY_LABEL_TH.get(col, col),
                    "raw": str(value), "current": str(current),
                    "sheet": sheet.name, "row": r + 1, "field_set": "registry",
                    "reason": f"ทะเบียนเดิมมี “{current}” แต่ไฟล์นี้เขียนว่า “{value}” "
                              f"— ค่าเดิมยังอยู่จนกว่าจะมีคนตัดสิน"}})
        if changed:
            res.updated += 1
        else:
            res.unchanged += 1

    return res
