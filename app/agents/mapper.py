"""
mapper.py (agent)
=================
Proposes what an unknown label means. The LLM picks a target and says which
unit the values are written in; code computes the conversion factor
(app/pipeline/units.py). The LLM never produces numbers that get stored.

A proposal is only a proposal: the Verifier checks it and a human approves
it before it becomes a mapping (docs/requirements.md D9, D11).
"""

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.agents.catalog import catalog_text
from app.llm.client import CallMeta, call_structured
from app.pipeline import units as U
from app.template import FIELDS_BY_COLUMN, RESULT_COLUMNS

SPECIAL = ["__extra__", "__ignore__", "__unknown__"]
Target = Literal[tuple(RESULT_COLUMNS + SPECIAL)]


class MapItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int
    target: Target
    unit: str | None          # unit the values are written in (e.g. "g/L"); null if none/categorical/text
    confidence: Literal["high", "medium", "low"]
    reason: str               # one short sentence in Thai, shown to the reviewer


class MapResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[MapItem]


SYSTEM = f"""You map column headers / lab-test names from Thai hospital (HIS) health-checkup exports
to a fixed occupational-health template. Data may be Thai or English.

Template columns:
{catalog_text()}

Special targets:
- "__extra__": a real test result that has NO column above (e.g. FBS, cholesterol, HbA1c,
  RBC count, indirect bilirubin, absolute cell counts). It is kept separately.
- "__ignore__": not a test result at all (hospital number, visit number, order number, ward,
  row number, doctor name, ...).
- "__unknown__": you are not sure. Prefer this over a guess — a wrong mapping corrupts
  medical records, an "__unknown__" only asks a human.

Rules:
- Match meaning, not spelling. Watch percent vs absolute count, % predicted vs litres,
  total vs direct vs indirect, and the sample values (their magnitude tells the unit).
- "unit": the unit the VALUES are written in, e.g. "g/L", "µmol/L", "10^3/µL", "L/L", "m".
  If a unit is given in the input, repeat it. If none is given, infer it from the sample
  magnitude (e.g. hemoglobin values around 140 are g/L). Use null for categorical/text columns.
- "confidence": high only if you would bet a patient record on it.
- "reason": one short sentence in Thai.
Answer every input id exactly once."""


def build_user(items: list[dict], file_labels: list[str] | None = None) -> str:
    payload = {"labels_in_this_file": file_labels or [], "items": items}
    return "Map these items:\n" + json.dumps(payload, ensure_ascii=False)


def propose(items: list[dict], file_labels: list[str] | None = None, *, model: str | None = None,
            db=None, source_file_id=None) -> tuple[list[dict], CallMeta]:
    """
    items: [{"id", "label", "unit", "samples", "layout"}] — no names, no CIDs.
    Returns one dict per item: target, unit, factor (None = unusable unit), confidence, reason.
    """
    res, meta = call_structured("mapper", SYSTEM, build_user(items, file_labels), MapResult,
                                model=model, db=db, source_file_id=source_file_id,
                                log_input={"items": items})
    by_id = {it.id: it for it in res.items}
    out = []
    for item in items:
        p = by_id.get(item["id"])
        if p is None:
            out.append({"id": item["id"], "target": "__unknown__", "unit": None, "factor": None,
                        "confidence": "low", "reason": "โมเดลไม่ได้ตอบรายการนี้"})
            continue
        factor = 1.0
        if p.target in FIELDS_BY_COLUMN and FIELDS_BY_COLUMN[p.target].kind == "numeric":
            factor = U.factor(p.target, p.unit)
        out.append({"id": p.id, "target": p.target, "unit": p.unit, "factor": factor,
                    "confidence": p.confidence, "reason": p.reason})
    return out, meta
