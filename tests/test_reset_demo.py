"""
scripts/reset_demo.py against a scratch database.

It stopped working when the schema was rebuilt (D23): run afterwards it raised a
foreign-key error on the hospitals that accounts and rounds still pointed at and, being one
transaction, cleaned nothing. This runs it on a database with a workplace, a round, a
result and a hand-over in it, so the next schema change that outgrows it fails here and not
the day before the demo.
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_reset_demo_empties_the_data_and_keeps_what_it_promises():
    code = r'''
import os, sys
sys.path.insert(0, ".")
from scenarios.harness import Harness, Scenario, cid, csv_bytes
h = Harness(); h.build_database(); h.boot(); h.reset()
s = Scenario(h)
s.default_people()
s.results([["เลขบัตรประชาชน", "ชื่อ-สกุล", "hb"], [cid(1), "ก ข", 14.0]])
s.sa.post("/api/summary/submit", json={"round_id": s.r1})
h.sql("select 1")
assert h.scalar("select count(*) from employee_checkups") == 1

from sqlalchemy import text
from scripts.reset_demo import reset
with h.SessionLocal() as db:
    reset(db); db.commit()

for t in ("companies", "departments", "employees", "employee_checkups", "employee_checkup_batches",
          "walkthrough_surveys", "source_files", "pending_reviews", "report_submissions", "extra_results"):
    n = h.scalar(f"select count(*) from {t}")
    assert n == 0, f"{t} still has {n} rows"
assert h.scalar("select count(*) from lab_mappings where hospital_id is not null") == 0
assert h.scalar("select count(*) from lab_mappings where hospital_id is null") > 0, "the seeded dictionary must stay"
assert h.scalar("select count(*) from employee_checkup_types") > 0, "seeded checkup types must stay"
assert h.scalar("select count(*) from app_users") == 2, "accounts must stay"
print("OK")
'''
    run = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert run.returncode == 0 and "OK" in run.stdout, (run.stdout[-800:], run.stderr[-1500:])
