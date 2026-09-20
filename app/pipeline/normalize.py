"""
normalize.py
============
Pure value parsers. Each returns a parsed value, or raises Unparseable
(with a Thai reason) when the value must go to a human instead of being
guessed.
"""

import re
from datetime import date, datetime, timedelta

TH_MONTHS = {m: i + 1 for i, m in enumerate(
    ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."])}
TH_MONTHS_FULL = {m: i + 1 for i, m in enumerate(
    ["มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
     "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"])}
EN_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}

NA_TOKENS = {"", "-", "--", "n/a", "na", "nan", "none", "null", "ไม่มี", "ไม่ได้ตรวจ", "nd", "."}
# one title, or a combined one as HIS exports write it when unsure ("นาง/นางสาว", "นาย/นาง")
_TITLE = r"(?:นางสาว|น\.ส\.|เด็กชาย|เด็กหญิง|ด\.ช\.|ด\.ญ\.|นาย|นาง|(?:mrs|mr|ms|miss)\.?(?=[\s/]))"
_TITLES_RE = re.compile(rf"^\s*{_TITLE}(?:\s*/\s*{_TITLE})*\s*", re.I)


class Unparseable(ValueError):
    """Value can't be read safely — send it to a human."""


def is_na(v) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and v != v:  # NaN
        return True
    return isinstance(v, str) and v.strip().lower() in NA_TOKENS


def text(v) -> str | None:
    if is_na(v):
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return re.sub(r"\s+", " ", str(v)).strip() or None


# ---------------------------------------------------------------------------
# CID
# ---------------------------------------------------------------------------


def cid_digits(v) -> str | None:
    """Digits of a CID as written: handles floats (1.1e12), dashes, spaces."""
    if is_na(v):
        return None
    if isinstance(v, float):
        return str(int(round(v))) if v.is_integer() or abs(v) >= 1e11 else None
    if isinstance(v, int):
        return str(v)
    s = str(v).strip()
    if re.fullmatch(r"\d+\.0+", s):
        s = s.split(".")[0]
    m = re.fullmatch(r"(\d)(?:\.(\d+))?[eE]\+?(\d+)", s)   # "1.100500112239E+12" from a CSV
    if m:
        # Excel's "1.10046E+12" dropped digits: the real CID can't be recovered, whatever its checksum says
        if 1 + len(m.group(2) or "") < 13:
            return None
        return str(int(float(s)))
    d = re.sub(r"[\s\-]", "", s)
    return d if d.isdigit() else None


def cid_valid(d: str | None) -> bool:
    if not d or len(d) != 13 or not d.isdigit():
        return False
    s = sum(int(x) * (13 - i) for i, x in enumerate(d[:12]))
    return (11 - s % 11) % 10 == int(d[12])


def looks_like_code(v) -> bool:
    """A department value that is already a code ("PROD-01", "QC"), not a name ("ฝ่ายผลิต")."""
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_\-.]{0,19}", str(v).strip()))


def looks_like_cid(v) -> bool:
    d = cid_digits(v)
    return bool(d) and len(d) == 13


# ---------------------------------------------------------------------------
# Dates (CE / BE, many formats)
# ---------------------------------------------------------------------------


def _be_to_ce(y: int) -> int:
    if y > 2400:
        return y - 543
    if y < 100:  # two-digit year: Thai files use BE (69 -> 2569); CE 20xx otherwise
        return (2500 + y - 543) if y >= 40 else 2000 + y
    return y


def parse_date(v) -> date:
    if isinstance(v, datetime):
        return _fix_year(v.date())
    if isinstance(v, date):
        return _fix_year(v)
    if isinstance(v, (int, float)) and 20000 < v < 80000:   # Excel serial
        return (datetime(1899, 12, 30) + timedelta(days=float(v))).date()
    if is_na(v):
        raise Unparseable("ไม่มีวันที่")
    s = re.sub(r"\s+", " ", str(v).strip())
    s = re.sub(r"[ T]\d{1,2}:\d{2}(:\d{2})?(\.\d+)?$", "", s)   # drop a time part

    m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s)
    if m:
        y, mo, d = map(int, m.groups())
        return _mk(_be_to_ce(y), mo, d, s)
    m = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2}|\d{4})", s)
    if m:
        d, mo, y = map(int, m.groups())
        return _mk(_be_to_ce(y), mo, d, s)
    m = re.fullmatch(r"(\d{1,2})\s*([^\d\s]+)\s*(\d{2}|\d{4})", s)
    if m:
        d, mname, y = m.groups()
        key = mname.strip().lower()
        mo = TH_MONTHS.get(mname) or TH_MONTHS.get(mname + ".") or TH_MONTHS_FULL.get(mname) \
            or EN_MONTHS.get(key[:3])
        if mo:
            return _mk(_be_to_ce(int(y)), mo, int(d), s)
    raise Unparseable(f"อ่านวันที่ไม่ได้: {s}")


