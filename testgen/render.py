"""
render.py
=========
Turns ground-truth records into a file in a given Style, and returns the
truth for that file: what every header / lab name means, the expected
canonical value of every cell, and what must be flagged instead of saved.
"""

import csv
import hashlib
import random
from dataclasses import asdict, dataclass, field
from datetime import date

import openpyxl
from openpyxl.styles import Alignment, Font

from app.template import FIELDS_BY_COLUMN, RESULT_COLUMNS
from testgen import vocab
from testgen.truth import TYPICAL, Record, corrupt_cid

LAB_GROUPS = {"cbc", "kidney", "liver", "metabolic", "toxicology", "cholinesterase"}
CATEGORICAL = ["chest_xray", "ekg", "hearing_ability", "far_vision_test"]
COMMENT_OF = {"chest_xray": "xray_comment", "ekg": "ekg_comment",
              "hearing_ability": "hearing_comment", "far_vision_test": "far_vision_comment"}
DP = {"db": 2, "bp_diastolic": 0, "spirometry_fev1": 2, "spirometry_fev1_fvc": 1, "hct": 1}
SHEET_OF_GROUP = {"cbc": "CBC", "kidney": "Chemistry", "liver": "Chemistry", "metabolic": "Chemistry",
                  "toxicology": "Chemistry", "cholinesterase": "Chemistry"}
CENSORABLE = {"tb", "db", "venous_blood_lead"}


@dataclass
class Style:
    layout: str = "long"        # long | wide | transposed
    labels: str = "known"       # known | novel | mixed | template
    columns: str = "all"        # all | lab | pe | subset
    unit_mode: str = "none"     # none | column (long) | header | row (wide) | inline
    alt_units: bool = False
    date_fmt: str = "iso"       # iso | iso_datetime | dmy_ce | dmy_be | dmy_be2 | thai_month_be | ymd_be | excel | mixed
    cid_fmt: str = "plain"      # plain | float | dashed | spaced | mixed
    bad_cid_rate: float = 0.0
    categorical: str = "code"   # code | text | comment_only
    bp_combined: bool = False
    extras: bool = False
    tb_is_tuberculosis: bool = False
    noise_cols: bool = False
    value_noise: bool = False
    preamble: int = 0           # report-title rows above the table
    group_header: bool = False  # wide xlsx: merged group row above labels
    fmt: str = "xlsx"           # xlsx | csv
    encoding: str = "utf-8"
    delimiter: str = ","
    split_sheets: bool = False  # xlsx: CBC / Chemistry / PE sheets
    full_name: bool = False     # one "ชื่อ-สกุล" column
    label_overrides: dict = field(default_factory=dict)  # force a label for a column
    id_headers: dict = field(default_factory=dict)       # force identity headers (role -> header)


class Pools:
    def __init__(self, set_name: str):
        s = "DEV" if set_name == "dev" else "EXAM"
        self.novel = getattr(vocab, f"NOVEL_{s}")
        self.extras = getattr(vocab, f"EXTRAS_{s}")
        self.noise = getattr(vocab, f"NOISE_{s}")
        self.unit_alts = getattr(vocab, f"UNIT_ALTS_{s}")
        self.id_headers = getattr(vocab, f"ID_HEADERS_{s}")
        self.categorical = getattr(vocab, f"CATEGORICAL_{s}")
        self.comments = getattr(vocab, f"COMMENTS_{s}")


# ---------------------------------------------------------------------------
# Cell renderers
# ---------------------------------------------------------------------------


def render_date(d: date, fmt: str, rng: random.Random):
    if fmt == "mixed":
        fmt = rng.choice(["iso", "dmy_be", "thai_month_be", "dmy_ce", "ymd_be"])
    be = d.year + 543
    return {
        "iso": d.isoformat(),
        "iso_datetime": f"{d.isoformat()} 00:00:00",
        "dmy_ce": f"{d.day:02d}/{d.month:02d}/{d.year}",
        "dmy_be": f"{d.day:02d}/{d.month:02d}/{be}",
        "dmy_be2": f"{d.day:02d}/{d.month:02d}/{be % 100:02d}",
        "thai_month_be": f"{d.day} {vocab.THAI_MONTHS[d.month - 1]} {be}",
        "ymd_be": f"{be}-{d.month:02d}-{d.day:02d}",
        "excel": d,
    }[fmt]


