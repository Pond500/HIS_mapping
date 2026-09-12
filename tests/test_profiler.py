"""The rules profiler on every dev file (dev set only — never exam)."""

import json
import os

import pytest

from app.pipeline.profiler import hkey, profile_sheet
from app.pipeline.reader import read_file
from testgen.build import ROOT
from testgen.cases import DEV

ID_ROLES = {"cid", "first_name", "last_name", "full_name", "department_id", "visit_date"}
UPLOADS = [(c.name, u) for c in DEV
           for u in json.load(open(os.path.join(ROOT, "dev", c.name, "truth.json"), encoding="utf-8"))["uploads"]]


def _sheets(case, up):
    path = os.path.join(ROOT, "dev", case, up["file"])
    return read_file(open(path, "rb").read(), path.rsplit(".", 1)[1])


def _roles(sh, spec):
    if spec.layout == "transposed":
        return {role: str(sh.rows[r][0]) for role, r in spec.id_cols.items()}
    return {role: str(sh.rows[spec.header_row][c]) for role, c in spec.id_cols.items()}


@pytest.mark.parametrize("case,up", UPLOADS, ids=[f"{c}/{u['file']}" for c, u in UPLOADS])
def test_identity_roles(case, up):
    """Every identity column is either found correctly, or reported missing (never silently skipped)."""
    expected = {role: h for h, role in up["headers"].items() if role in ID_ROLES}
    unknown_on_purpose = set(up["style"].get("id_headers", {})) - {"cid", "visit_date", "lab_name", "result", "unit"}
    for sh in _sheets(case, up):
        spec = profile_sheet(sh, set())
        assert spec.layout == up["style"]["layout"], sh.name
        assert not spec.problems
        got = _roles(sh, spec)
        for role, h in got.items():
            assert expected.get(role) == h, (sh.name, role)          # nothing found is wrong
        missing = {r for r in expected if r not in got}
        for role in missing:
            assert role in spec.missing_roles, (sh.name, role)        # ...and nothing is dropped silently
            if spec.layout != "transposed":
                assert expected[role] in [c["header"] for c in spec.candidates]
        # the default aliases find everything except headers a case made unknown on purpose
        assert missing <= unknown_on_purpose, (sh.name, missing)


def test_confirmed_identity_headers_are_used():
    """After a reviewer confirms 'ชื่อ (ไทย)' = first_name for a hospital, the profiler reads it."""
    case = "d19_unknown_name_headers_long"
    up = next(u for c, u in UPLOADS if c == case)
    aliases = {hkey("ชื่อ (ไทย)"): "first_name", hkey("นามสกุล (ไทย)"): "last_name"}
    for sh in _sheets(case, up):
        spec = profile_sheet(sh, set(), aliases)
        assert {"first_name", "last_name"} <= set(spec.id_cols) and not spec.missing_roles
