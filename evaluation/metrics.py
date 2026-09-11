"""
metrics.py
==========
Scores the DB state after a case against the case truth.

Every expected cell (cid, visit_date, column) ends up in exactly one bucket:

  correct         stored and equal to the truth
  wrong           stored but different                  -> silent error (breaks the core rule)
  missing_flagged not stored, but a human was asked     -> fine: "flagged for a human"
  missing_silent  not stored and nobody was told        -> silent data loss

plus, for cells stored that the truth does not expect at all:

  spurious        e.g. RBC saved as wbc, a row with an invalid CID saved,
                  "<0.1" saved as 0.1                   -> silent error

How the pipeline signals "a human was asked" (pending_reviews, status open):
  kind "value" / "comment"  payload {cid, visit_date, column}
  kind "mapping"            payload {label}  (label = lab name or header as in the file)
  kind "profile"            whole file waits for a human
  kind "cid"                payload {raw_cid}
A file with status "awaiting_review" also counts as flagged as a whole.
"""

import re
from collections import Counter

from app.template import FIELDS_BY_COLUMN

PERSON_FIELDS = ("first_name", "last_name", "department_id")
NUM_TOL = 0.006   # values are stored at 2 decimals; factors can round by one unit


def _digits(x):
    return re.sub(r"\D", "", str(x).split(".")[0] if re.fullmatch(r"\d+\.0+", str(x)) else str(x))


def equal(col, got, exp) -> bool:
    kind = FIELDS_BY_COLUMN[col].kind
    if kind in ("numeric", "categorical"):
        try:
            return abs(float(got) - float(exp)) <= NUM_TOL
        except (TypeError, ValueError):
            return False
    return str(got).strip() == str(exp).strip()