def render_cid(cid: str, fmt: str, rng: random.Random):
    if fmt == "mixed":
        fmt = rng.choice(["plain", "float", "dashed", "spaced"])
    if fmt == "float":
        return float(cid)
    if fmt == "dashed":
        return f"{cid[0]}-{cid[1:5]}-{cid[5:10]}-{cid[10:12]}-{cid[12]}"
    if fmt == "spaced":
        return f"{cid[0]} {cid[1:5]} {cid[5:10]} {cid[10:12]} {cid[12]}"
    return cid


def fmt_num(v: float, dp: int):
    return int(v) if dp == 0 else round(v, dp)


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------


def render(records: list[Record], style: Style, set_name: str, path: str, hospital: str,
           rng: random.Random) -> dict:
    pools = Pools(set_name)
    truth = {"file": path, "hospital": hospital, "style": asdict(style),
             "headers": {}, "lab_names": {}, "records": [], "flagged": [], "extras": [],
             "derived_columns": []}

    cols = _choose_columns(style, rng)
    if style.categorical == "comment_only":
        truth["derived_columns"] = [c for c in CATEGORICAL if c in cols]
    labels = {c: style.label_overrides.get(c) or _choose_label(c, style, pools, rng) for c in cols}
    assert len(set(labels.values())) == len(labels), f"duplicate labels in {path}"
    units = {c: _choose_unit(c, style, pools) for c in cols}
    extra_labels = rng.sample(sorted(pools.extras), k=min(4, len(pools.extras))) if style.extras else []
    noise = rng.sample(pools.noise, k=2) if style.noise_cols else []
    id_hdr = {role: (style.id_headers.get(role)
                     or (FIELDS_BY_COLUMN[role].header if style.labels == "template" and role in FIELDS_BY_COLUMN
                         else rng.choice(pool))) for role, pool in pools.id_headers.items()}
    if style.full_name:
        id_hdr["full_name"] = rng.choice(["ชื่อ-สกุล", "ชื่อ - นามสกุล", "Name"])

    # lab-name truth (what each label means)
    for c in cols:
        if c in truth["derived_columns"]:
            continue
        if style.bp_combined and c in ("bp_systolic", "bp_diastolic"):
            continue
        unit, k = units[c]
        truth["lab_names"][labels[c]] = {"target": c, "factor": round(1 / k, 10), "unit": unit}
    bp_label = None
    if style.bp_combined and "bp_systolic" in cols:
        bp_label = rng.choice(["BP", "ความดันโลหิต", "Blood Pressure"])
        truth["lab_names"][bp_label] = {"target": "__bp__", "factor": 1, "unit": "mmHg"}
    for x in extra_labels:
        truth["lab_names"][x] = {"target": "__extra__", "factor": 1, "unit": pools.extras[x][1]}
    tb_label = "TB" if style.tb_is_tuberculosis else None
    if tb_label:
        truth["lab_names"][tb_label] = {"target": "__extra__", "factor": 1, "unit": None}

    # build one logical row per record: {role_or_label: cell} + expected values
    logical = []
    for r in records:
        cid = r.cid
        bad = rng.random() < style.bad_cid_rate
        if bad:
            cid = corrupt_cid(cid, rng)
        cells, expected = {}, {}
        cells["cid"] = render_cid(cid, style.cid_fmt, rng)
        if style.full_name:
            cells["full_name"] = f"{r.first_name} {r.last_name}"
        else:
            cells["first_name"], cells["last_name"] = r.first_name, r.last_name
        cells["department_id"] = r.department_id
        cells["visit_date"] = render_date(r.visit_date, style.date_fmt if style.fmt == "xlsx" or style.date_fmt != "excel" else "iso", rng)

        for c in cols:
            cell, exp, flag = _render_value(c, r, style, pools, units[c], rng)
            if c in truth["derived_columns"]:
                expected[c] = r.values.get(c)
                continue
            if style.bp_combined and c in ("bp_systolic", "bp_diastolic"):
                continue
            if cell is not None:
                cells[labels[c]] = cell
            expected[c] = exp
            if flag:
                truth["flagged"].append({"kind": flag, "cid": r.cid, "visit_date": r.visit_date.isoformat(),
                                         "column": c, "raw": str(cell)})
        if bp_label:
            s, d = r.values.get("bp_systolic"), r.values.get("bp_diastolic")
            if s is not None and d is not None:
                cells[bp_label] = f"{int(s)}/{int(d)}"
                expected["bp_systolic"], expected["bp_diastolic"] = s, d
        for x in extra_labels:
            key, unit = pools.extras[x]
            cells[x] = r.extras[key]
            truth["extras"].append({"cid": r.cid, "visit_date": r.visit_date.isoformat(),
                                    "name": x, "value": r.extras[key], "unit": unit})
        if tb_label:
            cells[tb_label] = rng.choice(["negative", "negative", "negative", "positive"])
            truth["extras"].append({"cid": r.cid, "visit_date": r.visit_date.isoformat(),
                                    "name": tb_label, "value": cells[tb_label], "unit": None})
        for nz in noise:
            cells[nz] = str(rng.randint(100000, 999999))

        if bad:
            truth["flagged"].append({"kind": "invalid_cid", "raw_cid": cid,
                                     "visit_date": r.visit_date.isoformat()})
            # nothing from this row may be saved: drop its extras from the expected set
            truth["extras"] = [e for e in truth["extras"]
                               if not (e["cid"] == r.cid and e["visit_date"] == r.visit_date.isoformat())]
        else:
            truth["records"].append({
                "cid": r.cid, "first_name": r.first_name, "last_name": r.last_name,
                "department_id": r.department_id, "visit_date": r.visit_date.isoformat(),
                "values": {k: v for k, v in expected.items() if v is not None},
            })
        logical.append(cells)

    value_cols = [labels[c] for c in cols if labels[c] in truth["lab_names"]]
    value_cols += [bp_label] if bp_label else []
    value_cols += extra_labels + ([tb_label] if tb_label else [])
    id_roles = ["cid"] + (["full_name"] if style.full_name else ["first_name", "last_name"]) \
        + ["department_id", "visit_date"]

    for role in id_roles:
        truth["headers"][id_hdr[role]] = role
    for nz in noise:
        truth["headers"][nz] = "__ignore__"

    if style.layout == "long":
        sheets = _layout_long(logical, id_roles, value_cols, noise, id_hdr, truth, units, labels, cols, style)
    elif style.layout == "wide":
        sheets = _layout_wide(logical, id_roles, value_cols, noise, id_hdr, truth, units, labels, cols, style, pools)
    else:
        sheets = _layout_transposed(logical, id_roles, value_cols, id_hdr, truth, units, labels, cols, style)

    _write(path, sheets, style)
    return truth


