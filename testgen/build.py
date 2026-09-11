"""
build.py
========
Generates a test set with ground truth.

    .venv/bin/python -m testgen.build dev           # testdata/dev/...
    .venv/bin/python -m testgen.build exam          # testdata/exam/... + LOCK.json (refuses to overwrite)
    .venv/bin/python -m testgen.build --verify exam # check exam files still match LOCK.json

Per case, testdata/<set>/<case>/truth.json holds:
  uploads[]   per-file truth (headers, lab_names, flagged, extras, …) in upload order
  expected    final DB state after all uploads: one row per (cid, visit_date)
  conflicts   values a later upload changed — must NOT overwrite silently
  flagged     rows/values that must go to a human instead of being saved
  extras      results that belong in extra_results
  derived     (cid, visit_date, column) values that exist only as comment text
"""

import argparse
import copy
import hashlib
import json
import os
import random
import shutil
import sys

from app.template import FIELDS_BY_COLUMN
from testgen.cases import DEV, EXAM, Case
from testgen.render import render
from testgen.truth import make_records

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "testdata")
SEEDS = {"dev": 20260912, "exam": 99173}


def _seed(set_name: str, *parts) -> int:
    h = hashlib.sha256(f"{SEEDS[set_name]}|{'|'.join(map(str, parts))}".encode()).hexdigest()
    return int(h[:12], 16)


def _modify(records, n, rng):
    """Change n numeric values (simulates a corrected re-submission)."""
    numeric = [c for c, f in FIELDS_BY_COLUMN.items() if f.kind == "numeric"]
    done = 0
    while done < n:
        r = rng.choice(records)
        col = rng.choice(numeric)
        v = r.values.get(col)
        if v is None or col in ("bp_diastolic",):
            continue
        r.values[col] = round(v * rng.uniform(1.08, 1.3), 2)
        done += 1


def build_case(set_name: str, case: Case, out_dir: str) -> dict:
    rng = random.Random(_seed(set_name, case.name, "records"))
    groups = {g: make_records(rng, case.n) for g in case.groups}

    uploads = []
    for i, up in enumerate(case.uploads):
        records = copy.deepcopy(groups[up.records])
        if up.modify:
            _modify(records, up.modify, random.Random(_seed(set_name, case.name, "modify", i)))
        layout_seed = _seed(set_name, case.name, "upload", up.same_layout_as if up.same_layout_as is not None else i)
        path = os.path.join(out_dir, up.filename)
        t = render(records, up.style, set_name, path, up.hospital, random.Random(layout_seed))
        t["file"] = up.filename
        uploads.append(t)

    expected, conflicts, flagged, extras, derived = {}, [], [], {}, []
    for t in uploads:
        for rec in t["records"]:
            key = (rec["cid"], rec["visit_date"])
            if key not in expected:
                expected[key] = copy.deepcopy(rec)
                expected[key]["hospital"] = t["hospital"]
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
        for rec in t["records"]:
            for col in t["derived_columns"]:
                if col in rec["values"]:
                    derived.append({"cid": rec["cid"], "visit_date": rec["visit_date"], "column": col})

    return {
        "case": case.name, "desc": case.desc, "set": set_name,
        "uploads": uploads,
        "expected": sorted(expected.values(), key=lambda r: (r["cid"], r["visit_date"])),
        "conflicts": conflicts, "flagged": flagged, "extras": list(extras.values()), "derived": derived,
    }


def _sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def build(set_name: str, force: bool = False):
    cases = DEV if set_name == "dev" else EXAM
    set_dir = os.path.join(ROOT, set_name)
    lock_path = os.path.join(set_dir, "LOCK.json")
    if set_name == "exam" and os.path.exists(lock_path) and not force:
        sys.exit("exam set is locked (testdata/exam/LOCK.json). Use --verify, or --force to regenerate on purpose.")
    shutil.rmtree(set_dir, ignore_errors=True)

    summary = []
    for case in cases:
        out = os.path.join(set_dir, case.name)
        os.makedirs(out)
        truth = build_case(set_name, case, out)
        with open(os.path.join(out, "truth.json"), "w", encoding="utf-8") as fh:
            json.dump(truth, fh, ensure_ascii=False, indent=1, default=str)
        n_vals = sum(len(r["values"]) for r in truth["expected"])
        summary.append((case.name, len(case.uploads), len(truth["expected"]), n_vals,
                        len(truth["conflicts"]), len(truth["flagged"]), len(truth["extras"]), len(truth["derived"])))

    if set_name == "exam":
        files = sorted(os.path.relpath(os.path.join(d, f), set_dir)
                       for d, _, fs in os.walk(set_dir) for f in fs if f != "LOCK.json")
        with open(lock_path, "w") as fh:
            json.dump({f: _sha(os.path.join(set_dir, f)) for f in files}, fh, indent=1)

    print(f"{'case':32} files people values conflicts flagged extras derived")
    for row in summary:
        print(f"{row[0]:32} {row[1]:>5} {row[2]:>6} {row[3]:>6} {row[4]:>9} {row[5]:>7} {row[6]:>6} {row[7]:>7}")


def verify(set_name: str) -> bool:
    set_dir = os.path.join(ROOT, set_name)
    with open(os.path.join(set_dir, "LOCK.json")) as fh:
        lock = json.load(fh)
    bad = [f for f, h in lock.items() if not os.path.exists(os.path.join(set_dir, f))
           or _sha(os.path.join(set_dir, f)) != h]
    print("exam set OK" if not bad else f"exam set CHANGED: {bad}")
    return not bad


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("set", choices=["dev", "exam"])
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    if a.verify:
        sys.exit(0 if verify(a.set) else 1)
    build(a.set, a.force)
