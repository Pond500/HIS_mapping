"""Learned meanings of findings fill the category column; unknown findings go to a human (no DB)."""

import json
import os

from app.pipeline import normalize as N
from app.pipeline.extract import extract
from app.pipeline.mapper import Mapper, _TemplateName
from app.pipeline.profiler import profile_sheet
from app.pipeline.reader import read_file
from app.template import RESULT_COLUMNS
from testgen.build import ROOT

CASE = os.path.join(ROOT, "dev", "d10_comment_only")


def _mapper():
    m = Mapper.__new__(Mapper)
    m.hospital, m.identity = {}, {}
    m.central = {(c, None): _TemplateName(c) for c in RESULT_COLUMNS}
    # the file's own labels for this case are known dictionary names
    truth = json.load(open(os.path.join(CASE, "truth.json"), encoding="utf-8"))
    for label, info in truth["uploads"][0]["lab_names"].items():
        m.central[(label.strip().lower(), None)] = _TemplateName(info["target"])
    return m, truth


def _run(labels):
    m, truth = _mapper()
    up = truth["uploads"][0]
    path = os.path.join(CASE, up["file"])
    sheets = read_file(open(path, "rb").read(), "xlsx")
    specs = [profile_sheet(s, m.known_labels()) for s in sheets]
    return extract(sheets, specs, m, comment_labels=labels), truth


def test_unknown_findings_become_comment_reviews():
    ex, truth = _run({})
    assert sum(1 for r in ex.reviews if r["kind"] == "comment") == len(truth["derived"])


def test_learned_findings_fill_the_category_column_correctly():
    ex0, truth = _run({})
    expected = {(r["cid"], r["visit_date"]): r["values"] for r in truth["expected"]}
    # teach every finding its true meaning
    labels = {}
    for r in ex0.reviews:
        if r["kind"] == "comment":
            p = r["payload"]
            labels[(p["column"], N.norm_comment(p["text"]))] = expected[(p["cid"], p["visit_date"])][p["column"]]
    ex, _ = _run(labels)
    assert not [r for r in ex.reviews if r["kind"] == "comment"]
    filled = 0
    for (cid, vd), row in ex.rows.items():
        for col in ("chest_xray", "ekg", "hearing_ability", "far_vision_test"):
            if col in row["cells"]:
                assert row["cells"][col][0] == expected[(cid, vd)][col]
                filled += 1
    assert filled == len(truth["derived"])
