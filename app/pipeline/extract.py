"""
extract.py
==========
Sheets + specs + mapper -> clean cells, extras and review items.

Every cell either becomes a clean canonical value, or a review item that
says exactly what a human must decide (docs/requirements.md "กฎเหล็ก").
"""

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from app.models import TARGET_EXTRA, TARGET_EXTRA_COL_PREFIX, TARGET_IGNORE
from app.pipeline import normalize as N
from app.pipeline.mapper import TARGET_BP, Mapper, Resolution
from app.pipeline.profiler import SheetSpec
from app.pipeline.reader import Sheet
from app.pipeline.units import factor as unit_factor
from app.template import FIELDS_BY_COLUMN

COMMENT_OF = {"chest_xray": "xray_comment", "ekg": "ekg_comment",
              "hearing_ability": "hearing_comment", "far_vision_test": "far_vision_comment"}
ROLE_TH = {"first_name": "ชื่อ", "last_name": "นามสกุล", "full_name": "ชื่อ-สกุล", "department_id": "แผนก"}
RANGE_FLAG_SHARE = 0.2      # this share of a label's values out of range => the mapping/unit is suspect
SAMPLES = 6


@dataclass
class Obs:
    sheet: str
    cell: str
    ident: dict                 # raw cid / visit_date / names / department
    label: str
    unit: str | None
    raw: object


@dataclass
class Extraction:
    rows: dict = field(default_factory=dict)     # (cid, date_iso) -> {"person": {}, "cells": {col: (value, prov)}}
    extras: list = field(default_factory=list)
    reviews: list = field(default_factory=list)  # {"kind", "payload"}
    stats: Counter = field(default_factory=Counter)


# ---------------------------------------------------------------------------
# Observations from each layout
# ---------------------------------------------------------------------------


