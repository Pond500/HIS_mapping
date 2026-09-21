"""
harness.py
==========
The plumbing for the scenario suite: a scratch database built from the real
migrations, an in-process client that calls the app the way the browser does, and
small helpers for building input files.

Why not pytest with create_all, like the unit tests: the scenarios need what only
the migrations create — the seeded dictionary, the checkup types, the reporting
view — and they need the whole stack (upload -> agent graph -> store -> review ->
export), not one function. So this builds `his_mapping_scenarios` with
`alembic upgrade head`, wipes it between cases, and never touches the dev database.

The language model is never called: LLM_MODE=replay with an empty cache means every
label the rules cannot resolve raises LLMError and goes to a human. That is a real
path (the model being down), it is deterministic, and it costs nothing.
"""

import csv
import io
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

DB_NAME = "his_mapping_scenarios"
CHECKUP_PERIODIC = 2          # "ตรวจสุขภาพตามระยะเวลา/ประจำปี" in the seeded types


def cid(n: int) -> str:
    """A citizen id that passes the checksum, from a small number."""
    base = "1" + f"{n:011d}"
    s = sum(int(d) * (13 - i) for i, d in enumerate(base))
    return base + str((11 - s % 11) % 10)


def bad_cid(n: int) -> str:
    good = cid(n)
    return good[:-1] + str((int(good[-1]) + 1) % 10)


def csv_bytes(rows, encoding="utf-8-sig") -> bytes:
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue().encode(encoding)


def xlsx_bytes(sheets: dict) -> bytes:
    import openpyxl
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for r in rows:
            ws.append(r)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


