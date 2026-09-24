"""
Review routes (D9)
==================
GET  /api/reviews?status=open&file_id=…   items waiting for a human, with the evidence
GET  /api/files/{id}                       status of one uploaded file
POST /api/files/{id}/decisions             reviewer decisions -> resume the file's graph
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.auth import require_user
from app.database import get_db
from app.database import SessionLocal
from app.graph import service
from app.pipeline.run import dismissed_keys, process_file, without_dismissed
from app.models import (
    TARGET_EXTRA, CheckupBatch, Department, Employee, PendingReview, SourceFile, WalkthroughSurvey,
)
from app.pipeline import units as U
from app.template import COLUMNS, FIELDS_BY_COLUMN, RESULT_COLUMNS, ddc_unit

router = APIRouter(prefix="/api", tags=["reviews"])


class Decision(BaseModel):
    review_id: int
    action: Literal["approve", "set", "extra", "ignore", "skip", "identity", "comment", "department",
                    "register", "move_department", "use_register", "choose_department",
                    # register-file answers (D23)
                    "add_department", "keep", "replace",
                    # "I fixed the source file" — closes an item that has no answer to give
                    "dismiss"]
    target: str | None = None
    unit: str | None = None       # unit the values are written in (for "set"); factor computed from it
    factor: float | None = None   # explicit factor (overrides unit)
    role: str | None = None       # identity review: which role the chosen column holds
    header: str | None = None     # identity review: the column header
    value: int | None = None      # comment review: 1 normal / 2 abnormal (applies to every row with this text)
    code: str | None = None       # department review: the code for this department name (D18)
    first_name: str | None = None  # unregistered_person: the name to file them under
    last_name: str | None = None
    # "extra" (CONTEXT.md "คอลัมน์ของบริษัท"): either column_id (pick an existing company
    # column) or column_name + column_kind (name a new one; column_unit for numeric)
    column_id: int | None = None
    column_name: str | None = None
    column_kind: Literal["numeric", "text"] | None = None
    column_unit: str | None = None


class DecisionBody(BaseModel):
    decisions: list[Decision]
    by: str = "reviewer"


def _review_dict(r: PendingReview) -> dict:
    return {"id": r.id, "source_file_id": r.source_file_id, "kind": r.kind, "payload": r.payload,
            "status": r.status, "decision": r.decision, "created_at": r.created_at.isoformat() if r.created_at else None}


@router.get("/template/columns")
def template_columns(all: bool = False, user=Depends(require_user)):
    """
    Result columns for the reviewer's "set" choice.

    `all=true` adds the five person columns and each column's template header and
    group, so a page can lay out a person's results without hard-coding the 45
    columns again: template.py stays the single source of truth.
    """
    from app.agents.catalog import DESC
    columns = COLUMNS if all else RESULT_COLUMNS
    out = []
    for c in columns:
        f = FIELDS_BY_COLUMN[c]
        row = {"column": c, "kind": f.kind, "unit": f.unit, "desc": DESC.get(c, f.header),
               "units": U.accepted_units(c) if f.kind == "numeric" else []}
        if all:
            # stored_unit: the unit employee_checkups holds it in (D23, the department's
            # form) — what a page showing stored values must label them with, e.g. wbc
            # 4.7 is 10^3/uL there, not cells/µL
            row.update(header=f.header, group=f.group, stored_unit=ddc_unit(c))
        out.append(row)
    return out


@router.get("/registry/columns")
def registry_columns(user=Depends(require_user)):
    """The register's own fields. A question about a register file must offer these,
    not the 45 lab columns: asking which blood test “ตำแหน่งงาน” is has no answer."""
    from app.template import REGISTRY_FIELDS, REGISTRY_LABEL_TH
    return [{"column": f.column, "header": REGISTRY_LABEL_TH.get(f.column, f.header),
             "kind": f.kind} for f in REGISTRY_FIELDS]


@router.get("/reviews")
def list_reviews(status: str = "open", file_id: int | None = None, round_id: int | None = None,
                 limit: int = 5000, db: Session = Depends(get_db), user=Depends(require_user)):
    """
    The cap used to be a silent 500. Reviews are the only way an item waiting for a
    human is visible at all, so anything past the cap waited forever with nothing on
    the screen to say so: on 2026-09-16 one database held 521 open reviews and the page
    showed 3 of the 24 mapping questions. Callers now choose the cap and can tell they
    hit it, because the answer comes back exactly `limit` long.

    `round_id` scopes to one round's "งานที่ต้องตรวจ" panel: its own results files,
    plus its company's registry files (a registry file has no round of its own, but a
    reviewer looking at one round still needs to see "this company's department is
    unknown" — leaving it out would look like nothing is waiting when something is).
    """
    q = db.query(PendingReview).filter(PendingReview.status == status)
    if file_id is not None:
        q = q.filter(PendingReview.source_file_id == file_id)
    if round_id is not None:
        b = db.get(CheckupBatch, round_id)
        if b is None:
            raise HTTPException(404, "ไม่พบรอบตรวจ")
        survey = db.get(WalkthroughSurvey, b.survey_id)
        file_ids = [fid for (fid,) in db.query(SourceFile.id).filter(
            (SourceFile.checkup_batch_id == round_id)
            | (SourceFile.company_id == (survey.company_id if survey else -1)))]
        q = q.filter(PendingReview.source_file_id.in_(file_ids))
    return [_review_dict(r) for r in q.order_by(desc(PendingReview.id)).limit(max(1, limit))]


@router.get("/files/{file_id}")
def file_status(file_id: int, db: Session = Depends(get_db), user=Depends(require_user)):
    if db.get(SourceFile, file_id) is None:
        raise HTTPException(404, "ไม่พบไฟล์")
    db.close()   # never hold a transaction open while the graph/checkpointer works
    return service.status(file_id)


def _company_of_file(db: Session, sf: SourceFile) -> int | None:
    if sf.company_id:
        return sf.company_id
    batch = db.get(CheckupBatch, sf.checkup_batch_id) if sf.checkup_batch_id else None
    if batch is None:
        return None
    survey = db.get(WalkthroughSurvey, batch.survey_id)
    return survey.company_id if survey else None


def _apply_people_decision(db: Session, sf: SourceFile, r: PendingReview, d: Decision, by: str) -> None:
    """The two decisions that change the register rather than a mapping (D23).

    They are applied here, against the database, instead of being handed to the
    graph: the graph answers "what does this label mean", and these answer "who is
    this person". Re-processing the file afterwards is what actually stores the
    results that were held back.
    """
    company_id = _company_of_file(db, sf)
    if company_id is None:
        raise HTTPException(400, "ไฟล์นี้ยังไม่ผูกกับสถานประกอบการ")

    if r.kind == "unregistered_person":
        dept_name = d.header or r.payload.get("department_in_file")
        if not dept_name:
            # A results file often carries no department. Saying which one is part
            # of the answer, not a failure — the screen asks for it.
            raise HTTPException(400, "ต้องเลือกแผนกที่จะเพิ่มคนนี้เข้าไปด้วย")
        dept = (db.query(Department)
                .filter(Department.company_id == company_id, Department.name == dept_name).one_or_none())
        if dept is None:
            raise HTTPException(400, f"ไม่มีแผนก “{dept_name}” ในสถานประกอบการนี้ "
                                     f"— เพิ่มแผนกที่หน้าทะเบียนสถานประกอบการก่อน")
        first, last = d.first_name, d.last_name
        if not first and not last:
            # The name in the file is a suggestion, not an answer; the reviewer may
            # correct it, but a person is never added with no name at all.
            parts = (r.payload.get("name_in_file") or "").split()
            first, last = (parts[0] if parts else None), (" ".join(parts[1:]) or None)
        if not first:
            raise HTTPException(400, "ต้องระบุชื่ออย่างน้อยหนึ่งช่องก่อนเพิ่มเข้าทะเบียน")
        # Two files can each ask about the same stranger, and the same question can
        # be answered twice. Inserting blindly hits the (citizen_id, department_id)
        # key, and the 500 that follows throws away every other answer saved with it.
        # Someone who is already there is the outcome this decision asked for.
        already = (db.query(Employee)
                   .filter(Employee.cid == r.payload["cid"],
                           Employee.department_pk == dept.id).one_or_none())
        if already is None:
            db.add(Employee(cid=r.payload["cid"], department_pk=dept.id,
                            first_name=first, last_name=last, source_file_id=sf.id))
        elif not already.first_name and first:
            already.first_name, already.last_name = first, last
        return

    if r.kind == "which_department":
        if d.header not in (r.payload.get("candidates") or []):
            raise HTTPException(400, "เลือกได้เฉพาะแผนกที่คนนี้อยู่ในทะเบียน")
        return

    # department_change
    person = (db.query(Employee).join(Department, Department.id == Employee.department_pk)
              .filter(Employee.cid == r.payload["cid"], Department.company_id == company_id).first())
    if person is None:
        raise HTTPException(400, "ไม่พบคนนี้ในทะเบียนแล้ว")
    if d.action == "use_register":
        return                      # the file was wrong; the register stands, results land as they are
    target = (db.query(Department)
              .filter(Department.company_id == company_id,
                      Department.name == r.payload["department_in_file"]).one_or_none())
    if target is None:
        raise HTTPException(400, f"ไม่มีแผนก “{r.payload['department_in_file']}” ในสถานประกอบการนี้")
    # The department keys people by (citizen_id, department_id), so someone who has
    # genuinely moved is a second row, not an edited one — their history in the old
    # department stays where it happened.
    exists = (db.query(Employee)
              .filter(Employee.cid == person.cid, Employee.department_pk == target.id).one_or_none())
    if exists is None:
        db.add(Employee(cid=person.cid, department_pk=target.id, first_name=person.first_name,
                        last_name=person.last_name, title=person.title, gender=person.gender,
                        birth_year=person.birth_year, nationality=person.nationality,
                        position=person.position, work_experience=person.work_experience,
                        medical_condition=person.medical_condition, source_file_id=sf.id))


REGISTRY_KINDS = ("mapping", "identity", "unknown_department", "registry_value")

# Items with no answer to give: the fix is in the source file. They used to stay open
# for ever, even after a corrected file was uploaded, because nothing can tell that an
# invalid id "was fixed" — it never links to a person. A person says so instead.
DISMISSABLE = ("cid", "value", "profile", "row_missing_department")


def _dismiss(r: PendingReview, d: "Decision", by: str) -> bool:
    """True if this review was closed now. Anything but 'dismiss' or 'skip' is refused."""
    if d.action == "skip" or r.status != "open":
        return False
    if d.action != "dismiss":
        raise HTTPException(400, f"รายการ {r.id}: รายการนี้ตอบไม่ได้ ทำได้แค่ปิดเมื่อแก้ไฟล์ต้นฉบับแล้ว")
    r.status, r.decision, r.decided_by = "dismissed", {"action": "dismiss"}, by
    return True


def _refresh_status(db: Session, sf: SourceFile) -> None:
    from app.models import Conflict
    if sf.status == "failed":
        return
    waiting = (db.query(PendingReview).filter(PendingReview.source_file_id == sf.id,
                                              PendingReview.status == "open").count()
               + db.query(Conflict).filter(Conflict.source_file_id == sf.id, Conflict.status == "open").count())
    sf.status = "awaiting_review" if waiting else "completed"


def _decide_registry(db: Session, sf: SourceFile, body: DecisionBody) -> dict:
    """Answers to a register file's questions (D23).

    A register file never goes through the agent graph — upload_registry calls
    registry.import_registry directly — so there is no paused thread to resume and
    process_file would read it as a results file. Until 2026-09-21 the answers went
    down that path anyway: every one returned 500 and left the register marked
    `failed`, which is how a whole step of the department's flow was unanswerable.
    """
    from app.pipeline.mapper import norm_label
    from app.pipeline.reader import read_file
    from app.pipeline.registry import REG_IGNORE, REG_PREFIX, import_registry
    from app.models import LabMapping
    from app.template import REGISTRY_BY_COLUMN

    def learn(label: str, column: str) -> None:
        key = norm_label(label)
        row = (db.query(LabMapping)
               .filter(LabMapping.hospital_id == sf.hospital_id,
                       LabMapping.source_name == key).one_or_none())
        if row is None:
            db.add(LabMapping(hospital_id=sf.hospital_id, source_name=key,
                              target_column=f"{REG_PREFIX}{column}", origin="human"))
        else:
            row.target_column = f"{REG_PREFIX}{column}"

    for d in body.decisions:
        r = db.get(PendingReview, d.review_id)
        if r is None or r.source_file_id != sf.id or r.kind not in REGISTRY_KINDS + DISMISSABLE:
            raise HTTPException(400, f"รายการ {d.review_id} ไม่ใช่คำถามของไฟล์ทะเบียนนี้")
        if r.kind in DISMISSABLE:
            _dismiss(r, d, body.by)
            continue
        if d.action == "skip" or r.status != "open":
            continue          # a re-send after a partial failure must not decide twice

        if r.kind == "mapping":
            if d.action == "ignore":
                learn(r.payload["label"], REG_IGNORE)
            elif d.action == "set":
                if d.target not in REGISTRY_BY_COLUMN:
                    raise HTTPException(400, f"ไม่มีช่อง {d.target} ในทะเบียนพนักงาน")
                learn(r.payload["label"], d.target)
            else:
                raise HTTPException(400, f"รายการ {d.review_id}: เลือกช่องในทะเบียน หรือ “ไม่ใช่ข้อมูลทะเบียน”")

        elif r.kind == "identity":
            if d.action != "identity" or not d.header or d.role not in (r.payload.get("missing") or []):
                raise HTTPException(400, f"รายการ {d.review_id}: ต้องเลือกคอลัมน์ในไฟล์")
            learn(d.header, d.role)

        elif r.kind == "unknown_department":
            if d.action != "add_department":
                raise HTTPException(400, f"รายการ {d.review_id}: ต้องเลือกว่าจะทำอย่างไรกับแผนกนี้")
            name = r.payload["department_in_file"]
            exists = (db.query(Department)
                      .filter(Department.company_id == sf.company_id,
                              Department.name == name).one_or_none())
            if exists is None:
                db.add(Department(name=name, company_id=sf.company_id))

        else:   # registry_value
            if d.action not in ("keep", "replace"):
                raise HTTPException(400, f"รายการ {d.review_id}: เลือกเก็บค่าเดิมหรือใช้ค่าใหม่")
            if d.action == "replace":
                person = db.get(Employee, r.payload["employee_id"])
                if person is None:
                    raise HTTPException(400, "ไม่พบคนนี้ในทะเบียนแล้ว")
                setattr(person, r.payload["column"], r.payload["raw"])

        r.status, r.decision, r.decided_by = "approved", {"action": d.action}, body.by

    db.commit()

    # Re-read the file with the answers in place: that is what actually imports the
    # rows that were held back. Only now are the leftover questions replaced.
    with open(sf.stored_path, "rb") as fh:
        content = fh.read()
    db.query(PendingReview).filter(PendingReview.source_file_id == sf.id,
                                   PendingReview.status == "open").delete()
    result = import_registry(db, read_file(content, sf.file_type), sf.hospital_id,
                             sf.company_id, sf.id)
    result.reviews = without_dismissed(result.reviews, dismissed_keys(db, sf.id))
    for item in result.reviews:
        db.add(PendingReview(source_file_id=sf.id, kind=item["kind"], payload=item["payload"],
                             field_set="registry", status="open"))
    sf.stats = result.as_stats()
    sf.status = "awaiting_review" if result.reviews else "completed"
    sf.errors = []
    db.commit()
    return {"upload_id": sf.id, "status": sf.status, "stats": sf.stats, "errors": [],
            "waiting_for_human": bool(result.reviews)}


@router.post("/files/{file_id}/decisions")
def decide(file_id: int, body: DecisionBody, db: Session = Depends(get_db), user=Depends(require_user)):
    sf = db.get(SourceFile, file_id)
    if sf is None:
        raise HTTPException(404, "ไม่พบไฟล์")
    # Who decided comes from the session, never from the browser. It was taking the
    # client's word for it, and the client always said "reviewer", so decided_by named
    # nobody — the same trace manual entry is careful to keep (see routes/manual.py).
    body.by = user.username
    if sf.field_set == "registry":
        return _decide_registry(db, sf, body)
    decisions, touched_people, dismissed = [], False, False
    for d in body.decisions:
        r = db.get(PendingReview, d.review_id)
        if r is not None and r.source_file_id == file_id and r.kind in DISMISSABLE:
            dismissed = _dismiss(r, d, body.by) or dismissed
            continue
        if r is None or r.source_file_id != file_id or r.kind not in (
                "mapping", "identity", "comment", "department",
                "unregistered_person", "department_change", "which_department"):
            raise HTTPException(400, f"รายการ {d.review_id} ไม่ใช่รายการจับคู่ของไฟล์นี้")
        if r.kind in ("unregistered_person", "department_change", "which_department"):
            if d.action == "skip" or r.status != "open":
                continue
            wanted = {"unregistered_person": ("register",),
                      "department_change": ("move_department", "use_register"),
                      "which_department": ("choose_department",)}[r.kind]
            if d.action not in wanted:
                raise HTTPException(400, f"รายการ {d.review_id}: ต้องเลือกว่าจะทำอย่างไรกับคนนี้")
            _apply_people_decision(db, sf, r, d, body.by)
            # the chosen department is part of the answer: the file is re-read next, and
            # store.py finds it here rather than asking again
            decision = {"action": d.action}
            if d.action == "choose_department":
                decision["department"] = d.header
            r.status, r.decision, r.decided_by = "approved", decision, body.by
            touched_people = True
            continue
        if r.kind == "department":
            if d.action == "skip":
                continue
            from app.pipeline.normalize import looks_like_code
            if d.action != "department" or not d.code or not looks_like_code(d.code):
                raise HTTPException(400, f"รายการ {d.review_id}: ใส่รหัสแผนก (ตัวอักษรอังกฤษ/ตัวเลข เช่น QC, PROD-01)")
            decisions.append({"action": "department", "name": r.payload["name"], "code": d.code.strip(),
                              "by": body.by})
            continue
        if r.kind == "comment":
            if d.action == "skip":
                continue
            if d.action != "comment" or d.value not in (1, 2):
                raise HTTPException(400, f"รายการ {d.review_id}: เลือกปกติ (1) หรือผิดปกติ (2)")
            decisions.append({"action": "comment", "column": r.payload["column"], "text": r.payload["text"],
                              "value": d.value, "by": body.by})
            continue
        if r.kind == "identity":
            if d.action == "skip":
                continue
            if d.action != "identity" or d.role not in (r.payload.get("missing") or []) or not d.header:
                raise HTTPException(400, f"รายการ {d.review_id}: ต้องเลือกคอลัมน์ให้ข้อมูลที่หาไม่พบ")
            decisions.append({"action": "identity", "role": d.role, "header": d.header, "by": body.by})
            continue
        if d.action not in ("approve", "set", "extra", "ignore", "skip"):
            # Anything else used to reach the agent graph, which raised ValueError inside
            # its paused thread: a 500, and a thread left resumed halfway.
            raise HTTPException(400, f"รายการ {d.review_id}: คำตอบ “{d.action}” ใช้กับคำถามนี้ไม่ได้")
        if (d.action == "approve" and r.payload.get("company_id")
                and (r.payload.get("proposal") or {}).get("target") == TARGET_EXTRA):
            # agreeing to the model's bare "__extra__" would store a nameless row again;
            # in a company's file that answer is a company column a person names
            raise HTTPException(400, f"รายการ {d.review_id}: เลือก “เป็นผลตรวจจริง แต่ไม่มีช่องในแบบฟอร์ม” "
                                     f"แล้วเลือกหรือตั้งชื่อคอลัมน์ของบริษัท")
        out = {"label": r.payload["label"], "unit": r.payload.get("unit"), "action": d.action, "by": body.by}
        if d.action == "set":
            if d.target not in RESULT_COLUMNS:
                raise HTTPException(400, f"ไม่มีคอลัมน์ {d.target} ใน template")
            factor = d.factor
            if factor is None:
                factor = U.factor(d.target, d.unit) if FIELDS_BY_COLUMN[d.target].kind == "numeric" else 1.0
            if factor is None:
                raise HTTPException(400, f"ไม่รู้จักหน่วย '{d.unit}' สำหรับ {d.target}")
            out.update(target=d.target, factor=factor)
        if d.action == "extra":
            # a company column (CONTEXT.md): pick an existing one, or name a new one
            if not d.column_id and not (d.column_name and d.column_kind):
                raise HTTPException(400, f"รายการ {d.review_id}: เลือกคอลัมน์ที่มีอยู่แล้ว "
                                         f"หรือตั้งชื่อ+ชนิดข้อมูลของคอลัมน์ใหม่")
            out.update(column_id=d.column_id, column_name=d.column_name,
                      column_kind=d.column_kind, column_unit=d.column_unit)
        decisions.append(out)
    if dismissed:
        db.flush()
        _refresh_status(db, sf)
        db.commit()
        if not decisions and not touched_people:
            # only items were closed: nothing to re-run, and re-running would only look at
            # the same file again
            db.close()
            return service.status(file_id)
    if touched_people:
        db.commit()
    # close the request's read transaction first: resuming the graph can run LLM calls
    # for minutes, and an open transaction blocks Postgres DDL (see app/routes/upload.py)
    db.close()
    if not decisions and touched_people:
        # Nothing for the graph to answer, but the file must run again: that is what
        # stores the results that were waiting on these people.
        with SessionLocal() as db2:
            process_file(db2, db2.get(SourceFile, file_id))
        return service.status(file_id)
    return service.decide(file_id, decisions)
