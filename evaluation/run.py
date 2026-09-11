"""
run.py
======
Runs a system under test (SUT) over a test set and scores it.

    .venv/bin/python -m evaluation.run --sut baseline --set dev
    .venv/bin/python -m evaluation.run --sut baseline --set dev --case d08_extras_traps -v
    .venv/bin/python -m evaluation.run --sut baseline --set exam     # reporting only — never tune on exam

Uses a separate database (his_mapping_eval, or EVAL_DATABASE_URL), wiped
before every case. Results go to evaluation/results/<set>_<sut>_<time>.json.
"""

import argparse
import json
import os
import sys
import time

from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT, ".env"))
BASE_URL = os.environ["DATABASE_URL"]
EVAL_URL = os.environ.get("EVAL_DATABASE_URL") or BASE_URL.rsplit("/", 1)[0] + "/his_mapping_eval"
# must happen before any app.* import: app.database reads DATABASE_URL at import time
os.environ["DATABASE_URL"] = EVAL_URL
os.environ.setdefault("STORAGE_DIR", os.path.join(ROOT, "storage", "eval_uploads"))

import psycopg  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import Conflict, Employee, ExtraResult, PendingReview, SourceFile  # noqa: E402
from app.template import TEMPLATE_FIELDS  # noqa: E402
from evaluation.metrics import headline, score_case  # noqa: E402
from testgen.build import ROOT as TESTDATA, verify  # noqa: E402
from testgen.cases import DEV, EXAM  # noqa: E402

RESULTS_DIR = os.path.join(ROOT, "evaluation", "results")
CELL_COLUMNS = [f.column for f in TEMPLATE_FIELDS if f.column not in ("cid", "visit_date")]


# ---------------------------------------------------------------------------
# Eval database
# ---------------------------------------------------------------------------


def ensure_eval_db():
    admin = BASE_URL.replace("postgresql+psycopg://", "postgresql://")
    dbname = EVAL_URL.rsplit("/", 1)[1]
    with psycopg.connect(admin, autocommit=True) as conn:
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,)).fetchone():
            conn.execute(f'CREATE DATABASE "{dbname}"')
    from alembic import command
    from alembic.config import Config
    command.upgrade(Config(os.path.join(ROOT, "alembic.ini")), "head")


def reset_db():
    with SessionLocal() as db:
        db.execute(text("TRUNCATE employees, source_files, value_provenance, extra_results, conflicts, "
                        "value_history, pending_reviews, agent_decisions, file_profiles RESTART IDENTITY CASCADE"))
        db.execute(text("DELETE FROM lab_mappings WHERE origin <> 'seed'"))
        db.execute(text("DELETE FROM hospitals WHERE code <> 'UNSPECIFIED'"))
        db.commit()


def snapshot(upload_ids: list) -> dict:
    with SessionLocal() as db:
        values = {}
        for e in db.query(Employee):
            row = {c: getattr(e, c) for c in CELL_COLUMNS if getattr(e, c) is not None}
            values[(e.cid, e.visit_date.isoformat())] = row
        conflicts = {(c.cid, c.visit_date.isoformat(), col)
                     for c, col in [(db.get(Employee, x.employee_id), x.column) for x in db.query(Conflict)]}
        reviews = [{"kind": r.kind, "source_file_id": r.source_file_id, "payload": r.payload}
                   for r in db.query(PendingReview).filter(PendingReview.status == "open")]
        awaiting = {f.id for f in db.query(SourceFile).filter(SourceFile.status == "awaiting_review")}
        extras = [{"cid": x.cid, "visit_date": x.visit_date.isoformat(), "name": x.source_name,
                   "value": x.value_num if x.value_num is not None else x.value_text}
                  for x in db.query(ExtraResult)]
    return {"upload_ids": upload_ids, "values": values, "conflicts": conflicts, "reviews": reviews,
            "awaiting_files": awaiting, "extras": extras}


# ---------------------------------------------------------------------------
# Systems under test
# ---------------------------------------------------------------------------


