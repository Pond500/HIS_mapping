"""Fixes for the external blind set's findings (R2 titles, R4 lossy CIDs, D18 codes, R3 title dates)."""

import pytest

from app.pipeline import normalize as N
from app.pipeline.profiler import TITLE_DATE_KEY, hkey, profile_sheet, title_date
from app.pipeline.reader import Sheet


@pytest.mark.parametrize("raw,expected", [
    ("นาง/นางสาวอำไพ รุ่งเรือง", ("อำไพ", "รุ่งเรือง")),
    ("นาย/นาง สมชาย ใจดี", ("สมชาย", "ใจดี")),
    ("นางสาวมาลี  บุญมา", ("มาลี", "บุญมา")),
    ("น.ส.กนกพร ศรีสุข", ("กนกพร", "ศรีสุข")),
    ("Mr. John Smith", ("John", "Smith")),
    ("วีระ ประสิทธิ์ผล", ("วีระ", "ประสิทธิ์ผล")),
])
def test_titles_including_combined_ones(raw, expected):
    assert N.split_full_name(raw) == expected


def test_leftover_punctuation_is_not_saved_as_a_name():
    with pytest.raises(N.Unparseable):
        N.split_full_name("นาง//อำไพ รุ่งเรือง")


@pytest.mark.parametrize("raw", ["1.10046E+12", "8.51925E+12", "2.34778e+12"])
def test_lossy_scientific_cids_are_never_trusted(raw):
    assert N.cid_digits(raw) is None


def test_full_precision_scientific_cid_is_recovered():
    assert N.cid_digits("1.100500112239E+12") == "1100500112239"


@pytest.mark.parametrize("v,code", [("PROD-01", True), ("QC", True), ("MAINT", True),
                                    ("ฝ่ายผลิต", False), ("ฝ่าย ผลิต 1", False), ("OPD ชั้น 2", False)])
def test_department_code_or_name(v, code):
    assert N.looks_like_code(v) is code


def _vertical(title):
    rows = [[title, None, None],
            ["HN", "A1", "A2"],
            ["เลขบัตรประชาชน", "1100500112239", "3485739700176"],
            ["ชื่อ-สกุล", "สมชาย ใจดี", "มานพ ศรีสุข"],
            ["แผนก", "QC", "QC"],
            ["Hb", 13.5, 14.1]]
    return Sheet("s", rows)


def test_title_date_is_found_but_asked_about_first():
    sh = _vertical("ผลตรวจสุขภาพ วันที่ 8 เมษายน 2569")
    assert title_date(sh.rows, 2) == ("2026-04-08", "ผลตรวจสุขภาพ วันที่ 8 เมษายน 2569")
    spec = profile_sheet(sh, set())
    assert not spec.problems and "visit_date" in spec.missing_roles and spec.report_date is None
    assert spec.candidates[0]["header"] == TITLE_DATE_KEY and spec.candidates[0]["date"] == "2026-04-08"


def test_confirmed_title_date_is_used():
    spec = profile_sheet(_vertical("ผลตรวจสุขภาพ วันที่ 8 เมษายน 2569"), set(), {hkey(TITLE_DATE_KEY): "visit_date"})
    assert spec.report_date == "2026-04-08" and "visit_date" not in spec.missing_roles


def test_two_different_title_dates_are_not_guessed():
    sh = _vertical("ตรวจ 8 เมษายน 2569 พิมพ์ 10 เมษายน 2569")
    assert title_date(sh.rows, 2) is None
    assert profile_sheet(sh, set()).problems     # -> a profile review, never a guess
