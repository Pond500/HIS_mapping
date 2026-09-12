"""
run.py
======
Runs a system under test (SUT) over a test set and scores it.

    .venv/bin/python -m evaluation.run --sut rules --set dev
    .venv/bin/python -m evaluation.run --sut agents --set dev --oracle      # simulated reviewer
    .venv/bin/python -m evaluation.run --sut agents --case d08_extras_traps -v
    .venv/bin/python -m evaluation.run --sut agents --set exam --oracle     # reporting only — never tune on exam

SUTs: baseline (old /api/legacy/upload), rules (pipeline, no LLM),
agents (LangGraph + LLM, AUTO_ACCEPT=on), agents_noauto (every AI proposal waits for a human).

--oracle: after each upload, a simulated reviewer answers the open mapping reviews from
the truth (a perfect human). Automation is scored per upload BEFORE the oracle answers;
precision and silent errors on the final state. This measures D8's "same hospital,
second file" target, which needs approved mappings to be remembered.

Uses a separate database (his_mapping_eval, or EVAL_DATABASE_URL), wiped before every case.
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
from sqlalchemy import func, text  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import (AgentDecision, Conflict, Employee, ExtraResult, PendingReview,  # noqa: E402
                        SourceFile)
from app.template import FIELDS_BY_COLUMN, TEMPLATE_FIELDS  # noqa: E402
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
        # LangGraph checkpoints: file ids restart at 1, so old threads must go
        existing = {r[0] for r in db.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename LIKE 'checkpoint%'"))}
        for t in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
            if t in existing:
                db.execute(text(f"TRUNCATE {t}"))
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
        extras = [{"cid": x.cid, "visit_date": x.visit_date.isoformat(), "name": x.source_name,
                   "value": x.value_num if x.value_num is not None else x.value_text}
                  for x in db.query(ExtraResult)]
        cost = db.query(func.coalesce(func.sum(AgentDecision.cost_usd), 0)).scalar()
        calls = db.query(func.count(AgentDecision.id)).scalar()
    return {"upload_ids": upload_ids, "values": values, "conflicts": conflicts, "reviews": reviews,
            "awaiting_files": set(), "extras": extras, "llm_cost_usd": float(cost or 0), "llm_calls": calls}


# ---------------------------------------------------------------------------
# Systems under test
# ---------------------------------------------------------------------------


class BaselineSUT:
    """Pre-POC exact + RapidFuzz mapping (app/routes/upload_legacy.py), over HTTP in-process."""
    name = "baseline"

    def __init__(self):
        from fastapi.testclient import TestClient
        from app.main import app
        self.client = TestClient(app)

    def upload(self, path: str, hospital: str):
        with open(path, "rb") as fh:
            r = self.client.post("/api/legacy/upload", files={"file": (os.path.basename(path), fh)},
                                 data={"hospital": hospital})
        return r.json().get("upload_id")

    def decide(self, file_id, decisions):
        pass   # the old code has no review loop


class RulesSUT:
    """Pipeline without LLM (app/pipeline)."""
    name = "rules"

    def upload(self, path: str, hospital: str):
        from app.pipeline.run import process_file
        from app.routes.upload import register_file
        with SessionLocal() as db:
            sf = register_file(db, os.path.basename(path), open(path, "rb").read(), hospital)
            try:
                process_file(db, sf)
            except Exception as e:
                print(f"   upload failed: {path}: {e}")
            return sf.id

    def decide(self, file_id, decisions):
        from app.graph import service
        service.decide(file_id, decisions)


class AgentsSUT(RulesSUT):
    """LangGraph + LLM agents (app/graph), auto-accept on full agreement."""
    name, auto = "agents", "on"

    def upload(self, path: str, hospital: str):
        from app.graph import service
        from app.routes.upload import register_file
        os.environ["AUTO_ACCEPT"] = self.auto
        with SessionLocal() as db:
            sf = register_file(db, os.path.basename(path), open(path, "rb").read(), hospital)
        try:
            service.run_upload(sf.id)
        except Exception as e:
            print(f"   upload failed: {path}: {type(e).__name__}: {e}")
        return sf.id


class AgentsNoAutoSUT(AgentsSUT):
    """Same graph, but every AI proposal waits for a human."""
    name, auto = "agents_noauto", "off"


SUTS = {s.name: s for s in (BaselineSUT, RulesSUT, AgentsSUT, AgentsNoAutoSUT)}


# ---------------------------------------------------------------------------
# Simulated reviewer (a perfect human, answers mapping reviews from the truth)
# ---------------------------------------------------------------------------


def oracle_decisions(file_id: int, upload_truth: dict) -> tuple[list, dict]:
    stats = {"decisions": 0, "corrections": 0}
    decisions = []
    with SessionLocal() as db:
        reviews = db.query(PendingReview).filter(PendingReview.source_file_id == file_id,
                                                 PendingReview.kind == "mapping",
                                                 PendingReview.status == "open").all()
        for r in reviews:
            label, unit = r.payload.get("label"), r.payload.get("unit")
            info = upload_truth["lab_names"].get(label)
            if info is None and upload_truth["headers"].get(label) == "__ignore__":
                info = {"target": "__ignore__", "factor": 1}
            if info is None or info["target"] == "__bp__":
                continue
            t, f = info["target"], info["factor"]
            prop = (r.payload.get("proposal") or {})
            prop_ok = prop.get("target") == t and (t not in FIELDS_BY_COLUMN or FIELDS_BY_COLUMN[t].kind != "numeric"
                                                   or (prop.get("factor") and abs(prop["factor"] - f) <= 0.01 * abs(f)))
            if prop_ok:
                d = {"action": "approve"}
            elif t == "__extra__":
                d = {"action": "extra"}
            elif t == "__ignore__":
                d = {"action": "ignore"}
            else:
                d = {"action": "set", "target": t, "factor": f}
            stats["decisions"] += 1
            stats["corrections"] += 0 if prop_ok else 1
            decisions.append({"label": label, "unit": unit, "by": "oracle", **d})
    return decisions, stats


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run(sut_name: str, set_name: str, only_case: str | None, verbose: bool, oracle: bool):
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
        ids, first_pass, orc = [], [], {"decisions": 0, "corrections": 0}
        for i, up in enumerate(case.uploads):
            fid = sut.upload(os.path.join(TESTDATA, set_name, case.name, up.filename), up.hospital)
            ids.append(fid)
            first_pass.append(score_case(truth, snapshot(ids))["per_upload"][i])
            if oracle and fid is not None:
                decisions, st = oracle_decisions(fid, truth["uploads"][i])
                if decisions:
                    sut.decide(fid, decisions)
                orc = {k: orc[k] + st[k] for k in orc}
        snap = snapshot(ids)
        r = score_case(truth, snap)
        r["per_upload"] = first_pass
        r["seconds"] = round(time.time() - t0, 1)
        r["llm_cost_usd"], r["llm_calls"], r["oracle"] = snap["llm_cost_usd"], snap["llm_calls"], orc
        results.append(r)
        bk, auto_ok = r["buckets"], sum(p.get("correct", 0) for p in first_pass)
        print(f"{case.name:32} auto✅{auto_ok:5} | final ✅{bk.get('correct', 0):5} "
              f"❌{bk.get('wrong', 0) + bk.get('spurious', 0):4} 🟡{bk.get('missing_flagged', 0):5} "
              f"⚠️{bk.get('missing_silent', 0):4} / {r['expected_cells']:5}  "
              f"${r['llm_cost_usd']:.4f} {r['seconds']}s" + (f"  oracle {orc}" if oracle else ""))
        if verbose:
            for e in r["error_examples"][:8]:
                print("     ❌", e)
            if r["missing_by_column"]:
                print("     ⚠️ missing by column:", r["missing_by_column"])

    h = headline(results, repeat_uploads)
    print("\n" + "=" * 72)
    fmt = lambda v: f"{v * 100:.2f}%" if isinstance(v, float) and v <= 1 else str(v)  # noqa: E731
    for k, label, target in [
        ("auto_precision", "ความถูกต้องของสิ่งที่อยู่ในระบบ", "≥ 99.5%"),
        ("automation", "สัดส่วนที่ระบบทำเองได้ (ก่อนคนตรวจ)", "≥ 70%"),
        ("automation_repeat", "ทำเองได้ (รพ.เดิม รอบสอง)", "≥ 95%"),
        ("silent_errors", "ค่าผิดที่หลุดเข้าไปเงียบ ๆ", "0"),
        ("silent_drops", "ค่าที่หายไปเงียบ ๆ", "0"),
        ("flagged_for_human", "ค่าที่ยังรอคนดู (สุดท้าย)", "-"),
        ("conflicts_found", "ข้อมูลขัดแย้งที่จับได้", "ครบ"),
        ("invalid_cid_flagged", "เลขบัตรผิดที่จับได้", "ครบ"),
        ("extras_found", "ผลนอก template ที่เก็บได้", "ครบ"),
        ("human_decisions", "การตัดสินใจของคนตรวจจำลอง", "-"),
        ("human_corrections", "  ในนั้น AI เสนอผิด/ไม่ได้เสนอ", "-"),
        ("llm_calls", "จำนวนครั้งที่เรียก AI", "-"),
        ("llm_cost_usd", "ค่าใช้จ่าย AI (USD)", "-"),
    ]:
        v = h[k]
        print(f"  {label:38} {(f'${v:.4f}' if k == 'llm_cost_usd' else fmt(v)):>12}   (เป้า {target})")

    os.makedirs(RESULTS_DIR, exist_ok=True)
    tag = f"{sut_name}{'_oracle' if oracle else ''}"
    out = os.path.join(RESULTS_DIR, f"{set_name}_{tag}_{time.strftime('%Y%m%d-%H%M%S')}.json")
    if not only_case:
        with open(out, "w", encoding="utf-8") as fh:
            json.dump({"sut": sut_name, "set": set_name, "oracle": oracle, "headline": h, "cases": results},
                      fh, ensure_ascii=False, indent=1, default=str)
        print(f"\nsaved {os.path.relpath(out, ROOT)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sut", default="rules", choices=sorted(SUTS))
    ap.add_argument("--set", default="dev", choices=["dev", "exam"])
    ap.add_argument("--case")
    ap.add_argument("--oracle", action="store_true", help="simulate a perfect reviewer after each upload")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    run(a.sut, a.set, a.case, a.verbose, a.oracle)
