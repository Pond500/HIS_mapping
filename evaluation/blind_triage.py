"""
blind_triage.py
===============
Classifies every silent error / silent drop of a blind-set result, so a report can
separate problems of the system from problems of the answer key.

    .venv/bin/python -m evaluation.blind_triage evaluation/results/blind_agents_oracle_<time>.json
    ... --export blind_test_datasets/answer_key_feedback.csv   # cells where the key disagrees with the file

Categories (checked in this order):
  dept_code      department_id: the file has a department NAME, the key wants a CODE
                 (no name->code table exists anywhere) — answer-key / requirement question
  key_rounding   numeric value whose file unit is scaled (e.g. x10^3/uL) and the key's value
                 is not recoverable from the file's written precision — answer-key issue
  blank_in_file  the key has a value but the file's cell is empty / "-" / N/A — answer-key issue
  title_prefix   a first name still carrying part of a title (e.g. "/นางสาว…") — system bug
  not_in_file    the key's value appears nowhere in the file (e.g. a company department when the
                 file only has hospital service points, a finding text never written) — answer-key issue
  comment_lost   a *_comment cell missing: the finding text was never kept — system bug
  other          anything else — needs a look
Reads input files only to locate the source cells of misses (after measuring).
"""

import csv
import json
import os
import sys
from collections import Counter

from app.pipeline import normalize as N
from app.pipeline.extract import observations
from app.pipeline.profiler import profile_sheet
from app.pipeline.reader import read_file
from app.template import FIELDS_BY_COLUMN

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTDATA = os.path.join(ROOT, "testdata", "blind")
KEY_ISSUES = ("dept_code", "key_rounding", "blank_in_file", "not_in_file")


def _file_texts(case: str, truth: dict) -> set:
    """Every non-empty cell text of the case's files (to check a key value exists at all)."""
    out = set()
    for up in truth["uploads"]:
        path = os.path.join(TESTDATA, case, up["file"])
        for sh in read_file(open(path, "rb").read(), os.path.splitext(path)[1]):
            out.update(N.text(x) for row in sh.rows for x in row if x is not None)
    return out


def _source_cells(case: str, truth: dict) -> dict:
    """(cid, column) -> raw cell text, via the pipeline's own reader/profiler."""
    out = {}
    for up in truth["uploads"]:
        path = os.path.join(TESTDATA, case, up["file"])
        label_target = {lab: info["target"] for lab, info in up["lab_names"].items()}
        for sh in read_file(open(path, "rb").read(), os.path.splitext(path)[1]):
            spec = profile_sheet(sh, set())
            if spec.layout == "skip":
                continue
            for o in observations(sh, spec):
                target = label_target.get(o.label)
                cid = N.cid_digits(o.ident.get("cid"))
                if target and cid:
                    out.setdefault((cid, target), N.text(o.raw))
    return out


def classify(case: str, truth: dict, errors: list, missing: list, rows: list | None = None) -> Counter:
    cells = _source_cells(case, truth)
    texts = _file_texts(case, truth)
    c = Counter()

    def note(category, item, raw):
        if rows is not None and category in KEY_ISSUES:
            rows.append({"case": case, "category": category, "cid": item["cid"], "visit_date": item["date"],
                         "column": item["column"], "answer_key": item.get("expected"),
                         "system_stored": item.get("got"), "cell_in_file": raw})
    for e in errors:
        col, got, exp = e["column"], e.get("got"), e.get("expected")
        if e["kind"] == "wrong" and col == "department_id":
            cat = "not_in_file" if N.text(exp) not in texts else "dept_code"
            c[cat] += 1
            note(cat, e, got)
        elif e["kind"] == "wrong" and col == "first_name" and str(got).startswith("/"):
            c["title_prefix"] += 1
        elif e["kind"] == "wrong" and FIELDS_BY_COLUMN[col].kind == "numeric" and got is not None and exp is not None:
            raw = cells.get((e["cid"], col))
            try:
                num, _ = N.parse_number(raw)
                scale = abs(float(got) / num) if num else 1
            except (N.Unparseable, TypeError, ZeroDivisionError):
                scale = 1
            # written precision of the file (last decimal) times the unit scale
            decimals = len(str(raw).split(" ")[0].split(".")[1]) if raw and "." in str(raw).split(" ")[0] else 0
            step = scale * 10 ** -decimals
            cat = "key_rounding" if abs(float(got) - float(exp)) <= step / 2 + 1e-9 else "other"
            c[cat] += 1
            note(cat, e, raw)
        else:
            c[f"other_{e['kind']}"] += 1
    for m in missing:
        col = m["column"]
        raw = cells.get((m["cid"], col), "<no source cell>")
        if col.endswith("_comment") and not any(N.text(m.get("expected")) in t for t in texts):
            c["not_in_file"] += 1
            note("not_in_file", m, None)
        elif col.endswith("_comment"):
            c["comment_lost"] += 1
        elif raw is None or N.is_na(raw):
            c["blank_in_file"] += 1
            note("blank_in_file", m, raw)
        else:
            c["other_missing"] += 1
    return c


def main(result_path: str, export: str | None = None):
    r = json.load(open(result_path, encoding="utf-8"))
    total = Counter()
    rows = [] if export else None
    for case in r["cases"]:
        if "errors_all" not in case:
            sys.exit("result has no complete error lists — re-run with the current evaluation/metrics.py")
        truth = json.load(open(os.path.join(TESTDATA, case["case"], "truth.json"), encoding="utf-8"))
        c = classify(case["case"], truth, case["errors_all"], case["missing_all"], rows)
        total.update(c)
        print(f"{case['case']:28} {dict(c)}")
    print("\nTOTAL", dict(total))
    key = sum(total[k] for k in KEY_ISSUES)
    system = sum(total.values()) - key
    print(f"attributable to the system: {system}   to the answer key / requirement: {key}")
    if export:
        with open(export, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["case"])
            w.writeheader()
            w.writerows(rows)
        print(f"wrote {len(rows)} rows to {export}")


if __name__ == "__main__":
    out = sys.argv[sys.argv.index("--export") + 1] if "--export" in sys.argv else None
    main(sys.argv[1], out)
