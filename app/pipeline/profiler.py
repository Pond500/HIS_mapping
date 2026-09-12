"""
profiler.py
===========
Works out where the table is in each sheet and what each column/row is.
Content first (a column of 13-digit numbers is the CID, whatever its header
says), header aliases second. A sheet it can't read produces "problems",
which become a profile review — never a silently skipped sheet.

The Profiler agent (week 2) produces the same SheetSpec for layouts these
rules can't handle.
"""

import re
from dataclasses import dataclass, field

from app.pipeline import normalize as N
from app.pipeline.reader import Sheet
from app.pipeline.units import norm_unit

# Header aliases: general Thai/English vocabulary for HIS exports
ALIASES = {
    "cid": ["cid", "pid", "idcard", "idcardno", "citizenid", "nationalid", "personalid", "เลขบัตรประชาชน",
            "เลขประจำตัวประชาชน", "เลขบัตร", "บัตรประชาชน", "เลขที่บัตร", "เลขบัตรปชช"],
    "full_name": ["fullname", "patientname", "name", "ชื่อนามสกุล", "ชื่อผู้รับบริการ", "ชื่อผู้ป่วย"],
    "first_name": ["fname", "firstname", "givenname", "ชื่อ", "ชื่อจริง"],
    "last_name": ["lname", "lastname", "surname", "familyname", "นามสกุล", "สกุล", "ชื่อสกุล"],
    "department_id": ["department", "departmentid", "dept", "deptid", "แผนก", "idแผนก", "หน่วยงาน", "ฝ่าย",
                      "section", "division", "สังกัด"],
    "visit_date": ["visitdate", "vstdate", "dateserv", "date", "servicedate", "examdate", "วันที่ตรวจ",
                   "วันที่รับบริการ", "วันที่", "วันตรวจ", "วันที่ตรวจปปปปดดวว"],
    "lab_name": ["labname", "labtest", "test", "testname", "item", "itemname", "รายการตรวจ", "รายการ",
                 "ชื่อการตรวจ", "investigation", "lab", "labitem"],
    "result": ["result", "labresult", "value", "ผล", "ผลตรวจ", "ผลการตรวจ", "ค่า", "ค่าที่ได้", "resultvalue"],
    "unit": ["unit", "units", "หน่วย", "หน่วยวัด"],
}
_ALIAS_OF = {a: role for role, al in ALIASES.items() for a in al}


def hkey(v) -> str:
    """Header key: lowercase, no spaces/punctuation."""
    return re.sub(r"[\s\-_./()\[\]:#]+", "", str(v).lower()) if v is not None else ""


def alias_role(v, id_aliases: dict | None = None) -> str | None:
    """id_aliases: {hkey(header): role} a hospital's reviewer confirmed earlier."""
    if not isinstance(v, str):
        return None
    if id_aliases and hkey(v) in id_aliases:
        return id_aliases[hkey(v)]
    raw = v.strip().lower()
    if re.fullmatch(r"ชื่อ\s*[-–/]\s*(นาม)?สกุล", raw):   # "ชื่อ-สกุล", "ชื่อ - นามสกุล" = full name
        return "full_name"
    return _ALIAS_OF.get(hkey(v))


def unit_like(v) -> bool:
    if not isinstance(v, str) or not v.strip() or len(v.strip()) > 15:
        return False
    u = norm_unit(v)
    return bool(re.search(r"[/%µ³^]|mmhg|^(g|l|m|cm|kg|bpm|u/l|iu/l|fl|pg)$", u))


@dataclass
class SheetSpec:
    sheet: str
    layout: str                                   # long | wide | transposed | skip
    header_row: int | None = None
    data_rows: list[int] = field(default_factory=list)
    id_cols: dict = field(default_factory=dict)   # role -> col (long/wide) or row (transposed)
    label_cols: dict = field(default_factory=dict)  # wide: col -> header text
    lab_col: int | None = None                    # long
    result_col: int | None = None
    unit_col: int | None = None
    unit_row: int | None = None                   # wide
    data_cols: list[int] = field(default_factory=list)   # transposed: one per person-visit
    label_rows: list[int] = field(default_factory=list)  # transposed
    problems: list[str] = field(default_factory=list)
    missing_roles: list[str] = field(default_factory=list)   # identity columns not found -> human
    candidates: list[dict] = field(default_factory=list)     # unrecognized text columns that may be them

    def to_dict(self):
        return self.__dict__.copy()


def _frac(vals, pred):
    vals = [v for v in vals if not N.is_na(v)]
    return (sum(1 for v in vals if pred(v)) / len(vals)) if vals else 0.0


def _col(rows, c, rs):
    return [rows[r][c] for r in rs]


