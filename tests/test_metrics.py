"""Scoring rules for the evaluation harness (evaluation/metrics.py)."""

from evaluation.metrics import score_case

TRUTH = {
    "case": "t",
    "uploads": [{"records": [{"cid": "1", "visit_date": "2026-01-01"}],
                 "lab_names": {"Hb (g/L)": {"target": "hb", "factor": 0.1}}}],
    "expected": [{"cid": "1", "visit_date": "2026-01-01", "first_name": "ก",
                  "values": {"hb": 13.5, "wbc": 7000.0}}],
    "conflicts": [], "flagged": [], "extras": [], "derived": [],
}
KEY = ("1", "2026-01-01")


def state(values, reviews=(), awaiting=()):
    return {"upload_ids": [10], "values": values, "conflicts": set(), "reviews": list(reviews),
            "awaiting_files": set(awaiting), "extras": []}


def test_all_correct():
    r = score_case(TRUTH, state({KEY: {"first_name": "ก", "hb": 13.5, "wbc": 7000}}))
    assert r["buckets"] == {"correct": 3}


def test_wrong_and_silent_drop():
    r = score_case(TRUTH, state({KEY: {"first_name": "ก", "hb": 135}}))
    assert r["buckets"] == {"correct": 1, "wrong": 1, "missing_silent": 1}


def test_mapping_review_counts_as_flagged():
    rev = {"kind": "mapping", "source_file_id": 10, "payload": {"label": "Hb (g/L)"}}
    r = score_case(TRUTH, state({KEY: {"first_name": "ก", "wbc": 7000}}, reviews=[rev]))
    assert r["buckets"] == {"correct": 2, "missing_flagged": 1}


def test_spurious_cell_and_row():
    r = score_case(TRUTH, state({KEY: {"first_name": "ก", "hb": 13.5, "wbc": 7000, "plt": 5},
                                 ("9", "2026-01-01"): {"hb": 12}}))
    assert r["buckets"]["spurious"] == 2


def test_rounding_tolerance():
    r = score_case(TRUTH, state({KEY: {"first_name": "ก", "hb": 13.504, "wbc": 7000.005}}))
    assert r["buckets"] == {"correct": 3}
