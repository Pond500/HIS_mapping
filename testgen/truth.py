"""
truth.py
========
Generates the ground truth: synthetic people and their results in the
canonical units of app/template.py. Renderers turn these into files.
"""

import random
from dataclasses import dataclass, field
from datetime import date, timedelta

from testgen import vocab

# typical (not plausible) ranges in canonical units, and display decimals
TYPICAL = {
    "venous_blood_lead": (2, 45, 1),
    "wbc": (3800, 11500, 0),
    "hb": (10.5, 17.5, 1),
    "hct": (32, 52, 1),
    "plt": (150000, 420000, 0),
    "neutrophil": (40, 75, 1),
    "lymphocyte": (18, 45, 1),
    "monocyte": (2, 10, 1),
    "eosinophil": (0, 8, 1),
    "basophil": (0, 2, 1),
    "creatinine": (0.5, 1.6, 2),
    "sgot_ast": (12, 70, 0),
    "sgpt_alt": (8, 90, 0),
    "alp": (40, 150, 0),
    "tb": (0.2, 1.8, 2),
    "uric_acid": (2.8, 8.9, 1),
    "rbc_che": (7000, 12500, 0),
    "plasma_che_bche": (3500, 12500, 0),
    "bmi": (17.5, 36, 1),
    "bp_systolic": (98, 165, 0),
    "pulse_rate": (52, 105, 0),
    "spirometry_fvc_percent": (65, 118, 1),
    "spirometry_fev1_percent": (60, 118, 1),
    "spirometry_fvc": (2.2, 5.4, 2),
    "spirometry_height": (148, 184, 1),
}

EXTRA_VALUES = {
    "fbs": (72, 135, 0), "chol": (140, 270, 0), "hba1c": (4.6, 7.8, 1),
    "rbc": (3.9, 6.1, 2), "ibil": (0.1, 1.2, 2), "neut_abs": (1.6, 7.8, 2),
    "lymph_abs": (1.0, 4.2, 2), "tg": (45, 320, 0), "ldl": (65, 195, 0),
    "mcv": (74, 99, 1),
}


def cid_checksum(first12: str) -> int:
    s = sum(int(d) * (13 - i) for i, d in enumerate(first12))
    return (11 - s % 11) % 10


def make_cid(rng: random.Random) -> str:
    first12 = str(rng.randint(1, 8)) + "".join(str(rng.randint(0, 9)) for _ in range(11))
    return first12 + str(cid_checksum(first12))


def corrupt_cid(cid: str, rng: random.Random) -> str:
    """Change one digit so the checksum fails (a typical typing error)."""
    while True:
        i = rng.randint(1, 11)
        bad = cid[:i] + str((int(cid[i]) + rng.randint(1, 9)) % 10) + cid[i + 1:]
        if cid_checksum(bad[:12]) != int(bad[12]):
            return bad


@dataclass
class Record:
    cid: str
    first_name: str
    last_name: str
    department_id: str
    visit_date: date
    values: dict = field(default_factory=dict)   # template column -> canonical value
    extras: dict = field(default_factory=dict)   # extra key -> value


def _u(rng, lo, hi, dp):
    v = rng.uniform(lo, hi)
    return round(v, dp) if dp else float(round(v))


def make_values(rng: random.Random, missing_rate: float = 0.04) -> dict:
    v = {col: _u(rng, *TYPICAL[col]) for col in TYPICAL}
    v["db"] = round(v["tb"] * rng.uniform(0.1, 0.35), 2)
    v["bp_diastolic"] = float(round(v["bp_systolic"] * rng.uniform(0.55, 0.7)))
    v["spirometry_fev1"] = round(v["spirometry_fvc"] * rng.uniform(0.68, 0.88), 2)
    v["spirometry_fev1_fvc"] = round(v["spirometry_fev1"] / v["spirometry_fvc"] * 100, 1)
    v["hct"] = round(v["hb"] * rng.uniform(2.8, 3.1), 1)

    for col, cmt_col in [("chest_xray", "xray_comment"), ("ekg", "ekg_comment"),
                         ("hearing_ability", "hearing_comment"), ("far_vision_test", "far_vision_comment")]:
        v[col] = 1 if rng.random() < 0.82 else 2
        v[cmt_col] = None  # filled by the renderer from the vocab pool of its set
    if v["chest_xray"] == 2 and rng.random() < 0.5:
        v["profusion"] = rng.choice(["0/1", "1/0", "1/1"])
        v["primary_lesion"] = rng.choice(["p", "q", "r"])
        v["secondary_lesion"] = rng.choice(["p", "q", "s", None])
    else:
        v["profusion"] = v["primary_lesion"] = v["secondary_lesion"] = None

    for col in list(v):
        if v[col] is not None and rng.random() < missing_rate and col not in ("db", "bp_diastolic"):
            v[col] = None
    return v


def make_records(rng: random.Random, n: int, visit_range=(date(2026, 1, 5), date(2026, 8, 28))) -> list[Record]:
    span = (visit_range[1] - visit_range[0]).days
    out = []
    for _ in range(n):
        out.append(Record(
            cid=make_cid(rng),
            first_name=rng.choice(vocab.FIRST_NAMES),
            last_name=rng.choice(vocab.LAST_NAMES),
            department_id=rng.choice(vocab.DEPARTMENTS),
            visit_date=visit_range[0] + timedelta(days=rng.randint(0, span)),
            values=make_values(rng),
            extras={k: _u(rng, *r) for k, r in EXTRA_VALUES.items()},
        ))
    return out
