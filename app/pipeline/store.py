"""
store.py
========
Writes an Extraction into the department's tables (D12, D13, D23).

This is the one place that knows about the department's shape. Everything
before it — reader, profiler, mapper, extract — still works in the canonical
45-column template, in canonical units, exactly as it did before and as every
locked test set expects. The translation happens here, once, on the way in:

  - our units and codes  -> the department's (template.ddc_value)
  - one wide row         -> employees + employee_checkups + the round

The rules themselves are unchanged:
  - new cell            -> stored, with provenance holding the raw value
  - same value again    -> skipped
  - different value     -> Conflict (open); the stored value stays
  - extras              -> extra_results
  - review items        -> pending_reviews

Two things can stop a person's results from being written at all, and both
raise a review rather than guessing (D23):
  - the person is not in the register for this workplace
  - the file puts them in a different department than the register does
"""

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import (
    CheckupBatch, Conflict, Department, Employee, EmployeeCheckup, ExtraResult,
    PendingReview, SourceFile, ValueProvenance, WalkthroughSurvey,
)
from app.approval import revoke_if_approved
from app.template import FIELDS_BY_COLUMN, ddc_value


def _same(col, a, b) -> bool:
    if FIELDS_BY_COLUMN[col].kind in ("numeric", "categorical"):
        return abs(float(a) - float(b)) < 0.005
    return str(a).strip() == str(b).strip()


def _typed(col, value):
    kind = FIELDS_BY_COLUMN[col].kind
    if kind == "numeric":
        return Decimal(str(value))
    if kind == "categorical":
        return int(value)
    return value


def _company_of(db: Session, batch: CheckupBatch) -> int:
    return db.get(WalkthroughSurvey, batch.survey_id).company_id


