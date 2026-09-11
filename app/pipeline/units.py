"""
units.py
========
Unit conversion to the canonical units in app/template.py.

Standard clinical conversions only (general lab knowledge, not tuned to any
test file). An unknown unit string is never guessed: the caller flags it.
"""

import re

# column -> {normalized unit: factor to canonical}
_TO_CANON = {
    "hb": {"g/dl": 1, "g/l": 0.1, "mmol/l": 1.611},
    "hct": {"%": 1, "l/l": 100, "fraction": 100},
    "wbc": {"cells/µl": 1, "/µl": 1, "cells/mm3": 1, "/mm3": 1, "10^3/µl": 1000, "10^9/l": 1000, "x10^3": 1000,
            "k/µl": 1000, "10^3/mm3": 1000},
    "plt": {"cells/µl": 1, "/µl": 1, "cells/mm3": 1, "/mm3": 1, "10^3/µl": 1000, "10^9/l": 1000, "x10^3": 1000,
            "k/µl": 1000, "10^3/mm3": 1000},
    "creatinine": {"mg/dl": 1, "µmol/l": 1 / 88.4},
    "uric_acid": {"mg/dl": 1, "µmol/l": 1 / 59.48, "mmol/l": 1000 / 59.48},
    "tb": {"mg/dl": 1, "µmol/l": 1 / 17.1},
    "db": {"mg/dl": 1, "µmol/l": 1 / 17.1},
    "venous_blood_lead": {"µg/dl": 1, "µg/l": 0.1, "µmol/l": 1 / 0.0483},
    "spirometry_height": {"cm": 1, "m": 100},
    "spirometry_fvc": {"l": 1, "ml": 0.001},
    "spirometry_fev1": {"l": 1, "ml": 0.001},
    "bmi": {"kg/m²": 1, "kg/m2": 1},
    "sgot_ast": {"u/l": 1, "iu/l": 1}, "sgpt_alt": {"u/l": 1, "iu/l": 1}, "alp": {"u/l": 1, "iu/l": 1},
    "rbc_che": {"u/l": 1, "iu/l": 1}, "plasma_che_bche": {"u/l": 1, "iu/l": 1},
    "bp_systolic": {"mmhg": 1}, "bp_diastolic": {"mmhg": 1}, "pulse_rate": {"bpm": 1, "/min": 1, "ครั้ง/นาที": 1},
}
for _c in ("neutrophil", "lymphocyte", "monocyte", "eosinophil", "basophil", "spirometry_fev1_fvc"):
    _TO_CANON[_c] = {"%": 1}
for _c in ("spirometry_fvc_percent", "spirometry_fev1_percent"):
    _TO_CANON[_c] = {"% predicted": 1, "%pred": 1, "% pred": 1, "%": 1, "%predicted": 1}


def norm_unit(u: str | None) -> str | None:
    if u is None:
        return None
    s = str(u).strip().lower()
    if not s:
        return None
    s = s.replace("μ", "µ")
    s = re.sub(r"\s+", "", s) if not s.startswith("%") else re.sub(r"\s+", " ", s)
    s = s.replace("umol", "µmol").replace("ug/", "µg/").replace("/ul", "/µl").replace("mcg/", "µg/")
    s = s.replace("×", "x").replace("x10^3/µl", "10^3/µl").replace("x10³/µl", "10^3/µl").replace("10³", "10^3")
    s = s.replace("x10^9/l", "10^9/l").replace("10⁹", "10^9").replace("10e3", "10^3").replace("10e9", "10^9")
    s = s.replace("k/ul", "k/µl")
    return s


def factor(column: str, unit: str | None) -> float | None:
    """
    Factor that converts a value in `unit` to the canonical unit of `column`.
    1.0 when unit is absent (caller must then range-check). None = unknown unit.
    """
    u = norm_unit(unit)
    if u is None:
        return 1.0
    table = _TO_CANON.get(column)
    if table is None:
        return 1.0 if u in ("", "-") else None
    return table.get(u)