def observations(sheet: Sheet, spec: SheetSpec):
    rows = sheet.rows
    if spec.layout in ("long", "wide"):
        for r in spec.data_rows:
            row = rows[r]
            ident = {role: row[c] for role, c in spec.id_cols.items()}
            if spec.report_date:
                ident.setdefault("visit_date", spec.report_date)
            if spec.layout == "long":
                if spec.result_col is None or N.is_na(row[spec.lab_col]):
                    continue
                unit = row[spec.unit_col] if spec.unit_col is not None else None
                yield Obs(sheet.name, sheet.cell_ref(r, spec.result_col), ident, N.text(row[spec.lab_col]),
                          N.text(unit), row[spec.result_col])
            else:
                for c, label in spec.label_cols.items():
                    unit = rows[spec.unit_row][c] if spec.unit_row is not None else None
                    yield Obs(sheet.name, sheet.cell_ref(r, c), ident, label, N.text(unit), row[c])
    elif spec.layout == "transposed":
        for c in spec.data_cols:
            ident = {role: rows[r][c] for role, r in spec.id_cols.items()}
            if spec.report_date:
                ident.setdefault("visit_date", spec.report_date)
            for r in spec.label_rows:
                unit = rows[r][spec.unit_col] if spec.unit_col is not None else None
                yield Obs(sheet.name, sheet.cell_ref(r, c), ident, N.text(rows[r][0]), N.text(unit), rows[r][c])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def extract(sheets: list[Sheet], specs: list[SheetSpec], mapper: Mapper,
            evidence: dict | None = None, comment_labels: dict | None = None,
            comment_evidence: dict | None = None, round_date: str | None = None) -> Extraction:
    """
    evidence:         {(label, unit): {...}} from the agents, attached to mapping reviews
    comment_labels:   {(category column, norm_comment(text)): 1|2} learned meanings of findings
    comment_evidence: {(category column, norm_comment(text)): {...}} attached to comment reviews
    round_date:       the checkup round's appoint_date, ISO (D23). The department keeps
                      the date on the round, so a file with no date column is normal
                      rather than unreadable. A date written in the file still wins:
                      this is only the fallback, and it is never guessed — it comes
                      from what the person picked in the upload dialog.
    """
    ex = Extraction()
    id_headers = set()
    for spec in specs:
        for p in spec.problems:
            # Same reason as the missing-role filter below: when the round carries
            # the date, a file without a date column is the normal case, not a
            # problem to report (D23).
            if round_date is not None and "วันที่ตรวจไม่พบ" in p:
                continue
            ex.reviews.append({"kind": "profile", "payload": {"sheet": spec.sheet, "problem": p}})
        # Two roles a results file is not supposed to carry once a round is chosen
        # (D23), so asking a reviewer to find them is asking for a column that is not
        # there. The date comes from the round. The department comes from the register:
        # a results file only gets to disagree with it, and saying nothing is not a
        # disagreement. Left in, the question offered whatever text column happened to
        # be in the file — on the department's own files, the chest X-ray finding.
        # The name is the same story: it lives in the register. A results file without
        # a name column is normal (just an id and values), and asking for one offered the
        # reviewer whatever text column was nearby. An unregistered person's name is asked
        # for on that person's own question, where it is actually needed.
        skip_roles = ({"visit_date", "department_id", "first_name", "last_name", "full_name"}
                      if round_date is not None else set())
        missing = [r for r in spec.missing_roles if r not in skip_roles]
        if spec.layout != "skip" and missing:
            ex.reviews.append({"kind": "identity", "payload": {
                "sheet": spec.sheet, "missing": missing, "candidates": spec.candidates,
                "reason": "หาคอลัมน์ " + ", ".join(ROLE_TH.get(r, r) for r in missing)
                          + " ไม่พบ — ช่วยเลือกคอลัมน์ที่ถูกต้อง"}})
            id_headers |= {c["header"] for c in spec.candidates}

    # 1. read every observation, resolve its label once
    resolutions: dict[tuple, Resolution] = {}
    obs_by_label = defaultdict(list)
    for sheet, spec in zip(sheets, specs):
        if spec.layout == "skip" or ("visit_date" in spec.missing_roles and round_date is None):
            continue   # no visit date yet: the sheet waits for its "identity" review, row by row noise helps no one
        for o in observations(sheet, spec):
            if o.label is None:
                continue
            key = (o.label, o.unit)
            if key not in resolutions:
                resolutions[key] = mapper.resolve(o.label, o.unit)
            obs_by_label[key].append(o)
            ex.stats["observations"] += 1

    bad_cids, seen_reviews = set(), set()
    dept_pending = defaultdict(set)   # department NAME without a learned code -> {(cid, date)} (D18)

    def review(kind, **payload):
        k = (kind, tuple(sorted((a, str(b)) for a, b in payload.items() if a != "samples")))
        if k not in seen_reviews:
            seen_reviews.add(k)
            ex.reviews.append({"kind": kind, "payload": payload})

    def identify(o: Obs):
        """-> (cid, date_iso, person) or None (and a review) when the row can't be keyed."""
        d = N.cid_digits(o.ident.get("cid"))
        if not N.cid_valid(d):
            raw = N.text(o.ident.get("cid"))
            if raw and raw not in bad_cids:
                bad_cids.add(raw)
                review("cid", raw_cid=raw, sheet=o.sheet, cell=o.cell,
                       reason="เลขบัตรประชาชนไม่ถูกต้อง (checksum ไม่ผ่านหรือไม่ครบ 13 หลัก)")
            return None
        raw_date = o.ident.get("visit_date")
        if N.text(raw_date) is None and round_date is not None:
            vd = round_date                      # the round's date, as picked in the dialog
        else:
            try:
                vd = N.parse_date(raw_date).isoformat()
            except N.Unparseable as e:
                review("value", cid=d, visit_date=None, column="visit_date", raw=N.text(raw_date),
                       sheet=o.sheet, reason=str(e))
                return None
        person = {}
        try:
            if "full_name" in o.ident:
                person["first_name"], person["last_name"] = N.split_full_name(o.ident["full_name"])
            for role in ("first_name", "last_name"):
                if role in o.ident and N.text(o.ident[role]):
                    person[role] = N.clean_name(o.ident[role])
        except N.Unparseable as e:
            person.pop("first_name", None), person.pop("last_name", None)
            review("value", cid=d, visit_date=vd, column="first_name", also=["last_name"],
                   raw=N.text(o.ident.get("full_name") or o.ident.get("first_name")), sheet=o.sheet, reason=str(e))
        dept = N.text(o.ident.get("department_id")) if "department_id" in o.ident else None
        if dept:
            if round_date is not None:
                # D23 superseded D18. A department is now a real row owned by the
                # workplace, so the name is passed through as written and store.py
                # matches it against that workplace's departments. Asking a reviewer
                # for a "department code" here would be a question about a scheme
                # that no longer exists.
                person["department_id"] = dept
            else:
                code = dept if N.looks_like_code(dept) else mapper.dept_code(dept)
                if code:
                    person["department_id"] = code
                else:
                    dept_pending[dept].add((d, vd))
        return d, vd, person

    def put(key, person, col, value, o: Obs, res: Resolution):
        row = ex.rows.setdefault(key, {"person": {}, "cells": {}})
        for k, v in person.items():
            row["person"].setdefault(k, v)
        prov = {"sheet": o.sheet, "cell": o.cell, "raw_name": o.label, "raw_value": N.text(o.raw),
                "raw_unit": o.unit, "mapping_id": res.mapping_id}
        prev = row["cells"].get(col)
        if prev is None:
            row["cells"][col] = (value, prov)
        elif prev != "__dup__" and not _same(col, prev[0], value):
            # the same file gives two different values for one cell: don't pick one
            row["cells"][col] = "__dup__"
            review("value", cid=key[0], visit_date=key[1], column=col,
                   raw=f"{prev[1]['raw_value']} / {N.text(o.raw)}", sheet=o.sheet,
                   reason="ไฟล์เดียวกันมีค่าสองค่าสำหรับช่องเดียวกัน")

    # 2. per label: unresolved -> mapping review; numeric -> range check first
    for (label, unit), obs in obs_by_label.items():
        res = resolutions[(label, unit)]
        if res.target is None:
            review("mapping", label=label, unit=unit, reason=res.reason, suggestion=res.suggestion,
                   samples=[N.text(o.raw) for o in obs[:SAMPLES]], count=len(obs),
                   **({"maybe_identity": True} if label in id_headers else {}),
                   # a company-column unit conflict is already answered by the comparison
                   # itself (CONTEXT.md) — no AI proposal belongs on this question
                   **({"company_column_conflict": res.company_column_conflict}
                      if res.company_column_conflict else (evidence or {}).get((label, unit), {})))
            ex.stats["cells_unmapped"] += len(obs)
            continue
        if res.target == TARGET_IGNORE:
            continue
        if (res.target not in (TARGET_BP, TARGET_EXTRA)
                and not res.target.startswith(TARGET_EXTRA_COL_PREFIX)
                and FIELDS_BY_COLUMN[res.target].kind == "numeric"):
            if _range_suspect(res, obs):
                f = FIELDS_BY_COLUMN[res.target]
                review("mapping", label=label, unit=unit, suggestion=res.target,
                       reason=f"ค่าส่วนใหญ่อยู่นอกช่วงที่เป็นไปได้ของ {res.target} ({f.lo}–{f.hi} {f.unit}) "
                              f"— หน่วยหรือการจับคู่อาจผิด", samples=[N.text(o.raw) for o in obs[:SAMPLES]],
                       count=len(obs), range_suspect=True, canonical_unit=f.unit, lo=f.lo, hi=f.hi)
                ex.stats["cells_range_flagged"] += len(obs)
                continue

        for o in obs:
            ident = identify(o)
            if ident is None:
                continue
            cid, vd, person = ident
            key = (cid, vd)
            ex.rows.setdefault(key, {"person": {}, "cells": {}})
            for k, v in person.items():
                ex.rows[key]["person"].setdefault(k, v)
            if N.is_na(o.raw):
                continue
            try:
                _convert(o, res, key, person, put, ex, review, comment_labels or {}, comment_evidence or {})
            except N.Unparseable as e:
                col = "bp_systolic" if res.target == TARGET_BP else res.target
                review("value", cid=cid, visit_date=vd, column=col, raw=N.text(o.raw), sheet=o.sheet,
                       cell=o.cell, label=label, reason=str(e))
                ex.stats["cells_value_flagged"] += 1

    for name, keys in dept_pending.items():
        review("department", name=name, count=len(keys), keys=[list(k) for k in sorted(keys)][:2000],
               reason="แผนกเขียนเป็นชื่อ — ระบุรหัสแผนกครั้งเดียว ระบบจะจำไว้สำหรับโรงพยาบาลนี้")

    # drop cells marked as in-file duplicates
    for row in ex.rows.values():
        row["cells"] = {c: v for c, v in row["cells"].items() if v != "__dup__"}

    # 3. comment present, category column absent from the file -> classify from text (human/agent)
    resolved = {r.target for r in resolutions.values()}
    for cat, cmt in COMMENT_OF.items():
        if cmt in resolved and cat not in resolved:
            for (cid, vd), row in ex.rows.items():
                if cmt in row["cells"]:
                    text, prov = row["cells"][cmt]
                    known = (comment_labels or {}).get((cat, N.norm_comment(text)))
                    if known is not None:
                        row["cells"][cat] = (known, {**prov, "raw_name": f"{prov['raw_name']} (จัดประเภทจากข้อความ)"})
                        continue
                    review("comment", cid=cid, visit_date=vd, column=cat, text=text,
                           reason="มีแต่ข้อความผลตรวจ ต้องจัดว่าปกติหรือผิดปกติ",
                           **(comment_evidence or {}).get((cat, N.norm_comment(text)), {}))
    ex.stats["cells_ok"] = sum(len(r["cells"]) for r in ex.rows.values())
    return ex


