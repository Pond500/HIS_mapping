from datetime import date, datetime

import pytest

from app.pipeline import normalize as N
from app.pipeline import units as U
from app.template import TEMPLATE_FIELDS


@pytest.mark.parametrize("raw,expected", [
    ("2026-04-08", date(2026, 4, 8)),
    ("2026-04-08 00:00:00", date(2026, 4, 8)),
    ("08/04/2026", date(2026, 4, 8)),
    ("08/04/2569", date(2026, 4, 8)),
    ("08/04/69", date(2026, 4, 8)),
    ("2569-04-08", date(2026, 4, 8)),
    ("8 เม.ย. 2569", date(2026, 4, 8)),
    ("8 เมษายน 2569", date(2026, 4, 8)),
    ("8 Apr 2026", date(2026, 4, 8)),
    (datetime(2026, 4, 8), date(2026, 4, 8)),
    (date(2569, 4, 8), date(2026, 4, 8)),
    (46120, date(2026, 4, 8)),   # Excel serial
])
def test_parse_date(raw, expected):
    assert N.parse_date(raw) == expected


@pytest.mark.parametrize("raw", ["", "31/02/2026", "tomorrow", None])
def test_parse_date_rejects(raw):
    with pytest.raises(N.Unparseable):
        N.parse_date(raw)


@pytest.mark.parametrize("raw,digits", [
    ("1100500112239", "1100500112239"),
    (1100500112239.0, "1100500112239"),
    ("1100500112239.0", "1100500112239"),
    ("1.100500112239E+12", "1100500112239"),
    ("1-1005-00112-23-9", "1100500112239"),
    ("1 1005 00112 23 9", "1100500112239"),
])
def test_cid_digits(raw, digits):
    assert N.cid_digits(raw) == digits


def test_cid_checksum():
    assert N.cid_valid("1100500112239")
    assert not N.cid_valid("1100500112233")   # the old mock CID
    assert not N.cid_valid("110050011223")


@pytest.mark.parametrize("raw,expected", [
    (7500, (7500.0, None)), ("7,500", (7500.0, None)), ("  12.3 ", (12.3, None)),
    ("13.2 g/dL", (13.2, "g/dL")), ("N/A", (None, None)), ("-", (None, None)), (None, (None, None)),
])
def test_parse_number(raw, expected):
    assert N.parse_number(raw) == expected


@pytest.mark.parametrize("raw", ["<0.1", "> 1000", "positive", "13..2"])
def test_parse_number_rejects(raw):
    with pytest.raises(N.Unparseable):
        N.parse_number(raw)


@pytest.mark.parametrize("raw,expected", [
    (1, 1), ("2", 2), ("ปกติ", 1), ("Abnormal", 2), ("WNL", 1), ("ไม่พบความผิดปกติ", 1), (None, None),
])
def test_parse_categorical(raw, expected):
    assert N.parse_categorical(raw) == expected


def test_parse_categorical_rejects_unclear():
    with pytest.raises(N.Unparseable):
        N.parse_categorical("ผิดปกติเล็กน้อย ควรติดตาม")


def test_bp():
    assert N.parse_bp("120/80") == (120, 80)
    with pytest.raises(N.Unparseable):
        N.parse_bp("6/6")          # visual acuity, not blood pressure


def test_names():
    assert N.split_full_name("นายสมชาย ใจดี") == ("สมชาย", "ใจดี")
    assert N.split_full_name("สมหญิง  วงศ์สวัสดิ์") == ("สมหญิง", "วงศ์สวัสดิ์")


def test_canonical_units_have_factor_one():
    for f in TEMPLATE_FIELDS:
        if f.kind == "numeric":
            assert U.factor(f.column, f.unit) == 1, f.column


@pytest.mark.parametrize("col,unit,f", [
    ("hb", "g/L", 0.1), ("creatinine", "µmol/L", 1 / 88.4), ("creatinine", "umol/L", 1 / 88.4),
    ("wbc", "10^3/µL", 1000), ("wbc", "x10^3/uL", 1000), ("wbc", "10^9/L", 1000),
    ("hct", "L/L", 100), ("spirometry_height", "m", 100), ("hb", None, 1.0),
])
def test_unit_factor(col, unit, f):
    assert U.factor(col, unit) == pytest.approx(f)


def test_unknown_unit_is_none():
    assert U.factor("hb", "furlongs") is None
    assert U.factor("spirometry_fvc", "%") is None   # % on a litres column: not a unit problem to guess
