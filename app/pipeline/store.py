"""
store.py
========
Writes an Extraction to the DB (D12, D13):
  - new cell            -> stored, with provenance
  - same value again    -> skipped
  - different value     -> Conflict (open); the stored value stays until a human decides
  - extras              -> extra_results
  - review items        -> pending_reviews
"""

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import Conflict, Employee, ExtraResult, PendingReview, SourceFile, ValueProvenance
from app.pipeline.extract import Extraction
from app.template import FIELDS_BY_COLUMN


def _same(col, a, b) -> bool:
    if FIELDS_BY_COLUMN[col].kind in ("numeric", "categorical"):
        return abs(float(a) - float(b)) < 0.005
    return str(a).strip() == str(b).strip()


def save(db: Session, sf: SourceFile, ex: Extraction) -> dict:
    stats = {"stored": 0, "skipped_same": 0, "conflicts": 0, "extras": 0, "reviews": len(ex.reviews)}
    for (cid, vd), row in ex.rows.items():
        visit = date.fromisoformat(vd)
        emp = db.query(Employee).filter(Employee.cid == cid, Employee.visit_date == visit).one_or_none()
        if emp is None:
            if not row["cells"]:
                continue   # nothing usable for this person yet (all flagged)
            emp = Employee(cid=cid, visit_date=visit, hospital_id=sf.hospital_id, source_file_id=sf.id)
            db.add(emp)
            db.flush()
        for col, val in row["person"].items():
            if val is not None and getattr(emp, col) is None:
                setattr(emp, col, val)
        for col, (val, prov) in row["cells"].items():
            old = getattr(emp, col)
            if old is None:
                setattr(emp, col, Decimal(str(val)) if FIELDS_BY_COLUMN[col].kind == "numeric" else val)
                db.add(ValueProvenance(employee_id=emp.id, column=col, source_file_id=sf.id, **prov))
                stats["stored"] += 1
            elif _same(col, old, val):
                stats["skipped_same"] += 1
            else:
                db.add(Conflict(employee_id=emp.id, column=col, current_value=str(old), incoming_value=str(val),
                                source_file_id=sf.id, provenance=prov, status="open"))
                stats["conflicts"] += 1

    for e in ex.extras:
        dup = db.query(ExtraResult).filter_by(cid=e["cid"], visit_date=date.fromisoformat(e["visit_date"]),
                                              source_name=e["source_name"]).first()
        if dup:
            continue
        db.add(ExtraResult(hospital_id=sf.hospital_id, source_file_id=sf.id, cid=e["cid"],
                           visit_date=date.fromisoformat(e["visit_date"]), source_name=e["source_name"],
                           value_num=e["value_num"], value_text=e["value_text"], unit=e["unit"],
                           sheet=e["sheet"], cell=e["cell"]))
        stats["extras"] += 1

    for r in ex.reviews:
        db.add(PendingReview(source_file_id=sf.id, kind=r["kind"], payload=r["payload"], status="open"))
    return stats
