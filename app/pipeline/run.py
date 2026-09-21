"""
run.py
======
Rules pipeline: read -> profile -> map -> extract -> store (no LLM here;
the agent graph in app/graph wraps this and adds mappings).
One transaction per file: it either lands completely or not at all.
"""

import os

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    AgentDecision, CheckupBatch, CommentLabel, Conflict, Hospital, PendingReview, SourceFile,
)
from app.pipeline.extract import extract
from app.pipeline.mapper import Mapper
from app.pipeline.profiler import file_title_date, profile_sheet
from app.pipeline.reader import read_file
from app.pipeline.store import save


def get_or_create_hospital(db: Session, code: str | None) -> Hospital:
    code = (code or "UNSPECIFIED").strip()
    h = db.query(Hospital).filter(Hospital.code == code).one_or_none()
    if h is None:
        h = Hospital(code=code, name=code)
        db.add(h)
        db.flush()
    return h


def process_file(db: Session, sf: SourceFile, evidence: dict | None = None,
                 comment_evidence: dict | None = None) -> dict:
    """
    Runs the pipeline for a registered SourceFile. Commits on success, rolls back on error.
    Safe to re-run on the same file (after new mappings are approved): same values are
    skipped, and the file's still-open reviews are replaced by the fresh ones.
    """
    try:
        with open(sf.stored_path, "rb") as fh:
            data = fh.read()
        sheets = read_file(data, os.path.splitext(sf.stored_path)[1])
        mapper = Mapper(db, sf.hospital_id)
        fdate = file_title_date(sheets)
        specs = [profile_sheet(s, mapper.known_labels(), mapper.identity_aliases(), fdate) for s in sheets]
        labels = {(c.column, c.text_norm): c.value for c in db.query(CommentLabel)}
        # The round holds the date (D23). Passing it in is what lets a file with no
        # date column be read at all — which is most of the department's own files.
        batch = db.get(CheckupBatch, sf.checkup_batch_id) if sf.checkup_batch_id else None
        round_date = batch.appoint_date.isoformat() if batch else None
        ex = extract(sheets, specs, mapper, evidence, labels, comment_evidence, round_date)
        db.query(PendingReview).filter(PendingReview.source_file_id == sf.id,
                                       PendingReview.status == "open").delete()
        stored = save(db, sf, ex)
        llm_cost = db.query(func.coalesce(func.sum(AgentDecision.cost_usd), 0)).filter(
            AgentDecision.source_file_id == sf.id).scalar()
        kinds = {}
        for r in ex.reviews:
            kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
        sf.stats = {
            "sheets": [{"name": s.sheet, "layout": s.layout} for s in specs],
            "observations": ex.stats["observations"],
            "cells_ok": ex.stats["cells_ok"],
            **stored,
            "reviews_by_kind": kinds,
            "llm_cost_usd": float(llm_cost or 0),
            # UI compatibility
            "total_rows": ex.stats["observations"],
            "success_rows": stored["stored"],
            "error_rows": len(ex.reviews),
        }
        sf.errors = []
        # Open conflicts for this file, not the ones this run happened to create: on a
        # re-run the disagreements found earlier are still open and still undecided, and
        # a file that says "completed" while they wait is the kind of quiet lie D13 exists
        # to prevent.
        waiting = (db.query(Conflict)
                   .filter(Conflict.source_file_id == sf.id, Conflict.status == "open").count())
        sf.status = "awaiting_review" if ex.reviews or waiting else "completed"
        db.commit()
        return sf.stats
    except Exception as e:
        db.rollback()
        sf = db.merge(sf)
        sf.status, sf.errors = "failed", [f"{type(e).__name__}: {e}"]
        db.commit()
        raise
