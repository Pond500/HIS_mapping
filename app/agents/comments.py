"""
comments.py (agent)
===================
Classifies free-text findings (X-ray / EKG / hearing / vision) as normal (1) or
abnormal (2) when a file has no 1/2 column. Only the finding text is sent — no
names, no CIDs.

Two independent opinions from different vendors ("comment" and "comment_check"
agents, app/llm/config.py). Code decides agreement; disagreement or low
confidence goes to a human (docs/requirements.md D11, D17).
"""

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.llm.client import CallMeta, call_structured

COLUMN_MEANING = {
    "chest_xray": "Chest X-ray. 1 = normal. 2 = any abnormal finding (opacity, nodule, fibrosis, scar, "
                  "pleural thickening, cardiomegaly, ...).",
    "ekg": "Electrocardiogram. 1 = normal / normal sinus rhythm / within normal limits. 2 = any "
           "arrhythmia, block, hypertrophy, ischemic change, tachy/bradycardia needing follow-up.",
    "hearing_ability": "Audiometry. 1 = normal hearing both ears. 2 = any hearing loss (noise-induced, "
                       "sensorineural, conductive, one or both ears).",
    "far_vision_test": "Far vision for work. 1 = normal / suitable. 2 = impaired or needs correction "
                       "(myopia, reduced visual acuity, glasses needed).",
}


class CommentItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int
    verdict: Literal["normal", "abnormal", "unsure"]
    confidence: Literal["high", "medium", "low"]
    reason: str       # one short sentence in Thai


class CommentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[CommentItem]


SYSTEM = f"""You classify findings from Thai occupational health checkups. Each item is the free-text
finding for one exam; decide whether the overall result is normal or abnormal.

Meaning per exam:
{chr(10).join(f"- {c}: {m}" for c, m in COLUMN_MEANING.items())}

Rules:
- Text may be Thai or English, abbreviated.
- "abnormal" whenever the text reports a finding that is not normal, even if mild.
- "unsure" if the text is ambiguous, incomplete, or not a finding — a human will decide.
- "confidence": high only if a physician would certainly agree.
- "reason": one short sentence in Thai. Answer every id exactly once."""

VALUE = {"normal": 1, "abnormal": 2}


def classify(items: list[dict], *, agent: str = "comment", model: str | None = None, db=None,
             source_file_id=None) -> tuple[dict, CallMeta]:
    """items: [{"id", "column", "text"}] -> {id: {"value": 1|2|None, "confidence", "reason"}}"""
    res, meta = call_structured(agent, SYSTEM, "Classify these findings:\n" + json.dumps(items, ensure_ascii=False),
                                CommentResult, model=model, db=db, source_file_id=source_file_id,
                                log_input={"items": items})
    got = {x.id: x for x in res.items}
    out = {}
    for it in items:
        x = got.get(it["id"])
        out[it["id"]] = ({"value": VALUE.get(x.verdict), "confidence": x.confidence, "reason": x.reason} if x else
                         {"value": None, "confidence": "low", "reason": "ไม่ได้ตอบรายการนี้"})
    return out, meta
