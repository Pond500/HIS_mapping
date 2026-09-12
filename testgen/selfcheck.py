"""
selfcheck.py
============
Checks that a generated test set is internally consistent: re-reads every
file using the truth's own header/lab-name map and confirms each cell agrees
with the expected canonical value. Catches bugs in the generator, not in
the pipeline.

    .venv/bin/python -m testgen.selfcheck dev
"""

import csv
import json
import os
import re
import sys

import openpyxl

from app.template import FIELDS_BY_COLUMN
from testgen import vocab
from testgen.build import ROOT


def _grid(path, style):
    if style["fmt"] == "csv":
        with open(path, encoding=style["encoding"], newline="") as fh:
            return {"csv": [list(r) for r in csv.reader(fh, delimiter=style["delimiter"])]}
    wb = openpyxl.load_workbook(path)
    return {ws.title: [list(r) for r in ws.iter_rows(values_only=True)] for ws in wb.worksheets}


def _cid(v):
    if v is None:
        return None
    if isinstance(v, float):
        return str(int(v))
    s = re.sub(r"\D", "", str(v).split(".")[0] if re.fullmatch(r"\d+\.0", str(v)) else str(v))
    return s or None


def _num(v):
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "").split(" ")[0]
    if s.lower() in ("n/a", "-", "") or s.startswith("<"):
        return None
    return float(s)


def _check_cell(cell, target, info, rec, set_name, bad):
    if cell is None or cell == "":
        return 0
    if target == "__bp__":
        s, d = map(float, str(cell).split("/"))
        ok = rec["values"].get("bp_systolic") == s and rec["values"].get("bp_diastolic") == d
        if not ok:
            bad.append(("bp", cell, rec["cid"]))
        return 1
    if target not in FIELDS_BY_COLUMN:
        return 0
    exp = rec["values"].get(target)
    kind = FIELDS_BY_COLUMN[target].kind
    if kind == "categorical":
        pools = vocab.CATEGORICAL_DEV if set_name == "dev" else vocab.CATEGORICAL_EXAM
        findings = vocab.COMMENTS_DEV if set_name == "dev" else vocab.COMMENTS_EXAM
        ok = str(cell).strip() == str(exp) or (exp is not None and (
            str(cell) in pools[exp] or str(cell) in findings.get(target, {}).get(exp, [])))
    elif kind == "numeric":
        v = _num(cell)
        if v is None:
            return 0
        ok = exp is not None and abs(v * info["factor"] - exp) <= 0.0051 + abs(exp) * 1e-9
    else:
        ok = str(cell).strip() == str(exp)
    if not ok:
        bad.append((target, cell, exp, rec["cid"]))
    return 1


def check_upload(case_dir, up, set_name):
    grid = _grid(os.path.join(case_dir, up["file"]), up["style"])
    recs = {r["cid"]: r for r in up["records"]}
    hdr_role = up["headers"]
    cid_hdr = next(h for h, r in hdr_role.items() if r == "cid")
    checked, bad = 0, []
    for rows in grid.values():
        if up["style"]["layout"] == "transposed":
            cid_row = next(r for r in rows if r and r[0] == cid_hdr)
            start = next(i for i, r in enumerate(rows) if r and r[0] == "รายการตรวจ") + 1
            for r in rows[start:]:
                info = up["lab_names"].get(r[0])
                for j in range(2, len(r)):
                    rec = recs.get(_cid(cid_row[j]))
                    if info and rec:
                        checked += _check_cell(r[j], info["target"], info, rec, set_name, bad)
            continue
        h = next(i for i, r in enumerate(rows) if cid_hdr in r)
        header = rows[h]
        ci = header.index(cid_hdr)
        for r in rows[h + 1:]:
            if not r or r[0] == "หน่วย":
                continue
            rec = recs.get(_cid(r[ci]))
            if not rec:
                continue
            if up["style"]["layout"] == "long":
                lab = r[header.index(next(x for x, role in hdr_role.items() if role == "lab_name"))]
                res = r[header.index(next(x for x, role in hdr_role.items() if role == "result"))]
                info = up["lab_names"].get(lab)
                if info:
                    checked += _check_cell(res, info["target"], info, rec, set_name, bad)
            else:
                for j, hname in enumerate(header):
                    info = up["lab_names"].get(hname)
                    if info and j < len(r):
                        checked += _check_cell(r[j], info["target"], info, rec, set_name, bad)
    return checked, bad


def main(set_name):
    set_dir = os.path.join(ROOT, set_name)
    total_bad = 0
    for case in sorted(os.listdir(set_dir)):
        tpath = os.path.join(set_dir, case, "truth.json")
        if not os.path.exists(tpath):
            continue
        truth = json.load(open(tpath, encoding="utf-8"))
        n, bads = 0, []
        for up in truth["uploads"]:
            c, b = check_upload(os.path.join(set_dir, case), up, set_name)
            n += c
            bads += b
        total_bad += len(bads)
        print(f"{case:32} checked {n:5}  mismatches {len(bads)}" + (f"  e.g. {bads[:3]}" if bads else ""))
    print("OK" if total_bad == 0 else f"FAILED: {total_bad} mismatches")
    return total_bad == 0


if __name__ == "__main__":
    sys.exit(0 if main(sys.argv[1] if len(sys.argv) > 1 else "dev") else 1)