# ---------------------------------------------------------------------------
# Choices
# ---------------------------------------------------------------------------


def _choose_columns(style: Style, rng: random.Random) -> list[str]:
    if style.columns == "lab":
        cols = [c for c in RESULT_COLUMNS if FIELDS_BY_COLUMN[c].group in LAB_GROUPS]
    elif style.columns == "pe":
        cols = [c for c in RESULT_COLUMNS if FIELDS_BY_COLUMN[c].group not in LAB_GROUPS]
    elif style.columns == "subset":
        cols = sorted(rng.sample(RESULT_COLUMNS, k=int(len(RESULT_COLUMNS) * 0.6)), key=RESULT_COLUMNS.index)
    else:
        cols = list(RESULT_COLUMNS)
    if style.layout != "wide":
        # ILO lesion fields are only realistic in wide exports
        cols = [c for c in cols if c not in ("primary_lesion", "secondary_lesion", "profusion")]
    return cols


def _choose_label(col: str, style: Style, pools: Pools, rng: random.Random) -> str:
    if style.labels == "template":
        return col
    known = vocab.KNOWN.get(col, [col])
    novel = pools.novel.get(col)
    if style.labels == "novel" and novel:
        return rng.choice(novel)
    if style.labels == "mixed" and novel and rng.random() < 0.5:
        return rng.choice(novel)
    return rng.choice(known)