def score_case(truth: dict, state: dict) -> dict:
    """
    state = {
      "upload_ids": [source_file_id per upload, in order],
      "values":  {(cid, date): {column: value}},        # employees, non-null cells
      "conflicts": {(cid, date, column)},                # open or resolved
      "reviews": [{"kind", "source_file_id", "payload"}] # open pending_reviews
      "awaiting_files": {source_file_id},                # status awaiting_review
      "extras": [{"cid", "visit_date", "name", "value"}],
    }
    """
    uploads = truth["uploads"]
    idx_of_file = {fid: i for i, fid in enumerate(state["upload_ids"])}

    # which upload each expected record first came from
    first_upload = {}
    for i, up in enumerate(uploads):
        for rec in up["records"]:
            first_upload.setdefault((rec["cid"], rec["visit_date"]), i)

    # flagged cells / columns / uploads
    flagged_cells, flagged_cols, flagged_uploads, flagged_cids = set(), set(), set(), set()
    for fid in state["awaiting_files"]:
        if fid in idx_of_file:
            flagged_uploads.add(idx_of_file[fid])
    for r in state["reviews"]:
        p, i = r["payload"] or {}, idx_of_file.get(r["source_file_id"])
        if r["kind"] in ("value", "comment") and "column" in p:
            flagged_cells.add((str(p.get("cid")), str(p.get("visit_date")), p["column"]))
        elif r["kind"] == "mapping" and i is not None:
            info = uploads[i]["lab_names"].get(p.get("label"))
            if info:
                targets = ["bp_systolic", "bp_diastolic"] if info["target"] == "__bp__" else [info["target"]]
                flagged_cols.update((i, t) for t in targets)
        elif r["kind"] == "profile" and i is not None:
            flagged_uploads.add(i)
        elif r["kind"] == "cid":
            flagged_cids.add(_digits(p.get("raw_cid", "")))

    derived = {(d["cid"], d["visit_date"], d["column"]) for d in truth["derived"]}
    b = Counter()
    per_upload = [Counter() for _ in uploads]
    errors = []   # examples of silent errors, for debugging
    missing = []  # examples of silent drops

    expected_keys = {}
    for rec in truth["expected"]:
        key = (rec["cid"], rec["visit_date"])
        cells = {c: rec[c] for c in PERSON_FIELDS if rec.get(c) is not None}
        cells.update(rec["values"])
        expected_keys[key] = cells
        up = first_upload.get(key, 0)
        got_row = state["values"].get(key, {})
        for col, exp in cells.items():
            got = got_row.get(col)
            if got is not None:
                bucket = "correct" if equal(col, got, exp) else "wrong"
                if bucket == "wrong":
                    errors.append({"kind": "wrong", "cid": key[0], "date": key[1], "column": col,
                                   "got": str(got), "expected": exp})
            elif (key[0], key[1], col) in flagged_cells or (up, col) in flagged_cols or up in flagged_uploads:
                bucket = "missing_flagged"
            else:
                bucket = "missing_silent"
                missing.append({"cid": key[0], "date": key[1], "column": col, "expected": exp})
            b[bucket] += 1
            per_upload[up][bucket] += 1
            if (key[0], key[1], col) in derived:
                b[f"derived_{bucket}"] += 1

    for key, row in state["values"].items():
        for col, got in row.items():
            if col not in expected_keys.get(key, {}):
                b["spurious"] += 1
                errors.append({"kind": "spurious", "cid": key[0], "date": key[1], "column": col, "got": str(got)})

    exp_conf = {(c["cid"], c["visit_date"], c["column"]) for c in truth["conflicts"]}
    inv = [f for f in truth["flagged"] if f["kind"] == "invalid_cid"]
    cens = [f for f in truth["flagged"] if f["kind"] == "censored"]
    got_extras = {(e["cid"], e["visit_date"], str(e["name"]).strip().lower()) for e in state["extras"]}
    exp_extras = {(e["cid"], e["visit_date"], str(e["name"]).strip().lower()) for e in truth["extras"]}

    expected_total = sum(b[k] for k in ("correct", "wrong", "missing_flagged", "missing_silent"))
    return {
        "case": truth["case"],
        "buckets": dict(b),
        "expected_cells": expected_total,
        "per_upload": [dict(c) for c in per_upload],
        "conflicts": {"expected": len(exp_conf), "found": len(exp_conf & state["conflicts"])},
        "invalid_cid": {"expected": len(inv), "flagged": sum(_digits(f["raw_cid"]) in flagged_cids for f in inv)},
        "censored": {"expected": len(cens),
                     "flagged": sum((f["cid"], f["visit_date"], f["column"]) in flagged_cells for f in cens)},
        "extras": {"expected": len(exp_extras), "found": len(exp_extras & got_extras)},
        "error_examples": errors[:15],
        "missing_examples": missing[:15],
        "missing_by_column": dict(Counter(m["column"] for m in missing).most_common(8)),
    }


def headline(results: list[dict], repeat_uploads: set[tuple[str, int]]) -> dict:
    b = Counter()
    for r in results:
        b.update(r["buckets"])
    stored = b["correct"] + b["wrong"] + b["spurious"]
    expected = b["correct"] + b["wrong"] + b["missing_flagged"] + b["missing_silent"]
    rep = Counter()
    for r in results:
        for i, pu in enumerate(r["per_upload"]):
            if (r["case"], i) in repeat_uploads:
                rep.update(pu)
    rep_exp = sum(rep[k] for k in ("correct", "wrong", "missing_flagged", "missing_silent"))

    def total(key, sub):
        return sum(r[key][sub] for r in results)

    return {
        "auto_precision": b["correct"] / stored if stored else None,        # target >= 0.995
        "automation": b["correct"] / expected if expected else None,        # target >= 0.70
        "automation_repeat": rep["correct"] / rep_exp if rep_exp else None,  # target >= 0.95
        "silent_errors": b["wrong"] + b["spurious"],                        # target 0
        "silent_drops": b["missing_silent"],
        "flagged_for_human": b["missing_flagged"],
        "expected_cells": expected,
        "conflicts_found": f'{total("conflicts", "found")}/{total("conflicts", "expected")}',
        "invalid_cid_flagged": f'{total("invalid_cid", "flagged")}/{total("invalid_cid", "expected")}',
        "censored_flagged": f'{total("censored", "flagged")}/{total("censored", "expected")}',
        "extras_found": f'{total("extras", "found")}/{total("extras", "expected")}',
        "buckets": dict(b),
    }
