"""
reset_demo.py
=============
Wipes the MAIN database back to a fresh install, for a demo run after a
rehearsal (otherwise every mapping learned during rehearsal makes the demo
files go through with nothing left to review).

Deletes: workplaces and everything under them (departments, people, surveys,
rounds, results), uploaded-file records, reviews, conflicts, history, hand-overs,
agent logs, learned mappings (hospital layer), learned comment meanings, hospitals
other than UNSPECIFIED, LangGraph checkpoints.
Keeps:   the schema, the seeded central dictionary, the checkup types and lists,
         accounts (app_users), API keys, recorded LLM answers (storage/llm_cache —
         needed for LLM_MODE=fallback/replay).

    .venv/bin/python scripts/reset_demo.py --yes

It was written for the pre-D23 schema. Run after the rebuild it failed on deleting a
hospital that accounts still pointed at and, being one transaction, cleaned nothing —
so the day before a demo it would have looked like an error and left the rehearsal
data in place. It follows the schema now, and tests/test_reset_demo.py runs it against a
scratch database to keep it that way.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402

from app.database import DATABASE_URL, SessionLocal  # noqa: E402

# One TRUNCATE ... CASCADE from the two roots. companies reaches departments, employees,
# surveys, rounds, checkups and hand-overs; source_files reaches everything that points at
# an uploaded file. Listing the children by hand is what went stale last time.
ROOTS = ("companies", "source_files", "report_submissions", "agent_decisions", "file_profiles")


def reset(db) -> None:
    db.execute(text(f"TRUNCATE {', '.join(ROOTS)} RESTART IDENTITY CASCADE"))
    db.execute(text("DELETE FROM lab_mappings WHERE hospital_id IS NOT NULL OR origin <> 'seed'"))
    db.execute(text("TRUNCATE comment_labels RESTART IDENTITY"))
    # Remove the hospitals nothing points at any more. The tables that reference
    # hospitals are found from the schema, not listed here: a hand-written list is what
    # went stale last time. Accounts and keys keep the hospital they are bound to.
    keep = db.execute(text("SELECT id FROM hospitals WHERE code = 'UNSPECIFIED'")).scalar()
    refs = db.execute(text(
        "SELECT c.conrelid::regclass::text, a.attname FROM pg_constraint c "
        "JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey) "
        "WHERE c.contype = 'f' AND c.confrelid = 'hospitals'::regclass")).all()
    unused = " AND ".join(f'id NOT IN (SELECT "{col}" FROM {table} WHERE "{col}" IS NOT NULL)'
                          for table, col in refs)
    db.execute(text(f"DELETE FROM hospitals WHERE id <> :k AND {unused or 'TRUE'}"), {"k": keep or 0})
    existing = {r[0] for r in db.execute(text(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename LIKE 'checkpoint%'"))}
    for t in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
        if t in existing:
            db.execute(text(f"TRUNCATE {t}"))


def main():
    db_name = DATABASE_URL.rsplit("/", 1)[-1]
    if "--yes" not in sys.argv:
        sys.exit(f"This deletes all data in database '{db_name}'. Re-run with --yes to confirm.")
    with SessionLocal() as db:
        reset(db)
        db.commit()
    print(f"database '{db_name}' reset for the demo (central dictionary, accounts and recorded LLM answers kept)")


if __name__ == "__main__":
    main()
