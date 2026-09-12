"""
blind.py
========
Turns the externally made blind test set (blind_test_datasets/, docs/requirements.md D15)
into the evaluation format: testdata/blind/<case>/{inputs, truth.json} + LOCK.json.

The inputs are never opened here — only the answer keys (answer.xlsx) are read.
Like the exam set, the blind set is for reporting only: never tune on it.

    .venv/bin/python -m evaluation.blind                # build (refuses to overwrite a locked set)
    .venv/bin/python -m evaluation.run --sut agents --set blind --oracle

Scoring policy follows the agreed requirements, which can differ from a README's wording:
- D13: a re-submitted file never overwrites silently. For blind_03 -> blind_04 the expected
  final value is blind_03's and each changed cell is an expected conflict.
"""

import hashlib
import json
import os
import re
import shutil
import sys
from datetime import date, datetime

import openpyxl

from app.pipeline import units as U
from app.pipeline.normalize import cid_digits
from app.template import FIELDS_BY_COLUMN, FIELDS_BY_HEADER, RESULT_COLUMNS
from testgen.cases import Case, Upload
from testgen.render import Style

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "blind_test_datasets")
OUT = os.path.join(ROOT, "testdata", "blind")

# (source folder, input file, hospital code) — order within a case = upload order (from the READMEs)
CASES_SPEC = [
    ("b01_b02_repeat_hospital", [("blind_01", "input.xlsx", "PVT-HSK-014", "A", None),
                                 ("blind_02", "input.xlsx", "PVT-HSK-014", "B", 0)]),
    ("b03_b04_resend", [("blind_03", "input.xlsx", "GOV-RGH-221", "A", None),
                        ("blind_04", "input.xlsx", "GOV-RGH-221", "A", 0)]),
    ("b05_vertical_two_sheets", [("blind_05", "input.xlsx", "SSB-CMH-077", "A", None)]),
    ("b06_csv_mixed", [("blind_06", "input.csv", "LAB-QCK-005", "A", None)]),
]

CASES = [Case(name, "blind (external)", [Upload(h, Style(), records=g, filename=f"{src}{os.path.splitext(fn)[1]}",
                                                same_layout_as=same) for src, fn, h, g, same in ups],
              groups=sorted({u[3] for u in ups}))
         for name, ups in CASES_SPEC]

# unit spellings in the answer keys that mean the template unit (stated in the labels/README)
SAME_AS_CANONICAL = {"µg/100ml", "ug/100ml", "mg%", "mcg/dl"}


def _rows(path, sheet):
    ws = openpyxl.load_workbook(path, read_only=True, data_only=True)[sheet]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    return [r for r in rows if any(v not in (None, "") for v in r)]


def _column(header: str) -> str | None:
    h = str(header).strip()
    if h in FIELDS_BY_HEADER:
        return FIELDS_BY_HEADER[h].column
    base = re.sub(r"\s*\(.*\)\s*$", "", h).strip()
    return base if base in FIELDS_BY_COLUMN else None


def _iso(v) -> str:
    if isinstance(v, (datetime, date)):
        return (v.date() if isinstance(v, datetime) else v).isoformat()
    return str(v).strip()[:10]


def _typed(col, v):
    if v in (None, ""):
        return None
    kind = FIELDS_BY_COLUMN[col].kind
    if kind == "numeric":
        return float(str(v).replace(",", ""))
    if kind == "categorical":
        return int(float(v))
    return str(v).strip()


def _labels(path):
    """labels sheet -> (lab_names {label: {target, factor, unit}}, headers {header: role})"""
    lab_names, headers, warnings = {}, {}, []
    for label, unit, meaning in (r[:3] for r in _rows(path, "labels")[1:]):
        label, m = str(label).strip(), str(meaning or "").strip()
        unit = re.sub(r"\s*\(.*$", "", str(unit)).strip() if unit else None
        low = (label + " " + m).lower()
        if m.startswith("extra"):
            lab_names[label] = {"target": "__extra__", "factor": 1, "unit": unit}
            continue
        if "ไม่ใช่ข้อมูลบุคคล" in m or label.startswith("แถวสุดท้าย"):
            continue
        first = re.split(r"\s*\(", m, 1)[0].strip()
        targets = [t.strip() for t in re.split(r"\s*\+\s*", first)]
        if all(t.split("/")[0] in FIELDS_BY_COLUMN for t in targets) and not m.startswith("ข้อมูลส่วนตัว"):
            if targets == ["bp_systolic", "bp_diastolic"]:
                lab_names[label] = {"target": "__bp__", "factor": 1, "unit": unit}
                continue
            names, cols = label.split("/"), targets[0].split("/")
            pairs = zip(names, cols) if len(cols) > 1 and len(names) == len(cols) else [(label, targets[0])]
            for name, col in pairs:
                f = 1.0
                if FIELDS_BY_COLUMN[col].kind == "numeric":
                    f = U.factor(col, unit) if unit and unit.lower() not in SAME_AS_CANONICAL else 1.0
                    if f is None:
                        warnings.append(f"{label!r}: unit {unit!r} unknown for {col}; factor 1 assumed")
                        f = 1.0
                lab_names[name.strip()] = {"target": col, "factor": f, "unit": unit}
            continue
        # identity / not-a-result columns
        if label.upper() in ("HN", "VN"):
            headers[label] = "__ignore__"
        elif "เลขบัตร" in low or "ปชช" in low:
            headers[label] = "cid"
        elif "วันที่" in low or "วดป" in low:
            headers[label] = "visit_date"
        elif "แผนก" in low or "หน่วยงาน" in low or "สังกัด" in low or "ward" in low:
            headers[label] = "department_id"
        elif "ชื่อ" in low:
            headers[label] = "full_name" if ("สกุล" in low) else "first_name"
        else:
            warnings.append(f"label {label!r} ({m}) not classified")
    return lab_names, headers, warnings