def _convert(o: Obs, res: Resolution, key, person, put, ex: Extraction, review, labels: dict, cev: dict):
    if res.target == TARGET_BP:
        bp = N.parse_bp(o.raw)
        if bp:
            put(key, person, "bp_systolic", bp[0], o, res)
            put(key, person, "bp_diastolic", bp[1], o, res)
        return
    if res.target == TARGET_EXTRA or res.target.startswith(TARGET_EXTRA_COL_PREFIX):
        try:
            num, u = N.parse_number(o.raw)
            val_num, val_text = num, None
        except N.Unparseable:
            val_num, val_text, u = None, N.text(o.raw), None
        column_id = (int(res.target[len(TARGET_EXTRA_COL_PREFIX):])
                    if res.target.startswith(TARGET_EXTRA_COL_PREFIX) else None)
        ex.extras.append({"cid": key[0], "visit_date": key[1], "source_name": o.label, "value_num": val_num,
                          "value_text": val_text, "unit": o.unit or u, "sheet": o.sheet, "cell": o.cell,
                          "column_id": column_id})
        return
    f = FIELDS_BY_COLUMN[res.target]
    if f.kind == "numeric":
        num, inline_unit = N.parse_number(o.raw)
        if num is None:
            return
        factor = res.factor
        if inline_unit:
            factor = unit_factor(res.target, inline_unit)
            if factor is None:
                raise N.Unparseable(f"หน่วย '{inline_unit}' ไม่ตรงกับคอลัมน์ {res.target}")
        value = round(num * factor, f.precision[1])
        if not (f.lo <= value <= f.hi):
            raise N.Unparseable(f"ค่า {value} {f.unit} อยู่นอกช่วงที่เป็นไปได้ ({f.lo}–{f.hi})")
        put(key, person, res.target, value, o, res)
    elif f.kind == "categorical":
        try:
            v = N.parse_categorical(o.raw)
        except N.Unparseable:
            # a finding written in the result column ("Fibrosis RUL"): classify it like a comment,
            # and keep the text as the comment when it is abnormal (R1)
            cmt, text = COMMENT_OF.get(res.target), N.text(o.raw)
            if not cmt or not text or not re.search(r"[A-Za-z\u0E00-\u0E7F]{2}", text):
                raise
            k = (res.target, N.norm_comment(text))
            if k not in labels:
                review("comment", cid=key[0], visit_date=key[1], column=res.target, also=[cmt], text=text,
                       reason="ผลตรวจเขียนเป็นข้อความ ต้องจัดว่าปกติหรือผิดปกติ", **cev.get(k, {}))
                return
            put(key, person, res.target, labels[k], o, res)
            if labels[k] == 2:
                put(key, person, cmt, text, o, res)
            return
        if v is not None:
            put(key, person, res.target, v, o, res)
    else:
        v = N.text(o.raw)
        if v is not None:
            if f.size and len(v) > f.size:
                raise N.Unparseable(f"ข้อความยาวเกิน {f.size} ตัวอักษร")
            put(key, person, res.target, v, o, res)


def _range_suspect(res: Resolution, obs: list[Obs]) -> bool:
    f = FIELDS_BY_COLUMN[res.target]
    vals = []
    for o in obs:
        try:
            num, inline = N.parse_number(o.raw)
        except N.Unparseable:
            continue
        if num is not None and not inline:
            vals.append(num * res.factor)
    if len(vals) < 3:
        return False
    out = sum(1 for v in vals if not (f.lo <= v <= f.hi))
    return out / len(vals) >= RANGE_FLAG_SHARE


def _same(col, a, b) -> bool:
    if FIELDS_BY_COLUMN[col].kind in ("numeric", "categorical"):
        return abs(float(a) - float(b)) < 0.005
    return str(a) == str(b)