def _choose_unit(col: str, style: Style, pools: Pools):
    f = FIELDS_BY_COLUMN[col]
    if style.alt_units and col in pools.unit_alts:
        return pools.unit_alts[col]
    return (f.unit, 1)


def _cell_rng(cid: str, col: str) -> random.Random:
    """Per-cell randomness tied to (person, column): a re-submitted file renders
    unchanged values identically, so only real edits become conflicts."""
    return random.Random(int(hashlib.sha256(f"{cid}|{col}".encode()).hexdigest()[:12], 16))


def _render_value(col, r: Record, style: Style, pools: Pools, unit_k, rng):
    """Returns (cell, expected canonical value, flag kind or None)."""
    rng = _cell_rng(r.cid, col)
    f = FIELDS_BY_COLUMN[col]
    v = r.values.get(col)
    unit, k = unit_k

    if f.kind == "categorical":
        if v is None:
            return None, None, None
        if style.categorical == "code":
            return v, v, None
        return rng.choice(pools.categorical[v]), v, None
    if col in COMMENT_OF.values():
        partner = next(c for c, m in COMMENT_OF.items() if m == col)
        cls = r.values.get(partner)
        if cls is None or (style.categorical == "code" and rng.random() < 0.3):
            return None, None, None
        text = rng.choice(pools.comments[partner][cls])
        return text, text, None
    if f.kind == "text":
        return v, v, None
    if v is None:
        return None, None, None

    # numeric
    dp = TYPICAL.get(col, (0, 0, DP.get(col, 2)))[2] if k == 1 else (3 if v * k < 1 else 2)
    rendered = fmt_num(v * k, dp)
    expected = round(rendered / k, 2)

    if style.value_noise:
        roll = rng.random()
        if roll < 0.03:
            return rng.choice(["N/A", "-", "n/a"]), None, None
        if roll < 0.05 and col in CENSORABLE:
            return f"<{rng.choice([0.1, 0.2, 1])}", None, "censored"
        if roll < 0.35 and abs(rendered) >= 1000:
            return f"{rendered:,}", expected, None
        if roll < 0.40:
            return f"  {rendered} ", expected, None
    if style.unit_mode == "inline" and unit:
        return f"{rendered} {unit}", expected, None
    return rendered, expected, None


# ---------------------------------------------------------------------------
# Layouts -> {sheet name: {"rows": [...], "merges": [...]}}
# ---------------------------------------------------------------------------


def _preamble(style: Style, hospital_hint="โรงพยาบาลสมมติ"):
    lines = [f"รายงานผลการตรวจสุขภาพประจำปี {hospital_hint}", "พิมพ์จากระบบ HIS", ""]
    return [[x] for x in lines[:style.preamble]]


def _layout_long(logical, id_roles, value_cols, noise, id_hdr, truth, units, labels, cols, style):
    truth["headers"][id_hdr["lab_name"]] = "lab_name"
    truth["headers"][id_hdr["result"]] = "result"
    unit_of_label = {labels[c]: units[c][0] for c in cols}
    for x, info in truth["lab_names"].items():
        unit_of_label.setdefault(x, info["unit"])
    header = [id_hdr[r] for r in id_roles] + noise + [id_hdr["lab_name"], id_hdr["result"]]
    if style.unit_mode == "column":
        header.append(id_hdr["unit"])
        truth["headers"][id_hdr["unit"]] = "unit"

    by_sheet = {}
    for cells in logical:
        for lab in value_cols:
            if lab not in cells:
                continue
            row = [cells[r] for r in id_roles] + [cells[n] for n in noise] + [lab, cells[lab]]
            if style.unit_mode == "column":
                row.append(unit_of_label.get(lab) or "")
            sheet = "Sheet1"
            if style.split_sheets:
                target = truth["lab_names"][lab]["target"]
                sheet = SHEET_OF_GROUP.get(FIELDS_BY_COLUMN[target].group, "PE") if target in FIELDS_BY_COLUMN else "Other"
            by_sheet.setdefault(sheet, []).append(row)
    return {name: {"rows": _preamble(style) + [header] + rows, "merges": []} for name, rows in by_sheet.items()}


