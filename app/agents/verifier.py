"""
verifier.py (agent)
===================
Checks the Mapper's proposals independently. It sees the same evidence
(label, unit, sample values, other labels in the file) and the proposed
target + unit — but not the Mapper's reasoning or confidence, so it can't
simply agree with the argument (docs/requirements.md D11).

Agreement is decided by code, not by the model's own "agree" flag: the
verifier's target and unit must produce the same target and conversion
factor as the proposal.
"""

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.agents.catalog import catalog_text
from app.agents.mapper import SPECIAL, Target
from app.llm.client import CallMeta, call_structured
from app.pipeline import units as U
from app.template import FIELDS_BY_COLUMN


class VerifyItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int
    verdict: Literal["correct", "wrong", "unsure"]
    target: Target            # the verifier's own answer (same as proposal when "correct")
    unit: str | None
    reason: str               # one short sentence in Thai; required when wrong/unsure


class VerifyResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[VerifyItem]


SYSTEM = f"""You are a strict reviewer of lab-data mappings for Thai hospital (HIS) health-checkup
exports. Another system proposed which template column each label belongs to and which unit its
values are written in. Your job is to catch mistakes before they corrupt medical records.

Template columns:
{catalog_text()}

Special targets: "__extra__" (real result with no column), "__ignore__" (not a result),
"__unknown__" (cannot tell).

For each item decide independently from the evidence (label, unit, sample values, other labels in
the file), then compare with the proposal:
- Check meaning: percent vs absolute count, % predicted vs litres, total vs direct vs indirect,
  plasma vs RBC cholinesterase, a category (normal/abnormal) vs free-text comment.
- Check the unit against the sample magnitudes (e.g. hemoglobin 140 means g/L, not g/dL).
- If another label in the same file already clearly holds that column, be suspicious.
verdict "correct" only if you are confident the proposal is right; "wrong" if you know the right
answer (put it in target/unit); "unsure" otherwise.
"reason": one short sentence in Thai. Answer every id exactly once."""


def verify(items: list[dict], proposals: dict, file_labels: list[str] | None = None, *,
           model: str | None = None, db=None, source_file_id=None) -> tuple[dict, CallMeta]:
    """
    items: [{"id", "label", "unit", "samples", "layout"}]; proposals: {id: {"target", "unit"}}.
    Returns {id: {"verdict", "target", "unit", "factor", "agrees", "reason"}}.
    """
    payload = {"labels_in_this_file": file_labels or [],
               "items": [{**it, "proposed_target": proposals[it["id"]]["target"],
                          "proposed_unit": proposals[it["id"]]["unit"]} for it in items]}
    res, meta = call_structured("verifier", SYSTEM, "Review these proposals:\n" +
                                json.dumps(payload, ensure_ascii=False), VerifyResult,
                                model=model, db=db, source_file_id=source_file_id, log_input=payload)
    out = {}
    got = {v.id: v for v in res.items}
    for it in items:
        v, p = got.get(it["id"]), proposals[it["id"]]
        if v is None:
            out[it["id"]] = {"verdict": "unsure", "target": "__unknown__", "unit": None, "factor": None,
                             "agrees": False, "reason": "ผู้ตรวจไม่ได้ตอบรายการนี้"}
            continue
        factor = _factor(v.target, v.unit)
        agrees = (v.verdict == "correct" and v.target == p["target"] and v.target not in SPECIAL[2:]
                  and _same_factor(factor, p.get("factor")))
        out[it["id"]] = {"verdict": v.verdict, "target": v.target, "unit": v.unit, "factor": factor,
                         "agrees": agrees, "reason": v.reason}
    return out, meta


def _factor(target, unit):
    if target in FIELDS_BY_COLUMN and FIELDS_BY_COLUMN[target].kind == "numeric":
        return U.factor(target, unit)
    return 1.0


def _same_factor(a, b) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= 1e-6 * max(abs(a), abs(b), 1)