def profile_sheet(sheet: Sheet, known_labels: set[str], id_aliases: dict | None = None) -> SheetSpec:
    rows = sheet.rows
    if not rows or sum(1 for r in rows if any(not N.is_na(v) for v in r)) < 2:
        return SheetSpec(sheet.name, "skip")
    t = _try_transposed(sheet, id_aliases)
    if t:
        return t

    width = len(rows[0])
    # CID column by content
    best_c, best_rows = None, []
    for c in range(width):
        rs = [r for r in range(len(rows)) if N.looks_like_cid(rows[r][c])]
        if len(rs) > len(best_rows):
            best_c, best_rows = c, rs
    if best_c is None or len(best_rows) < 1:
        nonempty = sum(1 for r in rows if sum(1 for v in r if not N.is_na(v)) >= 2)
        spec = SheetSpec(sheet.name, "skip")
        if nonempty >= 3:
            spec.problems.append(f"sheet '{sheet.name}': หาคอลัมน์เลขบัตรประชาชนไม่พบ")
        return spec

    first = best_rows[0]
    spec = SheetSpec(sheet.name, "wide")
    # unit row / header row just above the first data row
    r = first - 1
    if r >= 0 and _is_unit_row(rows[r]):
        spec.unit_row, r = r, r - 1
    while r >= 0 and sum(1 for v in rows[r] if not N.is_na(v)) < 2:
        r -= 1
    if r < 0:
        spec.problems.append(f"sheet '{sheet.name}': หาแถวหัวตารางไม่พบ")
        spec.layout = "skip"
        return spec
    spec.header_row = r
    header = rows[r]
    spec.data_rows = [i for i in range(first, len(rows)) if not N.is_na(rows[i][best_c])]

    # identity columns
    spec.id_cols["cid"] = best_c
    for c, h in enumerate(header):
        role = alias_role(h, id_aliases)
        if role and role != "cid" and role not in spec.id_cols and c != best_c:
            spec.id_cols[role] = c
    _fix_name_columns(spec, rows)
    if "visit_date" not in spec.id_cols or _frac(_col(rows, spec.id_cols["visit_date"], spec.data_rows[:50]),
                                                   N.looks_like_date) < 0.6:
        spec.id_cols.pop("visit_date", None)
        cands = [(c, _frac(_col(rows, c, spec.data_rows[:50]), N.looks_like_date)) for c in range(width)
                 if c not in spec.id_cols.values()]
        cands = [x for x in cands if x[1] >= 0.6]
        if cands:
            spec.id_cols["visit_date"] = max(cands, key=lambda x: x[1])[0]
        else:
            spec.problems.append(f"sheet '{sheet.name}': หาคอลัมน์วันที่ตรวจไม่พบ")

    # long or wide?
    lab_c = spec.id_cols.pop("lab_name", None)
    res_c = spec.id_cols.pop("result", None)
    unit_c = spec.id_cols.pop("unit", None)
    cids = [N.cid_digits(rows[i][best_c]) for i in spec.data_rows]
    rows_per_cid = len(cids) / max(1, len(set(cids)))
    if lab_c is None and rows_per_cid >= 3:
        lab_c = _guess_lab_col(rows, spec, known_labels)
    if lab_c is not None and rows_per_cid >= 1.5:
        spec.layout, spec.lab_col = "long", lab_c
        spec.result_col = res_c if res_c is not None else _guess_result_col(rows, spec, best_c)
        spec.unit_col = unit_c if unit_c is not None else _guess_unit_col(rows, spec)
        if spec.result_col is None:
            spec.problems.append(f"sheet '{sheet.name}': หาคอลัมน์ผลตรวจไม่พบ")
        _identity_gaps(spec, rows)
        return spec

    used = set(spec.id_cols.values())
    for c, h in enumerate(header):
        if c in used or N.is_na(h):
            continue
        spec.label_cols[c] = N.text(h)
    _identity_gaps(spec, rows)
    return spec


def _identity_gaps(spec: SheetSpec, rows):
    """Identity columns the rules couldn't find are reported (-> an "identity" review), never
    silently skipped. Unrecognized text columns are offered as candidates."""
    ids = spec.id_cols
    if "full_name" not in ids:
        spec.missing_roles += [r for r in ("first_name", "last_name") if r not in ids]
    if "department_id" not in ids:
        spec.missing_roles.append("department_id")
    if not spec.missing_roles or spec.layout == "transposed" or spec.header_row is None:
        return
    used = set(ids.values()) | {spec.lab_col, spec.result_col, spec.unit_col}
    for c, h in enumerate(rows[spec.header_row]):
        if c in used or N.is_na(h):
            continue
        vals = _col(rows, c, spec.data_rows[:50])
        if _frac(vals, lambda v: isinstance(v, str) and not _parses(v)) >= 0.6:
            spec.candidates.append({"header": N.text(h),
                                    "samples": [N.text(v) for v in vals if not N.is_na(v)][:3]})


def _is_unit_row(row) -> bool:
    if isinstance(row[0], str) and alias_role(row[0]) == "unit":
        return True
    vals = [v for v in row if not N.is_na(v)]
    return len(vals) >= 2 and not any(N.looks_like_cid(v) for v in vals) and \
        sum(1 for v in vals if unit_like(v)) / len(vals) >= 0.6


