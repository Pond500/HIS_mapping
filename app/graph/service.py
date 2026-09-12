"""
service.py
==========
Entry points used by the API and the evaluation harness. One LangGraph thread
per source file ("file-<id>"), checkpointed in Postgres so a file waiting for
a reviewer survives restarts.
"""

import os
import time

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.database import SessionLocal
from app.graph import flow
from app.models import SourceFile
from app.pipeline.run import process_file

_graph = None
_pool = None


def graph():
    """Compiled graph with a Postgres checkpointer. A pool (checked on every checkout)
    rather than one long-lived connection, so a database restart doesn't break every
    later upload. Call init() at app startup so setup() never runs inside a request."""
    global _graph, _pool
    if _graph is None:
        url = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
        _pool = ConnectionPool(url, min_size=1, max_size=8, open=True, check=ConnectionPool.check_connection,
                               kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row})
        _drop_invalid_checkpoint_indexes(_pool)
        saver = PostgresSaver(_pool)
        saver.setup()
        _graph = flow.build(saver)
    return _graph


def init():
    """Create the checkpointer tables/indexes up front (app startup), while no request
    transaction is open — setup() uses CREATE INDEX CONCURRENTLY, which waits for them."""
    graph()


def _drop_invalid_checkpoint_indexes(pool):
    """An interrupted CREATE INDEX CONCURRENTLY leaves an INVALID index behind, and setup()'s
    'IF NOT EXISTS' would then skip it forever. Drop such leftovers so setup() rebuilds them."""
    with pool.connection() as conn:
        rows = conn.execute("SELECT c.relname FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
                            "WHERE NOT i.indisvalid AND c.relname LIKE 'checkpoint%'").fetchall()
        for r in rows:
            conn.execute(f'DROP INDEX IF EXISTS "{r["relname"]}"')


def _cfg(file_id: int) -> dict:
    return {"configurable": {"thread_id": f"file-{file_id}"}}


def run_upload(file_id: int) -> dict:
    """Runs the graph for a newly registered file until it finishes or waits for a human."""
    t0 = time.time()
    try:
        graph().invoke({"source_file_id": file_id}, _cfg(file_id))
    finally:
        with SessionLocal() as db:   # system time per file, shown on the dashboard (D5)
            sf = db.get(SourceFile, file_id)
            if sf is not None:
                sf.stats = {**(sf.stats or {}), "duration_s": round(time.time() - t0, 1)}
                db.commit()
    return status(file_id)


def waiting_for_human(file_id: int) -> bool:
    return "human" in (graph().get_state(_cfg(file_id)).next or ())


def decide(file_id: int, decisions: list[dict]) -> dict:
    """Applies reviewer decisions: resumes the paused graph, or (graph already finished) applies and re-runs."""
    if waiting_for_human(file_id):
        graph().invoke(Command(resume=decisions), _cfg(file_id))
    else:
        flow.apply_decisions(file_id, decisions)
        with SessionLocal() as db:
            process_file(db, db.get(SourceFile, file_id))
    return status(file_id)


def status(file_id: int) -> dict:
    with SessionLocal() as db:
        sf = db.get(SourceFile, file_id)
        return {"upload_id": sf.id, "status": sf.status, "stats": sf.stats, "errors": sf.errors,
                "waiting_for_human": waiting_for_human(file_id)}
