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
    JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, Numeric,
    SmallInteger, String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.template import REGISTRY_FIELDS, TEMPLATE_FIELDS

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
    # the API key that sent the file (D19); NULL when it came through the staff web page
    api_key_id: Mapped[int | None] = mapped_column(ForeignKey("api_keys.id"))

    # Which field set the file is read against, "result" or "registry" (D23).
    field_set: Mapped[str] = mapped_column(String(20), default="result")
    # The round a results file belongs to. Chosen in the upload dialog before the
    # file is picked, and it is where the visit date comes from — the department
    # keeps the date on the round, not in the file (D23).
    checkup_batch_id: Mapped[int | None] = mapped_column(ForeignKey("employee_checkup_batches.id"), index=True)
    # The workplace a registry file belongs to. A results file gets its company
    # through the round instead.
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), index=True)

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


class ApiKey(Base):
    """A key for the external API (/api/v1, D19). It belongs to one hospital: files sent
    with it are registered under that hospital. Only the SHA-256 of the key is stored."""
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    hospital_id: Mapped[int] = mapped_column(ForeignKey("hospitals.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))                 # who uses it, e.g. "HIS รพ.ตัวอย่าง"
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    prefix: Mapped[str] = mapped_column(String(20))                # first characters, to recognise a key
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)


class AppUser(Base):
    """A person who signs in to the staff web pages (Env-Occ manual: เข้าสู่ระบบ / จัดการผู้ใช้งาน).
    Roles: superadmin (ส่วนกลาง) / admin (ผู้ดูแลหน่วยบริการ) / doctor (แพทย์) / staff (เจ้าหน้าที่).
    A user belongs to one hospital ("สังกัด"); superadmin may have none."""
    __tablename__ = "app_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    surname: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str] = mapped_column(String(200), index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), index=True)
    hospital_id: Mapped[int | None] = mapped_column(ForeignKey("hospitals.id"), index=True)
    license_no: Mapped[str | None] = mapped_column(String(50))       # เลขใบประกอบวิชาชีพ (แพทย์)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)

    def to_dict(self):
        return {"id": self.id, "username": self.username, "name": self.name, "surname": self.surname,
                "email": self.email, "role": self.role, "hospital_id": self.hospital_id,
                "license_no": self.license_no, "is_active": self.is_active,
                "created_by": self.created_by,
                "created_at": self.created_at.isoformat() if self.created_at else None,
                "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None}


class ServiceRegistration(Base):
    """One application to register a medical service unit (Env-Occ manual: ขึ้นทะเบียนหน่วยบริการ).

    `data` holds the six steps of the form, `documents` the uploaded PDFs per field, and
    `review_notes` what the reviewer asked to fix. The original files live on disk under
    storage/registrations/, like uploaded result files."""
    __tablename__ = "service_registrations"

    id: Mapped[int] = mapped_column(primary_key=True)
    hospital_id: Mapped[int] = mapped_column(ForeignKey("hospitals.id"), index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("app_users.id"))
    # draft / submitted / changes_requested / approved / issued / cancelled
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    stage: Mapped[int] = mapped_column(Integer, default=1)          # 1..6 on the status timeline
    data: Mapped[dict] = mapped_column(JSON, default=dict)          # {"step1": {...}, ...}
    documents: Mapped[dict] = mapped_column(JSON, default=dict)     # {"field key": [ {...file...} ]}
    review_notes: Mapped[list] = mapped_column(JSON, default=list)  # [{key, label, note, fixed}]
    delivery: Mapped[dict] = mapped_column(JSON, default=dict)      # how the certificate is sent
    certificate_path: Mapped[str | None] = mapped_column(String(1000))
    certificate_downloaded: Mapped[bool] = mapped_column(Boolean, default=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime)
    expires_on: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    def to_dict(self):
        return {
            "id": self.id, "hospital_id": self.hospital_id, "status": self.status, "stage": self.stage,
            "data": self.data or {}, "documents": self.documents or {},
            "review_notes": self.review_notes or [], "delivery": self.delivery or {},
            "has_certificate": bool(self.certificate_path),
            "certificate_downloaded": self.certificate_downloaded,
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "issued_at": self.issued_at.isoformat() if self.issued_at else None,
            "expires_on": self.expires_on.isoformat() if self.expires_on else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
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


class CommentLabel(Base):
    """
    Learned meaning of a free-text finding when a file has no 1/2 column for it:
    (category column, normalized text) -> 1 normal / 2 abnormal. Global (a finding means
    the same in every hospital). Set by the comment agents on agreement, or by a human.
    """
    __tablename__ = "comment_labels"
    __table_args__ = (UniqueConstraint("column", "text_norm"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    column: Mapped[str] = mapped_column(String(100))        # chest_xray / ekg / hearing_ability / far_vision_test
    text_norm: Mapped[str] = mapped_column(String(500))
    value: Mapped[int] = mapped_column(SmallInteger)        # 1 / 2
    origin: Mapped[str] = mapped_column(String(20))         # agent_auto / agent_approved / human
    approved_by: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ---------------------------------------------------------------------------
# The department's schema (D23) — workplaces, people, checkup rounds, results
# ---------------------------------------------------------------------------
# Shapes and keys follow docs/DATA_DICTIONARY.md so a submission lands on the
# department's tables without a second translation. Two deliberate departures,
# both recorded in D23:
#   * `employees` columns the department marks NOT NULL but a lab file cannot
#     know (gender, birth_year, nationality, work_experience, position) are
#     nullable here. The only alternative is inventing them, which breaks the
#     core rule. A row missing them is shown as "ทะเบียนไม่ครบ".
#   * `employee_checkup_batches.survey_id` stays NOT NULL, which is why the
#     Walkthrough survey header is real rather than a mockup.


class Company(Base):
    """สถานประกอบการ. A shared national register (D23): not scoped per hospital,
    because the department keys it by juristic id, and one workplace may be
    served by several hospitals."""
    __tablename__ = "companies"
    __table_args__ = (UniqueConstraint("juristic_id", "branch_name", name="uk_juristic_branch"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    juristic_id: Mapped[str] = mapped_column(String(13), index=True)
    fid: Mapped[str | None] = mapped_column(String(14))
    name: Mapped[str] = mapped_column(String(300))
    branch_name: Mapped[str] = mapped_column(String(200), default="")
    address: Mapped[str | None] = mapped_column(Text)
    industry_group: Mapped[str | None] = mapped_column(String(200))
    industry_group_code: Mapped[str | None] = mapped_column(String(20))
    employee_numbers: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Department(Base):
    """แผนกงานในสถานประกอบการ. This is what D18's department code becomes: a real
    row owned by one company, not free text."""
    __tablename__ = "departments"
    __table_args__ = (UniqueConstraint("name", "company_id", name="uk_name_company_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)


class WalkthroughSurvey(Base):
    """The survey header only (D23). The full risk questionnaire stays a mockup,
    but the header must be real because a checkup round cannot exist without it."""
    __tablename__ = "walkthrough_surveys"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    survey_date: Mapped[date] = mapped_column(Date)
    surveyed_by: Mapped[str | None] = mapped_column(String(200))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class CheckupType(Base):
    """ประเภทการตรวจ. Seeded with the department's three (D23-ก)."""
    __tablename__ = "employee_checkup_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))


class CheckupBatch(Base):
    """รอบตรวจ. The round carries the date, not the file: appoint_date is NOT NULL
    here while a person's own checkup_date may be missing. This is why the upload
    dialog asks for a round first (D23)."""
    __tablename__ = "employee_checkup_batches"
    __table_args__ = (UniqueConstraint("checkup_type", "appoint_date", "survey_id",
                                       name="uk_date_survey_checkup_type"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    checkup_type: Mapped[int] = mapped_column(ForeignKey("employee_checkup_types.id"))
    appoint_date: Mapped[date] = mapped_column(Date)
    survey_id: Mapped[int] = mapped_column(ForeignKey("walkthrough_surveys.id"), index=True)
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_by: Mapped[str | None] = mapped_column(String(100))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    # ours, not the department's: which hospital entered this round
    hospital_id: Mapped[int] = mapped_column(ForeignKey("hospitals.id"), index=True)
    created_by: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


def _registry_column(field):
    """Registry fields are nullable here even where the department says NOT NULL.
    See the note at the top of this section."""
    if field.kind == "numeric":
        return mapped_column(Numeric(*field.precision), nullable=True)
    if field.kind == "id":
        return mapped_column(String(field.size), nullable=False)
    return mapped_column(String(field.size) if field.size else Text, nullable=True)


class Employee(Base):
    """ทะเบียนพนักงาน — who a person is. Holds no results.

    Note for anyone who knew the old schema: before D23 this table name meant
    "one person on one visit, with 40 result columns". It does not any more.
    Results live in EmployeeCheckup.

    The department's key is (citizen_id, department_id), so one person working
    in two departments is two rows, and their histories are separate.
    """
    __tablename__ = "employees"
    __table_args__ = (UniqueConstraint("cid", "department_pk", name="unique_citizen_dept"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    department_pk: Mapped[int] = mapped_column(ForeignKey("departments.id"), index=True)
    source_file_id: Mapped[int | None] = mapped_column(ForeignKey("source_files.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    for _f in REGISTRY_FIELDS:
        if _f.column != "department_id":      # replaced by the department_pk FK
            locals()[_f.column] = _registry_column(_f)
    del _f

    #: department columns the department requires but a lab file cannot supply
    REQUIRED_BY_DDC = ("gender", "birth_year", "nationality", "work_experience", "position")

    @property
    def registry_complete(self) -> bool:
        return all(getattr(self, c) is not None for c in self.REQUIRED_BY_DDC)

    def to_dict(self):
        d = {"id": self.id, "department_pk": self.department_pk,
             "registry_complete": self.registry_complete,
             "created_at": self.created_at.isoformat() if self.created_at else None}
        for f in REGISTRY_FIELDS:
            if f.column == "department_id":
                continue
            v = getattr(self, f.column)
            d[f.column] = float(v) if isinstance(v, Decimal) else v
        return d


def _result_column(field):
    if field.kind == "numeric":
        return mapped_column(Numeric(*field.precision), nullable=True)
    if field.kind == "categorical":
        return mapped_column(SmallInteger, nullable=True)
    return mapped_column(String(field.size) if field.size else Text, nullable=True)


class EmployeeCheckup(Base):
    """ผลตรวจของหนึ่งคนในหนึ่งรอบ. All 40 of our result columns exist in the
    department's 54, so nothing is dropped and nothing is invented.

    Values are stored in the department's units and codes (D23): wbc and plt in
    10^3/uL, rbc_che in U/g Hb, and 0=ปกติ / 1=ผิดปกติ for the categorical ones.
    The raw value as written in the file is kept in ValueProvenance, so a wrong
    reading of the dictionary is reversible (D23-ถาม).
    """
    __tablename__ = "employee_checkups"
    __table_args__ = (UniqueConstraint("employee_id", "checkup_batch_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    checkup_batch_id: Mapped[int] = mapped_column(ForeignKey("employee_checkup_batches.id"), index=True)
    checkup_date: Mapped[date | None] = mapped_column(Date)   # nullable: the round holds the date
    source_file_id: Mapped[int | None] = mapped_column(ForeignKey("source_files.id"), index=True)
    comment: Mapped[str | None] = mapped_column(Text)
    position: Mapped[str | None] = mapped_column(String(200))        # as at the time of this checkup
    work_experience: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=func.now())

    for _f in TEMPLATE_FIELDS:
        if _f.group != "person":
            locals()[_f.column] = _result_column(_f)
    del _f

    def to_dict(self):
        d = {"id": self.id, "employee_id": self.employee_id,
             "checkup_batch_id": self.checkup_batch_id,
             "checkup_date": self.checkup_date.isoformat() if self.checkup_date else None,
             "source_file_id": self.source_file_id, "comment": self.comment}
        for f in TEMPLATE_FIELDS:
            if f.group == "person":
                continue
            v = getattr(self, f.column)
            d[f.column] = float(v) if isinstance(v, Decimal) else v   # 0 stays 0
        return d


class CheckupCategory(Base):
    """หมวดหมู่การตรวจ — built from Field.group."""
    __tablename__ = "checkup_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)


class CheckupList(Base):
    """รายการตรวจ หน่วยวัด และเกณฑ์ปกติ.

    Generated from app/template.py, which stays the single source of truth
    (D23-ก). lower_limit/upper_limit are left NULL on purpose: our template
    carries a *plausible* range used to catch unit errors, which is a different
    number from a clinical *normal* range. Filling these in needs the
    department's own figures (D23-ถาม).
    """
    __tablename__ = "checkup_lists"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    category_id: Mapped[int] = mapped_column(ForeignKey("checkup_categories.id"), index=True)
    unit: Mapped[str | None] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(Text, default="")
    lower_limit: Mapped[float | None] = mapped_column(Float)
    upper_limit: Mapped[float | None] = mapped_column(Float)
    column_name: Mapped[str | None] = mapped_column(String(100))


class ValueProvenance(Base):
    """Where each stored value came from (file / sheet / cell).

    Since D23 this points at one cell of one checkup row, not at a person, and
    raw_value holds the number exactly as the file wrote it — before the unit
    and code conversion into the department's form.
    """
    __tablename__ = "value_provenance"

    id: Mapped[int] = mapped_column(primary_key=True)
    checkup_id: Mapped[int] = mapped_column(ForeignKey("employee_checkups.id", ondelete="CASCADE"), index=True)
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
    """Real results with no column in the department's table (FBS, cholesterol,
    …). Kept, not dropped (D12)."""
    __tablename__ = "extra_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    checkup_id: Mapped[int] = mapped_column(ForeignKey("employee_checkups.id", ondelete="CASCADE"), index=True)
    source_file_id: Mapped[int] = mapped_column(ForeignKey("source_files.id"), index=True)
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
    """Incoming value differs from the stored one. Stored value stays until a
    human decides.

    Since D23 a conflict can only happen inside one checkup round. The same
    person measured again in a later round is a separate row, not a
    disagreement — which is what the word was always supposed to mean.
    """
    __tablename__ = "conflicts"

    id: Mapped[int] = mapped_column(primary_key=True)
    checkup_id: Mapped[int] = mapped_column(ForeignKey("employee_checkups.id", ondelete="CASCADE"), index=True)
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
    checkup_id: Mapped[int] = mapped_column(ForeignKey("employee_checkups.id", ondelete="CASCADE"), index=True)
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
    # mapping / profile / cid / value / comment / identity / department_change /
    # unregistered_person
    kind: Mapped[str] = mapped_column(String(30))
    # which field set the file is being read against: "result" or "registry"
    # (D23-ก). The review screen offers columns from that set only.
    field_set: Mapped[str] = mapped_column(String(20), default="result")
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


# ---------------------------------------------------------------------------
# Reporting to the department (D21)
# ---------------------------------------------------------------------------


class ReportSubmission(Base):
    """
    One round of results handed to the department, the way the Env-Occ manual ends
    its health-report flow (ส่งรายงานผลตรวจ).

    `summary` is a snapshot of the numbers as they were when the button was pressed,
    not a live query: a file that arrives later must not quietly change what a past
    submission says it contained, or the record and the document sent will disagree.
    """
    __tablename__ = "report_submissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    hospital_id: Mapped[int] = mapped_column(ForeignKey("hospitals.id"), index=True)
    year: Mapped[int] = mapped_column(Integer, index=True)       # CE year of visit_date
    people: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    file_sha256: Mapped[str | None] = mapped_column(String(64))  # the export handed over
    note: Mapped[str | None] = mapped_column(Text)
    submitted_by: Mapped[str] = mapped_column(String(100))
    submitted_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
