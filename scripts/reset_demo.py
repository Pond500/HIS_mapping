"""
reset_demo.py
=============
Wipes the MAIN database back to a fresh install, for a demo run after a
rehearsal (otherwise every mapping learned during rehearsal makes the demo
files go through with nothing left to review).

Deletes: results, uploaded-file records, reviews, conflicts, history, agent
logs, learned mappings (hospital layer), learned comment meanings, hospitals
other than UNSPECIFIED, LangGraph checkpoints.
Keeps:   the schema, the seeded central dictionary, recorded LLM answers
         (storage/llm_cache — needed for LLM_MODE=fallback/replay).

    .venv/bin/python scripts/reset_demo.py --yes
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402

from app.database import DATABASE_URL, SessionLocal  # noqa: E402


def main():
    db_name = DATABASE_URL.rsplit("/", 1)[-1]
    if "--yes" not in sys.argv:
        sys.exit(f"This deletes all data in database '{db_name}'. Re-run with --yes to confirm.")
    with SessionLocal() as db:
        db.execute(text("TRUNCATE employees, source_files, value_provenance, extra_results, conflicts, "
                        "value_history, pending_reviews, agent_decisions, file_profiles RESTART IDENTITY CASCADE"))
        db.execute(text("DELETE FROM lab_mappings WHERE hospital_id IS NOT NULL OR origin <> 'seed'"))
        db.execute(text("TRUNCATE comment_labels RESTART IDENTITY"))
        db.execute(text("DELETE FROM hospitals WHERE code <> 'UNSPECIFIED'"))
        existing = {r[0] for r in db.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename LIKE 'checkpoint%'"))}
        for t in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
            if t in existing:
                db.execute(text(f"TRUNCATE {t}"))
        db.commit()
    print(f"database '{db_name}' reset for the demo (central dictionary and recorded LLM answers kept)")


if __name__ == "__main__":
    main()
