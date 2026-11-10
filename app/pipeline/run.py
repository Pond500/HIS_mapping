"""
run.py
======
Rules pipeline: read -> profile -> map -> extract -> store (no LLM here;
the agent graph in app/graph wraps this and adds mappings).
One transaction per file: it either lands completely or not at all.
"""

import json
import os

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    AgentDecision, CheckupBatch, CommentLabel, Conflict, ExtraResult, Hospital, PendingReview, SourceFile,
    ValueProvenance,
    WalkthroughSurvey,
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


def company_id_of(db: Session, sf: SourceFile) -> int | None:
    """The company a file's labels should be checked against for company columns
    (CONTEXT.md "คอลัมน์ของบริษัท"): a registry file names its company directly;
    a results file only has one through its round (D23)."""
    if sf.company_id is not None:
        return sf.company_id
    if sf.checkup_batch_id is None:
        return None
    batch = db.get(CheckupBatch, sf.checkup_batch_id)
    if batch is None:
        return None
    survey = db.get(WalkthroughSurvey, batch.survey_id)
    return survey.company_id if survey else None


def _review_key(kind: str, payload: dict) -> str:
    return json.dumps([kind, payload], sort_keys=True, ensure_ascii=False, default=str)


def dismissed_keys(db: Session, file_id: int) -> set:
    """Items a person closed on this file ("I fixed the source file"). A file is re-read
    after every save, so without this a closed item was simply found again and reopened."""
    return {_review_key(r.kind, r.payload)
            for r in db.query(PendingReview)
                       .filter(PendingReview.source_file_id == file_id, PendingReview.status == "dismissed")}


def without_dismissed(reviews: list, keys: set) -> list:
    return [r for r in reviews if _review_key(r["kind"], r["payload"]) not in keys] if keys else reviews


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
        mapper = Mapper(db, sf.hospital_id, company_id_of(db, sf))
        fdate = file_title_date(sheets)
        specs = [profile_sheet(s, mapper.known_labels(), mapper.identity_aliases(), fdate) for s in sheets]
        labels = {(c.column, c.text_norm): c.value for c in db.query(CommentLabel)}
        # The round holds the date (D23). Passing it in is what lets a file with no
        # date column be read at all — which is most of the department's own files.
        batch = db.get(CheckupBatch, sf.checkup_batch_id) if sf.checkup_batch_id else None
        round_date = batch.appoint_date.isoformat() if batch else None
        ex = extract(sheets, specs, mapper, evidence, labels, comment_evidence, round_date)
        ex.reviews = without_dismissed(ex.reviews, dismissed_keys(db, sf.id))
        db.query(PendingReview).filter(PendingReview.source_file_id == sf.id,
                                       PendingReview.status == "open").delete()
        stored = save(db, sf, ex)
        llm_cost = db.query(func.coalesce(func.sum(AgentDecision.cost_usd), 0)).filter(
            AgentDecision.source_file_id == sf.id).scalar()
        db.flush()
        # Everything this file has put in, over every run of it. `stored` counts only
        # this run, and a file is run again after the AI reads its findings or a person
        # answers a question, so the page said "19 stored" for a file that stored 24.
        total_stored = db.query(func.count(ValueProvenance.id)).filter(
            ValueProvenance.source_file_id == sf.id).scalar()
        total_extras = db.query(func.count(ExtraResult.id)).filter(
            ExtraResult.source_file_id == sf.id).scalar()
        kinds = {}
        for r in ex.reviews:
            kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
        sf.stats = {
            "sheets": [{"name": s.sheet, "layout": s.layout} for s in specs],
            "observations": ex.stats["observations"],
            "cells_ok": ex.stats["cells_ok"],
            **stored,
            "stored_total": total_stored,
            "extras_total": total_extras,
            "reviews_by_kind": kinds,
            "llm_cost_usd": float(llm_cost or 0),
            # UI compatibility
            "total_rows": ex.stats["observations"],
            "success_rows": total_stored,
            "error_rows": len(ex.reviews),
        }
        sf.errors = []
        # Open conflicts for this file, not the ones this run happened to create: on a
        # re-run the disagreements found earlier are still open and still undecided, and
        # a file that says "completed" while they wait is the kind of quiet lie D13 exists
        # to prevent.
        # The session does not autoflush, so the conflicts save() just added are not yet
        # visible to this query: on a file's first run it counted zero and reported
        # "completed" with the conflicts still open. Flush first.
        db.flush()
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