def save(db: Session, sf: SourceFile, ex) -> dict:
    """Results file -> the department's tables. Needs sf.checkup_batch_id."""
    stats = {"stored": 0, "skipped_same": 0, "conflicts": 0, "extras": 0,
             "reviews": len(ex.reviews), "unregistered": 0, "department_change": 0}

    batch = db.get(CheckupBatch, sf.checkup_batch_id) if sf.checkup_batch_id else None
    if batch is None:
        # Not an error the pipeline can fix: the round is chosen before the file
        # is picked, so arriving here without one is a bug in the caller.
        raise ValueError("ไฟล์ผลตรวจต้องผูกกับรอบตรวจ (checkup_batch_id) ก่อนบันทึก")
    company_id = _company_of(db, batch)

    # the register for this workplace, keyed the way the department keys it
    people = {
        (e.cid, e.department_pk): e
        for e in db.query(Employee).join(Department, Department.id == Employee.department_pk)
                   .filter(Department.company_id == company_id)
    }
    by_cid: dict[str, list[Employee]] = {}
    for (cid, _), e in people.items():
        by_cid.setdefault(cid, []).append(e)
    departments = {d.name: d.id for d in db.query(Department).filter(Department.company_id == company_id)}
    dept_name = {v: k for k, v in departments.items()}

    # Answers already given for THIS file. A file is re-read after every save, so without
    # remembering them "the file is wrong, use the register" left the results unsaved and
    # asked the same question again, for ever.
    use_register, chosen_dept = set(), {}
    for r in (db.query(PendingReview)
              .filter(PendingReview.source_file_id == sf.id, PendingReview.status == "approved",
                      PendingReview.kind.in_(("department_change", "which_department")))):
        d = r.decision or {}
        if d.get("action") == "use_register":
            use_register.add(r.payload["cid"])
        elif d.get("action") == "choose_department":
            chosen_dept[r.payload["cid"]] = d.get("department")

    reported, checkups = set(), {}

    # A person whose only values in this file are "extras" has no cells but does have
    # something to keep. Skipping them dropped those values silently — and the file still
    # said "completed", because nothing was left to ask about.
    extra_keys = {(e["cid"], e["visit_date"]) for e in ex.extras}

    for (cid, vd), row in ex.rows.items():
        if not row["cells"] and (cid, vd) not in extra_keys:
            continue                      # nothing usable for this person yet

        candidates = by_cid.get(cid, [])
        if not candidates:
            if cid not in reported:
                reported.add(cid)
                stats["unregistered"] += 1
                name = " ".join(x for x in (row["person"].get("first_name"),
                                            row["person"].get("last_name")) if x)
                # The workplace's departments travel with the question. A results
                # file often has no department column at all, and without this the
                # reviewer is asked to add someone with nowhere to put them.
                ex.reviews.append({"kind": "unregistered_person", "payload": {
                    "cid": cid, "name_in_file": name or None,
                    "department_in_file": row["person"].get("department_id"),
                    "known_departments": sorted(departments),
                    "values_waiting": len(row["cells"]),
                    "reason": "ไม่พบเลขบัตรนี้ในทะเบียนพนักงานของสถานประกอบการนี้ "
                              "— ผลตรวจของคนนี้ยังไม่ถูกบันทึก"}})
            continue

        # Which of this person's department rows does the file mean? The register
        # decides; the file only gets to disagree, and a disagreement is a question.
        # Nothing here picks a row on a guess: a name that matches no row, a person in
        # two departments with no department in the file, and a name that is no
        # department at all are all questions. (The first version took candidates[0] in
        # every one of those cases, and a person in two departments was filed under the
        # first with no one asked.)
        dept_in_file = (row["person"].get("department_id") or "").strip() or None
        names = sorted(dept_name[e.department_pk] for e in candidates)
        emp = None
        if cid in chosen_dept:                                  # the reviewer already picked
            emp = next((e for e in candidates if dept_name[e.department_pk] == chosen_dept[cid]), None)
        elif dept_in_file:
            match = [e for e in candidates if dept_name[e.department_pk] == dept_in_file]
            if match:
                emp = match[0]
            elif cid in use_register and len(candidates) == 1:  # "the file is wrong" was answered
                emp = candidates[0]
        elif len(candidates) == 1:
            emp = candidates[0]

        if emp is None:
            if cid not in reported:
                reported.add(cid)
                stats["department_change"] += 1
                if dept_in_file:
                    ex.reviews.append({"kind": "department_change", "payload": {
                        "cid": cid, "department_in_register": ", ".join(names),
                        "department_in_file": dept_in_file, "known_departments": sorted(departments),
                        "values_waiting": len(row["cells"]),
                        "reason": "แผนกในไฟล์ไม่ตรงกับทะเบียน — ย้ายแผนกจริง "
                                  "หรือไฟล์เขียนผิด ต้องให้คนตัดสิน"}})
                else:
                    ex.reviews.append({"kind": "which_department", "payload": {
                        "cid": cid, "candidates": names, "values_waiting": len(row["cells"]),
                        "reason": "คนนี้อยู่ในทะเบียนหลายแผนก และไฟล์ไม่ได้บอกว่าเป็นแผนกไหน "
                                  "— ระบบไม่เลือกให้"}})
            continue

        checkup = checkups.get(emp.id)
        if checkup is None:
            checkup = (db.query(EmployeeCheckup)
                       .filter(EmployeeCheckup.employee_id == emp.id,
                               EmployeeCheckup.checkup_batch_id == batch.id).one_or_none())
            if checkup is None:
                checkup = EmployeeCheckup(employee_id=emp.id, checkup_batch_id=batch.id,
                                          source_file_id=sf.id)
                db.add(checkup)
                db.flush()
            checkups[emp.id] = checkup

        # the person's own date if the file gave one, otherwise the round's
        visit = date.fromisoformat(vd)
        if checkup.checkup_date is None and visit != batch.appoint_date:
            checkup.checkup_date = visit

        for col, (val, prov) in row["cells"].items():
            stored_form = ddc_value(col, val)
            old = getattr(checkup, col)
            if old is None:
                setattr(checkup, col, _typed(col, stored_form))
                # raw_value keeps what the file said, before any conversion, so a
                # wrong reading of the dictionary can be undone (D23-ถาม)
                db.add(ValueProvenance(checkup_id=checkup.id, column=col,
                                       source_file_id=sf.id, **prov))
                stats["stored"] += 1
            elif _same(col, old, stored_form):
                stats["skipped_same"] += 1
            else:
                # A file can be processed more than once — answering a review about
                # one person re-runs the whole file — and the disagreement it found
                # the first time is still there. Asking about it again would put the
                # same decision on the screen twice, and deciding one copy would
                # leave the other open forever.
                dup = (db.query(Conflict)
                       .filter(Conflict.checkup_id == checkup.id, Conflict.column == col,
                               Conflict.status == "open",
                               Conflict.incoming_value == str(stored_form)).first())
                if dup is None:
                    db.add(Conflict(checkup_id=checkup.id, column=col,
                                    current_value=str(old), incoming_value=str(stored_form),
                                    source_file_id=sf.id, provenance=prov, status="open"))
                    stats["conflicts"] += 1

    # extras hang off the checkup row of the person they belong to
    for e in ex.extras:
        holder = None
        for emp in by_cid.get(e["cid"], []):
            if emp.id in checkups:
                holder = checkups[emp.id]
                break
        if holder is None:
            continue          # their results were not written, so neither is this
        dup = (db.query(ExtraResult)
               .filter_by(checkup_id=holder.id, source_name=e["source_name"]).first())
        if dup:
            continue
        db.add(ExtraResult(checkup_id=holder.id, source_file_id=sf.id,
                           source_name=e["source_name"], value_num=e["value_num"],
                           value_text=e["value_text"], unit=e["unit"],
                           sheet=e["sheet"], cell=e["cell"]))
        stats["extras"] += 1

    # New values in a round someone has already approved: the approval described results
    # that are no longer the results. It says so in the file's stats, so the screen can.
    if (stats["stored"] or stats["extras"]) and revoke_if_approved(db, batch):
        stats["approval_revoked"] = True

    stats["reviews"] = len(ex.reviews)
    for r in ex.reviews:
        db.add(PendingReview(source_file_id=sf.id, kind=r["kind"], payload=r["payload"],
                             field_set=sf.field_set or "result", status="open"))
    return stats
