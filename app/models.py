"""
models.py
=========
SQLAlchemy models. See docs/requirements.md (D6, D12, D13) for why each
table exists.

Core rule: every stored value is either correct or waiting for a human.
Nothing is overwritten silently. Changes go through Conflict -> ValueHistory.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON, Date, DateTime, ForeignKey, Integer, Numeric, SmallInteger, String,
    Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.template import TEMPLATE_FIELDS

# ---------------------------------------------------------------------------
# Hospitals & source files
# ---------------------------------------------------------------------------


class Hospital(Base):
    __tablename__ = "hospitals"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SourceFile(Base):
    """One uploaded file. The original bytes are kept on disk at stored_path."""
    __tablename__ = "source_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    hospital_id: Mapped[int] = mapped_column(ForeignKey("hospitals.id"), index=True)
    filename: Mapped[str] = mapped_column(String(500))
    file_type: Mapped[str] = mapped_column(String(10))           # csv / xlsx / xls
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    stored_path: Mapped[str] = mapped_column(String(1000))
    # processing / awaiting_review / completed / failed
    status: Mapped[str] = mapped_column(String(20), default="processing")
    graph_thread_id: Mapped[str | None] = mapped_column(String(100))
    # counts, automation rate, cost — filled in by the pipeline
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    def to_dict(self):
        s = self.stats or {}
        return {
            "id": self.id,
            "hospital_id": self.hospital_id,
            "filename": self.filename,
            "file_type": self.file_type,
            "status": self.status,
            "total_rows": s.get("total_rows", 0),
            "success_rows": s.get("success_rows", 0),
            "error_rows": s.get("error_rows", 0),
            "stats": s,
            "errors": self.errors or [],
            "created_at": self.uploaded_at.isoformat() if self.uploaded_at else None,
        }


class FileProfile(Base):
    """Confirmed parse spec for a file layout, reused for the same hospital."""
    __tablename__ = "file_profiles"
    __table_args__ = (UniqueConstraint("hospital_id", "fingerprint"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    hospital_id: Mapped[int] = mapped_column(ForeignKey("hospitals.id"))
    fingerprint: Mapped[str] = mapped_column(String(64))  # hash of the header layout
    spec: Mapped[dict] = mapped_column(JSON)
    confirmed_by: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ---------------------------------------------------------------------------
# Mappings (two layers: hospital_id NULL = central dictionary)
# ---------------------------------------------------------------------------

# Special target_column values besides template columns
TARGET_EXTRA = "__extra__"    # real lab with no template column -> extra_results
TARGET_IGNORE = "__ignore__"  # not a result at all (e.g. row numbers, order ids)


class LabMapping(Base):
    __tablename__ = "lab_mappings"
    __table_args__ = (
        UniqueConstraint("hospital_id", "source_name", "source_unit",
                         postgresql_nulls_not_distinct=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    hospital_id: Mapped[int | None] = mapped_column(ForeignKey("hospitals.id"), index=True)
    source_name: Mapped[str] = mapped_column(String(200))   # normalized: lower + stripped
    source_unit: Mapped[str | None] = mapped_column(String(50))
    target_column: Mapped[str] = mapped_column(String(100))
    unit_factor: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=1)
    origin: Mapped[str] = mapped_column(String(20))         # seed / human / agent_approved
    approved_by: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    def to_dict(self):
        return {
            "id": self.id,
            "hospital_id": self.hospital_id,
            "his_lab_name": self.source_name,
            "source_unit": self.source_unit,
            "template_column": self.target_column,
            "unit_factor": float(self.unit_factor) if self.unit_factor is not None else 1.0,
            "origin": self.origin,
        }


# ---------------------------------------------------------------------------
# Results (one row per person + visit date, columns from the template)
# ---------------------------------------------------------------------------


def _result_column(field):
    if field.kind == "numeric":
        return mapped_column(Numeric(*field.precision), nullable=True)
    if field.kind == "categorical":
        return mapped_column(SmallInteger, nullable=True)
    if field.kind == "date":
        return mapped_column(Date, nullable=False)
    if field.kind == "id":
        return mapped_column(String(field.size), nullable=False)
    return mapped_column(String(field.size) if field.size else Text, nullable=True)


class Employee(Base):
    __tablename__ = "employees"
    __table_args__ = (UniqueConstraint("cid", "visit_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    hospital_id: Mapped[int] = mapped_column(ForeignKey("hospitals.id"), index=True)
    source_file_id: Mapped[int] = mapped_column(ForeignKey("source_files.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # one column per template field (class namespace must hold them before mapping)
    for _f in TEMPLATE_FIELDS:
        locals()[_f.column] = _result_column(_f)
    del _f

    def to_dict(self):
        d = {"id": self.id, "hospital_id": self.hospital_id,
             "source_file_id": self.source_file_id,
             "created_at": self.created_at.isoformat() if self.created_at else None}
        for f in TEMPLATE_FIELDS:
            v = getattr(self, f.column)
            if isinstance(v, Decimal):
                v = float(v)
            elif isinstance(v, date):
                v = v.isoformat()
            d[f.column] = v  # 0 stays 0 — only None means missing
        return d


class ValueProvenance(Base):
    """Where each stored value came from (file / sheet / cell)."""
    __tablename__ = "value_provenance"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    column: Mapped[str] = mapped_column(String(100))
    source_file_id: Mapped[int] = mapped_column(ForeignKey("source_files.id"))
    sheet: Mapped[str | None] = mapped_column(String(200))
    cell: Mapped[str | None] = mapped_column(String(20))        # e.g. "D14"
    raw_name: Mapped[str | None] = mapped_column(String(200))
    raw_value: Mapped[str | None] = mapped_column(Text)
    raw_unit: Mapped[str | None] = mapped_column(String(50))
    mapping_id: Mapped[int | None] = mapped_column(ForeignKey("lab_mappings.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ExtraResult(Base):
    """Real results with no template column (FBS, cholesterol, …). Kept, not dropped."""
    __tablename__ = "extra_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    hospital_id: Mapped[int] = mapped_column(ForeignKey("hospitals.id"))
    source_file_id: Mapped[int] = mapped_column(ForeignKey("source_files.id"), index=True)
    cid: Mapped[str] = mapped_column(String(13), index=True)
    visit_date: Mapped[date] = mapped_column(Date)
    source_name: Mapped[str] = mapped_column(String(200))
    value_text: Mapped[str | None] = mapped_column(Text)
    value_num: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    unit: Mapped[str | None] = mapped_column(String(50))
    sheet: Mapped[str | None] = mapped_column(String(200))
    cell: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ---------------------------------------------------------------------------
# Conflicts & history (D13)
# ---------------------------------------------------------------------------


class Conflict(Base):
    """Incoming value differs from the stored one. Stored value stays until a human decides."""
    __tablename__ = "conflicts"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    column: Mapped[str] = mapped_column(String(100))
    current_value: Mapped[str | None] = mapped_column(Text)
    incoming_value: Mapped[str | None] = mapped_column(Text)
    source_file_id: Mapped[int] = mapped_column(ForeignKey("source_files.id"), index=True)
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open / kept / replaced
    resolved_by: Mapped[str | None] = mapped_column(String(100))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ValueHistory(Base):
    __tablename__ = "value_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    column: Mapped[str] = mapped_column(String(100))
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(String(50))   # conflict_resolved / accept_all
    source_file_id: Mapped[int | None] = mapped_column(ForeignKey("source_files.id"))
    changed_by: Mapped[str | None] = mapped_column(String(100))
    changed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ---------------------------------------------------------------------------
# Human review queue & agent audit log
# ---------------------------------------------------------------------------


class PendingReview(Base):
    """
    Anything a human must decide: a proposed mapping, a file profile, an
    invalid CID, a value skipped as "ไม่แน่ใจ", a comment classification.
    payload holds the evidence shown on the review screen.
    """
    __tablename__ = "pending_reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_file_id: Mapped[int] = mapped_column(ForeignKey("source_files.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))      # mapping / profile / cid / value / comment
    payload: Mapped[dict] = mapped_column(JSON)
    # open / approved / rejected / skipped
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    decision: Mapped[dict | None] = mapped_column(JSON)
    decided_by: Mapped[str | None] = mapped_column(String(100))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AgentDecision(Base):
    """Audit log of every LLM call: what went in (no PII), what came out, cost."""
    __tablename__ = "agent_decisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_file_id: Mapped[int | None] = mapped_column(ForeignKey("source_files.id"), index=True)
    agent: Mapped[str] = mapped_column(String(50))     # profiler / mapper / verifier / qc / comment
    model: Mapped[str] = mapped_column(String(200))
    input: Mapped[dict] = mapped_column(JSON)
    output: Mapped[dict | None] = mapped_column(JSON)
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