class BaselineSUT:
    """The pre-agent upload endpoint (exact + RapidFuzz mapping), via HTTP in-process."""
    name = "baseline"

    def __init__(self):
        from fastapi.testclient import TestClient
        from app.main import app
        self.client = TestClient(app)

    def upload(self, path: str, hospital: str):
        with open(path, "rb") as fh:
            r = self.client.post("/api/upload", files={"file": (os.path.basename(path), fh)},
                                 data={"hospital": hospital})
        body = r.json()
        return body.get("upload_id"), body


SUTS = {"baseline": BaselineSUT}


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run(sut_name: str, set_name: str, only_case: str | None, verbose: bool):
    if set_name == "exam":
        if not verify("exam"):
            sys.exit("exam set does not match LOCK.json — refusing to report on it")
        print("⚠️  EXAM set: for reporting only. Do not change prompts/code based on these results.\n")
    ensure_eval_db()
    sut = SUTS[sut_name]()
    cases = DEV if set_name == "dev" else EXAM
    repeat_uploads = {(c.name, i) for c in cases for i, u in enumerate(c.uploads)
                      if u.same_layout_as is not None and u.records != c.uploads[u.same_layout_as].records}

    results = []
    for case in cases:
        if only_case and case.name != only_case:
            continue
        truth = json.load(open(os.path.join(TESTDATA, set_name, case.name, "truth.json"), encoding="utf-8"))
        reset_db()
        t0 = time.time()
        ids = []
        for up in case.uploads:
            fid, body = sut.upload(os.path.join(TESTDATA, set_name, case.name, up.filename), up.hospital)
            ids.append(fid)
            if verbose and not body.get("success", True):
                print(f"   upload failed: {up.filename}: {body.get('error')}")
        r = score_case(truth, snapshot(ids))
        r["seconds"] = round(time.time() - t0, 2)
        results.append(r)
        bk = r["buckets"]
        print(f"{case.name:32} ✅{bk.get('correct', 0):5}  ❌{bk.get('wrong', 0) + bk.get('spurious', 0):5}  "
              f"🟡{bk.get('missing_flagged', 0):5}  ⚠️{bk.get('missing_silent', 0):5}  / {r['expected_cells']:5}")
        if verbose:
            for e in r["error_examples"][:8]:
                print("     ❌", e)
            if r["missing_by_column"]:
                print("     ⚠️ missing by column:", r["missing_by_column"])

    h = headline(results, repeat_uploads)
    print("\n" + "=" * 72)
    fmt = lambda v: f"{v * 100:.2f}%" if isinstance(v, float) else str(v)  # noqa: E731
    for k, label, target in [
        ("auto_precision", "ความถูกต้องของสิ่งที่ระบบผ่านเอง", "≥ 99.5%"),
        ("automation", "สัดส่วนที่ระบบทำเองได้ (ทุกไฟล์)", "≥ 70%"),
        ("automation_repeat", "สัดส่วนที่ทำเองได้ (รพ.เดิม รอบสอง)", "≥ 95%"),
        ("silent_errors", "ค่าผิดที่หลุดเข้าไปเงียบ ๆ", "0"),
        ("silent_drops", "ค่าที่หายไปเงียบ ๆ", "0"),
        ("flagged_for_human", "ค่าที่ส่งให้คนดู", "-"),
        ("conflicts_found", "ข้อมูลขัดแย้งที่จับได้", "ครบ"),
        ("invalid_cid_flagged", "เลขบัตรผิดที่จับได้", "ครบ"),
        ("censored_flagged", "ค่า <x ที่จับได้", "ครบ"),
        ("extras_found", "ผลนอก template ที่เก็บได้", "ครบ"),
    ]:
        print(f"  {label:38} {fmt(h[k]):>12}   (เป้า {target})")

    os.makedirs(RESULTS_DIR, exist_ok=True)
    out = os.path.join(RESULTS_DIR, f"{set_name}_{sut_name}_{time.strftime('%Y%m%d-%H%M%S')}.json")
    if not only_case:
        with open(out, "w", encoding="utf-8") as fh:
            json.dump({"sut": sut_name, "set": set_name, "headline": h, "cases": results},
                      fh, ensure_ascii=False, indent=1, default=str)
        print(f"\nsaved {os.path.relpath(out, ROOT)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sut", default="baseline", choices=sorted(SUTS))
    ap.add_argument("--set", default="dev", choices=["dev", "exam"])
    ap.add_argument("--case")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    run(a.sut, a.set, a.case, a.verbose)
