"""
extract.py
==========
Sheets + specs + mapper -> clean cells, extras and review items.

Every cell either becomes a clean canonical value, or a review item that
says exactly what a human must decide (docs/requirements.md "กฎเหล็ก").
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from app.models import TARGET_EXTRA, TARGET_IGNORE
from app.pipeline import normalize as N
from app.pipeline.mapper import TARGET_BP, Mapper, Resolution
from app.pipeline.profiler import SheetSpec
from app.pipeline.reader import Sheet
from app.pipeline.units import factor as unit_factor
from app.template import FIELDS_BY_COLUMN

COMMENT_OF = {"chest_xray": "xray_comment", "ekg": "ekg_comment",
              "hearing_ability": "hearing_comment", "far_vision_test": "far_vision_comment"}
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
            for r in spec.label_rows:
                unit = rows[r][spec.unit_col] if spec.unit_col is not None else None
                yield Obs(sheet.name, sheet.cell_ref(r, c), ident, N.text(rows[r][0]), N.text(unit), rows[r][c])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def extract(sheets: list[Sheet], specs: list[SheetSpec], mapper: Mapper,
            evidence: dict | None = None) -> Extraction:
    """evidence: {(label, unit): {...}} from the agents, attached to mapping reviews."""
    ex = Extraction()
    for spec in specs:
        for p in spec.problems:
            ex.reviews.append({"kind": "profile", "payload": {"sheet": spec.sheet, "problem": p}})

    # 1. read every observation, resolve its label once
    resolutions: dict[tuple, Resolution] = {}
    obs_by_label = defaultdict(list)
    for sheet, spec in zip(sheets, specs):
        if spec.layout == "skip":
            continue
        for o in observations(sheet, spec):
            if o.label is None:
                continue
            key = (o.label, o.unit)
            if key not in resolutions:
                resolutions[key] = mapper.resolve(o.label, o.unit)
            obs_by_label[key].append(o)
            ex.stats["observations"] += 1

    bad_cids, seen_reviews = set(), set()

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
        try:
            vd = N.parse_date(o.ident.get("visit_date")).isoformat()
        except N.Unparseable as e:
            review("value", cid=d, visit_date=None, column="visit_date", raw=N.text(o.ident.get("visit_date")),
                   sheet=o.sheet, reason=str(e))
            return None
        person = {}
        if "full_name" in o.ident:
            person["first_name"], person["last_name"] = N.split_full_name(o.ident["full_name"])
        for role in ("first_name", "last_name", "department_id"):
            if role in o.ident and N.text(o.ident[role]):
                person[role] = N.text(o.ident[role])
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
                   **(evidence or {}).get((label, unit), {}))
            ex.stats["cells_unmapped"] += len(obs)
            continue
        if res.target == TARGET_IGNORE:
            continue
        if res.target not in (TARGET_BP, TARGET_EXTRA) and FIELDS_BY_COLUMN[res.target].kind == "numeric":
            if _range_suspect(res, obs):
                f = FIELDS_BY_COLUMN[res.target]
                review("mapping", label=label, unit=unit, suggestion=res.target,
                       reason=f"ค่าส่วนใหญ่อยู่นอกช่วงที่เป็นไปได้ของ {res.target} ({f.lo}–{f.hi} {f.unit}) "
                              f"— หน่วยหรือการจับคู่อาจผิด", samples=[N.text(o.raw) for o in obs[:SAMPLES]],
                       count=len(obs))
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
                _convert(o, res, key, person, put, ex, review)
            except N.Unparseable as e:
                col = "bp_systolic" if res.target == TARGET_BP else res.target
                review("value", cid=cid, visit_date=vd, column=col, raw=N.text(o.raw), sheet=o.sheet,
                       cell=o.cell, label=label, reason=str(e))
                ex.stats["cells_value_flagged"] += 1

    # drop cells marked as in-file duplicates
    for row in ex.rows.values():
        row["cells"] = {c: v for c, v in row["cells"].items() if v != "__dup__"}

    # 3. comment present, category column absent from the file -> classify from text (human/agent)
    resolved = {r.target for r in resolutions.values()}
    for cat, cmt in COMMENT_OF.items():
        if cmt in resolved and cat not in resolved:
            for (cid, vd), row in ex.rows.items():
                if cmt in row["cells"]:
                    review("comment", cid=cid, visit_date=vd, column=cat, text=row["cells"][cmt][0],
                           reason="มีแต่ข้อความผลตรวจ ต้องจัดว่าปกติหรือผิดปกติ")
    ex.stats["cells_ok"] = sum(len(r["cells"]) for r in ex.rows.values())
    return ex


def _convert(o: Obs, res: Resolution, key, person, put, ex: Extraction, review):
    if res.target == TARGET_BP:
        bp = N.parse_bp(o.raw)
        if bp:
            put(key, person, "bp_systolic", bp[0], o, res)
            put(key, person, "bp_diastolic", bp[1], o, res)
        return
    if res.target == TARGET_EXTRA:
        try:
            num, u = N.parse_number(o.raw)
            val_num, val_text = num, None
        except N.Unparseable:
            val_num, val_text, u = None, N.text(o.raw), None
        ex.extras.append({"cid": key[0], "visit_date": key[1], "source_name": o.label, "value_num": val_num,
                          "value_text": val_text, "unit": o.unit or u, "sheet": o.sheet, "cell": o.cell})
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
        v = N.parse_categorical(o.raw)
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
