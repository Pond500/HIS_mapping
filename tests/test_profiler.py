"""The rules profiler finds the identity columns of every dev file (dev set only — never exam)."""

import json
import os

import pytest

from app.pipeline.profiler import profile_sheet
from app.pipeline.reader import read_file
from testgen.build import ROOT
from testgen.cases import DEV

ID_ROLES = {"cid", "first_name", "last_name", "full_name", "department_id", "visit_date"}
UPLOADS = [(c.name, u) for c in DEV
           for u in json.load(open(os.path.join(ROOT, "dev", c.name, "truth.json"), encoding="utf-8"))["uploads"]]


@pytest.mark.parametrize("case,up", UPLOADS, ids=[f"{c}/{u['file']}" for c, u in UPLOADS])
def test_identity_roles(case, up):
    path = os.path.join(ROOT, "dev", case, up["file"])
    sheets = read_file(open(path, "rb").read(), path.rsplit(".", 1)[1])
    expected = {role: h for h, role in up["headers"].items() if role in ID_ROLES}
    for sh in sheets:
        spec = profile_sheet(sh, set())
        assert spec.layout == up["style"]["layout"], sh.name
        assert not spec.problems
        if spec.layout == "transposed":
            got = {role: str(sh.rows[r][0]) for role, r in spec.id_cols.items()}
        else:
            got = {role: str(sh.rows[spec.header_row][c]) for role, c in spec.id_cols.items()}
        assert got == expected, sh.name