def _fix_year(d: date) -> date:
    return d.replace(year=d.year - 543) if d.year > 2400 else d


def _mk(y, mo, d, raw):
    try:
        return date(y, mo, d)
    except ValueError:
        raise Unparseable(f"วันที่ไม่ถูกต้อง: {raw}")


def looks_like_date(v) -> bool:
    if isinstance(v, (datetime, date)):
        return True
    if isinstance(v, (int, float)):
        return False   # bare numbers are results, not dates, unless typed as dates
    try:
        parse_date(v)
        return True
    except Unparseable:
        return False


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------

_NUM = r"[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|[-+]?\d+(?:\.\d+)?|[-+]?\.\d+"


def parse_number(v) -> tuple[float | None, str | None]:
    """
    Returns (number, inline unit). None number = empty/NA.
    Raises Unparseable for censored ("<0.1", ">1000") or non-numeric text.
    """
    if is_na(v):
        return None, None
    if isinstance(v, bool):
        raise Unparseable("ไม่ใช่ตัวเลข")
    if isinstance(v, (int, float)):
        return float(v), None
    s = str(v).strip()
    if re.match(r"^[<>≤≥]=?\s*\d", s):
        raise Unparseable(f"ค่าไม่ใช่ตัวเลขที่แน่นอน ({s})")
    # an inline unit must start like a unit (letter, %, µ, °, /, x) — "13..2" is not "13" + "..2"
    m = re.fullmatch(rf"({_NUM})\s*([A-Za-zµμ%°/\u0E00-\u0E7F][^\n]*)?", s)
    if not m:
        raise Unparseable(f"ไม่ใช่ตัวเลข: {s}")
    return float(m.group(1).replace(",", "")), (m.group(2) or None)


# ---------------------------------------------------------------------------
# Categorical (1 = ปกติ, 2 = ผิดปกติ)
# ---------------------------------------------------------------------------

NORMAL = {"1", "ปกติ", "normal", "n", "wnl", "within normal limit", "within normal limits", "negative", "neg",
          "ไม่พบความผิดปกติ", "เหมาะสม", "ok", "nad", "no abnormality detected"}
ABNORMAL = {"2", "ผิดปกติ", "abnormal", "ab", "abn", "พบความผิดปกติ", "อาจไม่เหมาะสม", "ไม่เหมาะสม",
            "ไม่ปกติ", "positive", "pos"}


def parse_categorical(v) -> int | None:
    if is_na(v):
        return None
    if isinstance(v, (int, float)) and float(v) in (1.0, 2.0):
        return int(v)
    s = re.sub(r"\s+", " ", str(v).strip().lower())
    if s in NORMAL:
        return 1
    if s in ABNORMAL:
        return 2
    raise Unparseable(f"ไม่แน่ใจว่าเป็นปกติหรือผิดปกติ: {v}")


def norm_comment(v) -> str:
    """Key for a free-text finding: lowercase, single spaces."""
    return re.sub(r"\s+", " ", str(v)).strip().lower()


def parse_bp(v) -> tuple[float, float] | None:
    if is_na(v):
        return None
    m = re.fullmatch(r"\s*(\d{2,3})\s*/\s*(\d{2,3})\s*(mmhg)?\s*", str(v).lower())
    if not m:
        raise Unparseable(f"อ่านค่าความดันไม่ได้: {v}")
    s, d = float(m.group(1)), float(m.group(2))
    if d >= s:
        raise Unparseable(f"ค่าความดันตัวล่างไม่น้อยกว่าตัวบน: {v}")
    return s, d


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------


def strip_title(name: str) -> str:
    return _TITLES_RE.sub("", name, count=1).strip()


def _check_name(n: str | None) -> str | None:
    if n is not None and not re.match(r"[A-Za-z\u0E00-\u0E7F]", n):
        raise Unparseable(f"อ่านชื่อไม่ได้แน่ชัด: {n}")
    return n


def clean_name(v) -> str | None:
    """A single name cell: title removed; raises Unparseable if what's left doesn't look like a name."""
    s = text(v)
    return _check_name(strip_title(s) or None) if s else None


def split_full_name(v) -> tuple[str | None, str | None]:
    s = text(v)
    if not s:
        return None, None
    parts = strip_title(s).split(" ", 1)
    first = parts[0] or None
    last = parts[1].strip() if len(parts) > 1 else None
    return _check_name(first), _check_name(last)


def same_value(kind: str, a, b) -> bool:
    """Is this the same answer, written two ways?

    Numeric fields are compared as numbers. Decimal("14.20") and 14.2 are one
    value, and treating them as different has bitten this project twice: once it
    sent reviewers questions with no difference in them, and once it filled the
    audit trail of manual edits with changes that never happened.
    """
    if a is None or b is None:
        return a is None and b is None
    if kind in ("numeric", "categorical"):
        try:
            return abs(float(a) - float(b)) < 0.005
        except (TypeError, ValueError):
            pass
    return str(a).strip() == str(b).strip()