def _layout_wide(logical, id_roles, value_cols, noise, id_hdr, truth, units, labels, cols, style, pools):
    col_of_label = {labels[c]: c for c in cols}

    def header_text(lab):
        c = col_of_label.get(lab)
        if style.unit_mode == "header" and c and units[c][0]:
            return f"{lab} ({units[c][0]})"
        return lab

    groups = {}
    for lab in value_cols:
        target = truth["lab_names"][lab]["target"]
        grp = FIELDS_BY_COLUMN[target].group if target in FIELDS_BY_COLUMN else ("vitals" if target == "__bp__" else "other")
        sheet = SHEET_OF_GROUP.get(grp, "PE") if style.split_sheets else "Sheet1"
        groups.setdefault(sheet, []).append((grp, lab))

    # headers truth uses the rendered header text
    lab_truth = truth["lab_names"]
    truth["lab_names"] = {}
    for lab, info in lab_truth.items():
        truth["headers"][header_text(lab)] = info["target"]
        truth["lab_names"][header_text(lab)] = info

    out = {}
    for sheet, items in groups.items():
        id_part = [id_hdr[r] for r in id_roles] + noise
        header = id_part + [header_text(lab) for _, lab in items]
        rows, merges = _preamble(style), []
        if style.group_header:
            top = [""] * len(id_part)
            start = len(id_part)
            for i, (grp, _) in enumerate(items):
                top.append(grp.upper() if i == 0 or items[i - 1][0] != grp else "")
            # merge consecutive same-group cells
            i = 0
            while i < len(items):
                j = i
                while j + 1 < len(items) and items[j + 1][0] == items[i][0]:
                    j += 1
                if j > i:
                    merges.append((len(rows) + 1, start + i + 1, start + j + 1))
                i = j + 1
            rows.append(top)
        rows.append(header)
        if style.unit_mode == "row":
            rows.append(["หน่วย"] + [""] * (len(id_part) - 1) +
                        [units[col_of_label[lab]][0] if lab in col_of_label else "" for _, lab in items])
        for cells in logical:
            if not any(lab in cells for _, lab in items):
                continue
            rows.append([cells.get(r) for r in id_roles] + [cells.get(n) for n in noise] +
                        [cells.get(lab) for _, lab in items])
        out[sheet] = {"rows": rows, "merges": merges}
    return out


def _layout_transposed(logical, id_roles, value_cols, id_hdr, truth, units, labels, cols, style):
    """Tests as rows, one column per person-visit (a printed-report style export)."""
    col_of_label = {labels[c]: c for c in cols}
    rows = _preamble(style)
    for role in id_roles:
        rows.append([id_hdr[role], ""] + [cells.get(role) for cells in logical])
    rows.append(["รายการตรวจ", "หน่วย"] + [""] * len(logical))
    truth["headers"]["รายการตรวจ"] = "lab_name"
    truth["headers"]["หน่วย"] = "unit"
    for lab in value_cols:
        c = col_of_label.get(lab)
        unit = units[c][0] if c else (truth["lab_names"][lab]["unit"] or "")
        rows.append([lab, unit] + [cells.get(lab) for cells in logical])
    return {"Report": {"rows": rows, "merges": []}}


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------


def _write(path: str, sheets: dict, style: Style):
    if style.fmt == "csv":
        assert len(sheets) == 1, "csv holds one sheet"
        (sheet,) = sheets.values()
        with open(path, "w", newline="", encoding=style.encoding) as fh:
            w = csv.writer(fh, delimiter=style.delimiter)
            for row in sheet["rows"]:
                w.writerow(["" if v is None else v for v in row])
        return
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, sheet in sheets.items():
        ws = wb.create_sheet(name)
        for row in sheet["rows"]:
            ws.append(row)
        for r, c1, c2 in sheet["merges"]:
            ws.merge_cells(start_row=r, start_column=c1, end_row=r, end_column=c2)
            ws.cell(r, c1).alignment = Alignment(horizontal="center")
            ws.cell(r, c1).font = Font(bold=True)
        for cell in ws[1]:
            if cell.value and style.preamble:
                cell.font = Font(bold=True, size=13)
    wb.save(path)