def _fix_name_columns(spec, rows):
    """A 'name' column whose values are mostly 'first last' is a full-name column."""
    for role in ("first_name", "last_name", "full_name"):
        c = spec.id_cols.get(role)
        if c is None:
            continue
        spaced = _frac(_col(rows, c, spec.data_rows[:50]), lambda v: isinstance(v, str) and " " in v.strip())
        if spaced >= 0.6 and role != "full_name" and "full_name" not in spec.id_cols:
            spec.id_cols["full_name"] = spec.id_cols.pop(role)
        elif spaced < 0.2 and role == "full_name":
            # a "name" header holding single words: treat as first name
            spec.id_cols.setdefault("first_name", spec.id_cols.pop("full_name"))


def _varies_within_person(rows, spec, c, cid_c):
    seen = {}
    for i in spec.data_rows[:400]:
        seen.setdefault(N.cid_digits(rows[i][cid_c]), set()).add(str(rows[i][c]))
    return sum(1 for s in seen.values() if len(s) > 1) / max(1, len(seen))


def _guess_lab_col(rows, spec, known_labels):
    used = set(spec.id_cols.values())
    best, best_score = None, 0.0
    for c in range(len(rows[0])):
        if c in used:
            continue
        vals = _col(rows, c, spec.data_rows[:400])
        if _frac(vals, lambda v: isinstance(v, str) and not re.fullmatch(r"[\d.,\s]+", v)) < 0.8:
            continue
        known = _frac(vals, lambda v: N.text(v).lower() in known_labels)
        varies = _varies_within_person(rows, spec, c, spec.id_cols["cid"])
        score = known * 2 + varies
        if score > best_score:
            best, best_score = c, score
    return best if best_score >= 0.5 else None


def _guess_result_col(rows, spec, cid_c):
    used = set(spec.id_cols.values()) | {spec.lab_col}
    best, best_score = None, 0.0
    for c in range(len(rows[0])):
        if c in used:
            continue
        vals = _col(rows, c, spec.data_rows[:400])
        numeric = _frac(vals, lambda v: _parses(v))
        score = numeric + _varies_within_person(rows, spec, c, cid_c)
        if score > best_score:
            best, best_score = c, score
    return best if best_score >= 1.0 else None


def _parses(v):
    try:
        N.parse_number(v)
        return True
    except N.Unparseable:
        return False


def _guess_unit_col(rows, spec):
    used = set(spec.id_cols.values()) | {spec.lab_col, spec.result_col}
    for c in range(len(rows[0])):
        if c not in used and _frac(_col(rows, c, spec.data_rows[:400]), unit_like) >= 0.7:
            return c
    return None


def _try_transposed(sheet: Sheet, id_aliases: dict | None = None) -> SheetSpec | None:
    rows = sheet.rows
    for r in range(min(30, len(rows))):
        cells = rows[r][1:]
        hits = [c + 1 for c, v in enumerate(cells) if N.looks_like_cid(v)]
        nonempty = [v for v in cells if not N.is_na(v)]
        if len(hits) >= 2 and len(hits) >= 0.6 * len(nonempty):
            spec = SheetSpec(sheet.name, "transposed", header_row=r, data_cols=hits)
            spec.id_cols["cid"] = r
            # identity rows: label in column 0, near the CID row
            last_id = r
            for rr in range(max(0, r - 10), min(len(rows), r + 12)):
                role = alias_role(rows[rr][0], id_aliases)
                if role in ("full_name", "first_name", "last_name", "department_id", "visit_date") \
                        and role not in spec.id_cols:
                    spec.id_cols[role] = rr
                    last_id = max(last_id, rr)
            if "visit_date" not in spec.id_cols:
                for rr in range(r + 1, min(len(rows), r + 12)):
                    if _frac([rows[rr][c] for c in hits], N.looks_like_date) >= 0.6:
                        spec.id_cols["visit_date"] = rr
                        last_id = max(last_id, rr)
                        break
            if "visit_date" not in spec.id_cols:
                spec.problems.append(f"sheet '{sheet.name}': หาแถววันที่ตรวจไม่พบ")
            for role in ("full_name", "first_name"):
                rr = spec.id_cols.get(role)
                if rr is not None and _frac([rows[rr][c] for c in hits],
                                            lambda v: isinstance(v, str) and " " in v.strip()) >= 0.6:
                    spec.id_cols.pop(role)
                    spec.id_cols["full_name"] = rr
            start = last_id + 1
            if start < len(rows) and alias_role(rows[start][0]) == "lab_name":
                if len(rows[start]) > 1 and alias_role(rows[start][1]) == "unit":
                    spec.unit_col = 1
                start += 1
            spec.label_rows = [i for i in range(start, len(rows)) if not N.is_na(rows[i][0])]
            if spec.unit_col is None and _frac([rows[i][1] for i in spec.label_rows], unit_like) >= 0.5:
                spec.unit_col = 1
            _identity_gaps(spec, rows)
            return spec
    return None
