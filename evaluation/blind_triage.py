"""
blind_triage.py
===============
Classifies every silent error / silent drop of a blind-set result, so a report can
separate problems of the system from problems of the answer key.

    .venv/bin/python -m evaluation.blind_triage evaluation/results/blind_agents_oracle_<time>.json

Categories (checked in this order):
  dept_code      department_id: the file has a department NAME, the key wants a CODE
                 (no name->code table exists anywhere) — answer-key / requirement question
  key_rounding   numeric value whose file unit is scaled (e.g. x10^3/uL) and the key's value
                 is not recoverable from the file's written precision — answer-key issue
  blank_in_file  the key has a value but the file's cell is empty / "-" / N/A — answer-key issue
  title_prefix   a first name still carrying part of a title (e.g. "/นางสาว…") — system bug
  comment_lost   a *_comment cell missing: the finding text was never kept — system bug
  other          anything else — needs a look
Reads input files only to locate the source cells of misses (after measuring).
"""

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


def classify(case: str, truth: dict, errors: list, missing: list) -> Counter:
    cells = _source_cells(case, truth)
    c = Counter()
    for e in errors:
        col, got, exp = e["column"], e.get("got"), e.get("expected")
        if e["kind"] == "wrong" and col == "department_id":
            c["dept_code"] += 1
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
            c["key_rounding" if abs(float(got) - float(exp)) <= step / 2 + 1e-9 else "other"] += 1
        else:
            c[f"other_{e['kind']}"] += 1
    for m in missing:
        col = m["column"]
        raw = cells.get((m["cid"], col), "<no source cell>")
        if col.endswith("_comment"):
            c["comment_lost"] += 1
        elif raw is None or N.is_na(raw):
            c["blank_in_file"] += 1
        else:
            c["other_missing"] += 1
    return c


def main(result_path: str):
    r = json.load(open(result_path, encoding="utf-8"))
    total = Counter()
    for case in r["cases"]:
        if "errors_all" not in case:
            sys.exit("result has no complete error lists — re-run with the current evaluation/metrics.py")
        truth = json.load(open(os.path.join(TESTDATA, case["case"], "truth.json"), encoding="utf-8"))
        c = classify(case["case"], truth, case["errors_all"], case["missing_all"])
        total.update(c)
        print(f"{case['case']:28} {dict(c)}")
    print("\nTOTAL", dict(total))
    system = total["title_prefix"] + total["comment_lost"] + sum(v for k, v in total.items() if k.startswith("other"))
    key = total["dept_code"] + total["key_rounding"] + total["blank_in_file"]
    print(f"attributable to the system: {system}   to the answer key / requirement: {key}")


if __name__ == "__main__":
    main(sys.argv[1])