class Harness:
    """One per run. Owns the scratch database, the clients and the temp storage."""

    def __init__(self, export_dir: str | None = None):
        from dotenv import dotenv_values
        base = os.environ.get("DATABASE_URL") or dotenv_values(os.path.join(ROOT, ".env"))["DATABASE_URL"]
        self.base_url = base.rsplit("/", 1)[0]
        self.url = f"{self.base_url}/{DB_NAME}"
        self.tmp = tempfile.mkdtemp(prefix="scenarios_")
        self.export_dir = export_dir
        self.current_case = None
        self._seq = {}
        os.environ.update(DATABASE_URL=self.url, LLM_MODE="replay", AUTO_ACCEPT="on",
                          LLM_CACHE_DIR=os.path.join(self.tmp, "llm"),
                          STORAGE_DIR=os.path.join(self.tmp, "uploads"))
        os.makedirs(os.environ["LLM_CACHE_DIR"], exist_ok=True)

    # -- database -----------------------------------------------------------
    def build_database(self):
        from sqlalchemy import create_engine, text
        admin = create_engine(f"{self.base_url}/postgres", isolation_level="AUTOCOMMIT")
        with admin.connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{DB_NAME}" WITH (FORCE)'))
            c.execute(text(f'CREATE DATABASE "{DB_NAME}"'))
        admin.dispose()
        from alembic import command
        from alembic.config import Config
        command.upgrade(Config(os.path.join(ROOT, "alembic.ini")), "head")

    def boot(self):
        from fastapi.testclient import TestClient
        from app import auth
        from app.database import SessionLocal, engine
        from app.main import app
        from app.models import AppUser
        from app.pipeline.run import get_or_create_hospital
        self.engine, self.SessionLocal = engine, SessionLocal
        with SessionLocal() as db:
            for code in ("H01", "H02"):
                get_or_create_hospital(db, code)
            h1 = get_or_create_hospital(db, "H01")
            for name, role, hosp in (("sa", "superadmin", None), ("staff1", "staff", h1.id)):
                db.add(AppUser(username=name, name=name, surname="ทดสอบ", email=f"{name}@example.com", role=role,
                               hospital_id=hosp, password_hash=auth.hash_password("pw-" + name),
                               is_active=True))
            db.commit()
        self.sa = TestClient(app)
        self.staff = TestClient(app)
        self.anon = TestClient(app)
        for client, name in ((self.sa, "sa"), (self.staff, "staff1")):
            r = client.post("/api/auth/login", json={"username": name, "password": "pw-" + name})
            assert r.status_code == 200, f"login {name}: {r.status_code} {r.text}"
        self._tables_to_wipe()

    def _tables_to_wipe(self):
        from sqlalchemy import text
        with self.engine.connect() as c:
            have = {r[0] for r in c.execute(text("select tablename from pg_tables where schemaname='public'"))}
        want = ["companies", "source_files", "comment_labels", "report_submissions",
                "checkpoints", "checkpoint_blobs", "checkpoint_writes"]
        self._wipe = [t for t in want if t in have]

    def reset(self):
        """Between cases: every trace of the last one, but not the seeded dictionary."""
        from sqlalchemy import text
        with self.engine.begin() as c:
            c.execute(text(f"TRUNCATE {', '.join(self._wipe)} RESTART IDENTITY CASCADE"))
            c.execute(text("DELETE FROM lab_mappings WHERE hospital_id IS NOT NULL"))
        self._tables_to_wipe()

    def sql(self, query: str, **params):
        from sqlalchemy import text
        with self.engine.connect() as c:
            return [dict(r._mapping) for r in c.execute(text(query), params)]

    def one(self, query: str, **params):
        rows = self.sql(query, **params)
        assert len(rows) == 1, f"expected exactly one row, got {len(rows)} for: {query}"
        return rows[0]

    def scalar(self, query: str, **params):
        rows = self.sql(query, **params)
        return list(rows[0].values())[0] if rows else None

    # -- files --------------------------------------------------------------
    def keep(self, name: str, content: bytes, kind: str):
        """With --export, every input file a case builds is written out for manual use,
        numbered in the order the case uploads them (the order matters)."""
        if self.export_dir and self.current_case:
            folder = os.path.join(self.export_dir, self.current_case)
            os.makedirs(folder, exist_ok=True)
            self._seq[self.current_case] = self._seq.get(self.current_case, 0) + 1
            with open(os.path.join(folder, f"{self._seq[self.current_case]:02d}-{kind}-{name}"), "wb") as fh:
                fh.write(content)

    def cleanup(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class Scenario:
    """The state one case starts from: one workplace, two departments, two rounds."""

    def __init__(self, h: Harness, world: bool = True):
        self.h = h
        self.sa, self.staff, self.anon = h.sa, h.staff, h.anon
        self.depts = {}
        self.fid = None
        if world:
            self.co = self.company("บริษัททดสอบ จำกัด", "0105500000001", ("ผลิต", "คลัง"))
            self.r1 = self.round(self.co, "2026-03-01")
            self.r2 = self.round(self.co, "2026-04-01")

    # -- setup through the same endpoints the pages call ---------------------
    def company(self, name, juristic, depts=()):
        r = self.sa.post("/api/companies", json={"juristic_id": juristic, "name": name})
        assert r.status_code == 201, r.text
        co = r.json()["id"]
        for d in depts:
            r = self.sa.post(f"/api/companies/{co}/departments", json={"name": d})
            assert r.status_code == 201, r.text
        return co

    def round(self, company_id, appoint, type_=CHECKUP_PERIODIC, client=None):
        # Made by a staff account, which has a hospital: a round records the hospital of
        # whoever creates it. (Creating one as the superadmin is its own case, C03.)
        client = client or self.staff
        r = client.post("/api/surveys", json={"company_id": company_id, "survey_date": "2026-01-05"})
        assert r.status_code in (200, 201), r.text
        r = client.post("/api/rounds", json={"survey_id": r.json()["id"], "checkup_type": type_,
                                              "appoint_date": appoint})
        assert r.status_code == 201, r.text
        return r.json()["id"]

    # -- uploads ------------------------------------------------------------
    def registry(self, rows, name="ทะเบียน.csv", company=None, hospital="H01", client=None, raw=None):
        content = raw if raw is not None else csv_bytes(rows)
        self.h.keep(name, content, "ทะเบียน")
        r = (client or self.sa).post("/api/upload/registry", files={"file": (name, content)},
                                     data={"company_id": company or self.co, "hospital": hospital})
        assert r.status_code == 200, r.text
        return r.json()

    def results(self, rows=None, name="ผลตรวจ.csv", round_id=None, hospital="H01", client=None, raw=None,
                encoding="utf-8-sig"):
        content = raw if raw is not None else csv_bytes(rows, encoding)
        self.h.keep(name, content, "ผลตรวจ")
        r = (client or self.sa).post("/api/upload", files={"file": (name, content)},
                                     data={"round_id": round_id or self.r1, "hospital": hospital})
        assert r.status_code == 200, r.text
        self.fid = r.json().get("upload_id")          # the results file just uploaded
        return r.json()

    def default_people(self):
        """Five people: four in ผลิต, one in คลัง. The register every results case leans on."""
        rows = [["เลขบัตรประชาชน", "ชื่อ", "นามสกุล", "ชื่อแผนก"]]
        for n in range(1, 5):
            rows.append([cid(n), f"ชื่อ{n}", f"สกุล{n}", "ผลิต"])
        rows.append([cid(5), "ชื่อ5", "สกุล5", "คลัง"])
        out = self.registry(rows)
        assert out["added"] == 5 and out["reviews"] == 0, out
        return out

    # -- reading back -------------------------------------------------------
    def reviews(self, file_id=None, status="open"):
        url = f"/api/reviews?status={status}&limit=5000" + (f"&file_id={file_id}" if file_id else "")
        r = self.sa.get(url)
        assert r.status_code == 200, r.text
        return r.json()

    def kinds(self, file_id=None):
        return sorted(x["kind"] for x in self.reviews(file_id))

    def decide(self, file_id, decisions, client=None, expect=200):
        r = (client or self.sa).post(f"/api/files/{file_id}/decisions",
                                     json={"decisions": decisions, "by": "browser-says-this"})
        assert r.status_code == expect, f"decide -> {r.status_code}: {r.text}"
        return r.json()

    def file(self, file_id):
        return self.h.one("select * from source_files where id=:i", i=file_id)

    def checkup(self, n, round_id=None):
        """One person's results row for a round, by the small number given to cid()."""
        rows = self.h.sql("""select c.*, e.cid, d.name as dept from employee_checkups c
                             join employees e on e.id=c.employee_id
                             join departments d on d.id=e.department_pk
                             where e.cid=:c and c.checkup_batch_id=:r""",
                          c=cid(n), r=round_id or self.r1)
        return rows[0] if len(rows) == 1 else (None if not rows else rows)

    def n_checkups(self, round_id=None):
        return self.h.scalar("select count(*) from employee_checkups where checkup_batch_id=:r",
                             r=round_id or self.r1)


def num(x, places=2):
    return None if x is None else round(float(x), places)