def _upload_truth(src, file_name, hospital):
    path = os.path.join(SRC, src, "answer.xlsx")
    exp = _rows(path, "expected")
    cols = [_column(h) for h in exp[0]]
    records = []
    for r in exp[1:]:
        rec = {"values": {}}
        for col, v in zip(cols, r):
            if col is None or v in (None, ""):
                continue
            if col == "cid":
                rec["cid"] = cid_digits(v)
            elif col == "visit_date":
                rec["visit_date"] = _iso(v)
            elif col in ("first_name", "last_name", "department_id"):
                rec[col] = str(v).strip()
            else:
                rec["values"][col] = _typed(col, v)
        records.append(rec)
    flagged = []
    for raw, day, col, value, reason in (r[:5] for r in _rows(path, "must_flag")[1:]):
        c = _column(col) if col else None
        if c in (None, "cid") or str(col).startswith("(ทั้งแถว)"):
            flagged.append({"kind": "invalid_cid", "raw_cid": str(raw), "visit_date": _iso(day), "reason": reason})
        else:
            flagged.append({"kind": "value", "cid": cid_digits(raw), "visit_date": _iso(day), "column": c,
                            "raw": str(value), "reason": reason})
    extras = [{"cid": cid_digits(r[0]), "visit_date": _iso(r[1]), "name": str(r[2]).strip(), "value": r[3],
               "unit": r[4]} for r in _rows(path, "extras")[1:]]
    lab_names, headers, warnings = _labels(path)
    return {"file": file_name, "hospital": hospital, "style": {"layout": "blind"}, "headers": headers,
            "lab_names": lab_names, "records": records, "flagged": flagged, "extras": extras,
            "derived_columns": []}, warnings


def _case_truth(name, ups):
    uploads, notes = [], []
    for src, fn, hospital, _g, _same in ups:
        t, w = _upload_truth(src, f"{src}{os.path.splitext(fn)[1]}", hospital)
        uploads.append(t)
        notes += [f"{src}: {x}" for x in w]
    expected, conflicts, flagged, extras = {}, [], [], {}
    for t in uploads:
        for rec in t["records"]:
            key = (rec["cid"], rec["visit_date"])
            if key not in expected:
                expected[key] = json.loads(json.dumps(rec))
                continue
            cur = expected[key]["values"]
            for col, v in rec["values"].items():
                if col not in cur:
                    cur[col] = v
                elif cur[col] != v:
                    conflicts.append({"cid": rec["cid"], "visit_date": rec["visit_date"], "column": col,
                                      "current": cur[col], "incoming": v, "file": t["file"]})
        flagged += [{**f, "file": t["file"]} for f in t["flagged"]]
        for e in t["extras"]:
            extras.setdefault((e["cid"], e["visit_date"], e["name"]), {**e, "file": t["file"]})
    return {"case": name, "desc": "blind (external)", "set": "blind", "uploads": uploads,
            "expected": sorted(expected.values(), key=lambda r: (r["cid"], r["visit_date"])),
            "conflicts": conflicts, "flagged": flagged, "extras": list(extras.values()), "derived": [],
            "notes": notes}


def _sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def build(force=False):
    lock_path = os.path.join(OUT, "LOCK.json")
    if os.path.exists(lock_path) and not force:
        sys.exit("blind set is locked (testdata/blind/LOCK.json). Use --force to rebuild on purpose.")
    shutil.rmtree(OUT, ignore_errors=True)
    for name, ups in CASES_SPEC:
        out = os.path.join(OUT, name)
        os.makedirs(out)
        for src, fn, *_ in ups:
            shutil.copyfile(os.path.join(SRC, src, fn), os.path.join(out, f"{src}{os.path.splitext(fn)[1]}"))
        truth = _case_truth(name, ups)
        with open(os.path.join(out, "truth.json"), "w", encoding="utf-8") as fh:
            json.dump(truth, fh, ensure_ascii=False, indent=1, default=str)
        n_vals = sum(len(r["values"]) for r in truth["expected"])
        print(f"{name:28} uploads {len(ups)}  people {len(truth['expected']):3}  values {n_vals:5}  "
              f"conflicts {len(truth['conflicts'])}  flagged {len(truth['flagged'])}  extras {len(truth['extras'])}")
        for n in truth["notes"]:
            print("   note:", n)
    files = sorted(os.path.relpath(os.path.join(d, f), OUT) for d, _, fs in os.walk(OUT) for f in fs if f != "LOCK.json")
    with open(lock_path, "w") as fh:
        json.dump({f: _sha(os.path.join(OUT, f)) for f in files}, fh, indent=1)


if __name__ == "__main__":
    build("--force" in sys.argv)
