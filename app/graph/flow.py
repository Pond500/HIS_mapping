"""
flow.py
=======
The per-file graph:

  analyze ─(unknown labels?)─> mapper -> range_check -> verifier ─(disagree, once)─> mapper
     │                                                     │
     └──────────────> store <────────── decide <───────────┘
                        │
              (items for a human?) ─> human [interrupt] -> store -> END

- analyze   rules profile + map; collects labels the rules can't resolve (+ samples, values)
- mapper    LLM proposes target + unit per label (app/agents/mapper.py)
- check     code checks the proposal against the plausible range, on ALL values in the file
- verifier  a different LLM checks independently (app/agents/verifier.py)
- decide    auto-accept only on full agreement (AUTO_ACCEPT=on); everything else -> human
- store     rules pipeline with the current mappings (stores what is certain now)
- human     waits for the reviewer (LangGraph interrupt), saves the decisions, re-stores

Graph state holds no names or CIDs — only file id, labels, sample lab values, proposals.
"""

import os
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.agents import mapper as mapper_agent
from app.agents import verifier as verifier_agent
from app.database import SessionLocal
from app.llm.client import LLMError
from app.models import TARGET_EXTRA, TARGET_IGNORE, LabMapping, PendingReview, SourceFile
from app.pipeline import normalize as N
from app.pipeline.extract import observations
from app.pipeline.mapper import IDENTITY_PREFIX, Mapper, norm_label
from app.pipeline.profiler import profile_sheet
from app.pipeline.reader import read_file
from app.pipeline.run import process_file
from app.template import FIELDS_BY_COLUMN

BATCH = 20
MAX_REVISIONS = 1
MAX_VALUES = 300


class FileState(TypedDict, total=False):
    source_file_id: int
    items: list            # [{id, label, unit, samples, layout, values}]
    file_labels: list
    proposals: dict        # "id" -> mapper proposal (+ range_ok)
    verdicts: dict         # "id" -> verifier verdict
    revision: int
    auto: list             # ids auto-accepted
    pending: list          # ids waiting for a human
    human_done: bool
    identity_candidates: list  # headers that may be a missing name/department column: never auto-accepted


def auto_accept_on() -> bool:
    return os.environ.get("AUTO_ACCEPT", "on").lower() in ("on", "1", "true", "yes")


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


def analyze(state: FileState) -> dict:
    with SessionLocal() as db:
        sf = db.get(SourceFile, state["source_file_id"])
        with open(sf.stored_path, "rb") as fh:
            sheets = read_file(fh.read(), os.path.splitext(sf.stored_path)[1])
        mapper = Mapper(db, sf.hospital_id)
    known = mapper.known_labels()
    raws = defaultdict(list)
    layouts = {}
    cands = set()
    for sh in sheets:
        spec = profile_sheet(sh, known, mapper.identity_aliases())
        cands |= {c["header"] for c in spec.candidates}
        if spec.layout == "skip":
            continue
        for o in observations(sh, spec):
            if o.label and not N.is_na(o.raw) and len(raws[(o.label, o.unit)]) < MAX_VALUES:
                raws[(o.label, o.unit)].append(o.raw)
                layouts[(o.label, o.unit)] = spec.layout
    items = []
    for (label, unit), vals in raws.items():
        if mapper.resolve(label, unit).target is not None:
            continue
        numbers = []
        for v in vals:
            try:
                num, inline = N.parse_number(v)
                if num is not None and not inline:
                    numbers.append(num)
            except N.Unparseable:
                pass
        items.append({"id": len(items), "label": label, "unit": unit, "layout": layouts[(label, unit)],
                      "samples": [N.text(v) for v in vals[:6]], "values": numbers,
                      "texts": [N.text(v) for v in vals[:40]]})
    return {"items": items, "file_labels": sorted({k[0] for k in raws})[:120], "proposals": {},
            "verdicts": {}, "revision": 0, "auto": [], "pending": [], "human_done": False,
            "identity_candidates": sorted(cands)}


def _llm_items(items):
    return [{k: it[k] for k in ("id", "label", "unit", "samples", "layout")} for it in items]


def _batched(fn, items):
    batches = [items[i:i + BATCH] for i in range(0, len(items), BATCH)]
    with ThreadPoolExecutor(4) as pool:
        return list(pool.map(fn, batches))


def mapper_node(state: FileState) -> dict:
    proposals, verdicts = dict(state["proposals"]), state["verdicts"]
    revising = bool(verdicts)
    todo = [it for it in state["items"]
            if not revising or not verdicts.get(str(it["id"]), {}).get("agrees")]
    if revising:   # second round: show the reviewer's objection
        todo = [{**it, "reviewer_note": {"target": verdicts.get(str(it["id"]), {}).get("target"),
                                         "unit": verdicts.get(str(it["id"]), {}).get("unit"),
                                         "reason": verdicts.get(str(it["id"]), {}).get("reason")}}
                for it in todo]

    def run(batch):
        with SessionLocal() as db:
            try:
                payload = [{**x, **({"reviewer_note": b["reviewer_note"]} if "reviewer_note" in b else {})}
                           for x, b in zip(_llm_items(batch), batch)]
                out, _ = mapper_agent.propose(payload, state["file_labels"], db=db,
                                              source_file_id=state["source_file_id"])
                db.commit()
                return out
            except LLMError as e:
                db.commit()
                return [{"id": b["id"], "target": "__unknown__", "unit": None, "factor": None,
                         "confidence": "low", "reason": f"เรียก AI ไม่สำเร็จ: {str(e)[:120]}"} for b in batch]

    for out in _batched(run, todo):
        for p in out:
            proposals[str(p["id"])] = p
    return {"proposals": proposals, "revision": state["revision"] + (1 if revising else 0)}


def check_node(state: FileState) -> dict:
    """Code, not LLM: does the proposal fit every value in the file?"""
    proposals = dict(state["proposals"])
    for it in state["items"]:
        p = dict(proposals[str(it["id"])])
        t = p["target"]
        ok, note = True, None
        if t in FIELDS_BY_COLUMN:
            f = FIELDS_BY_COLUMN[t]
            if f.kind == "numeric":
                if p["factor"] is None or not it["values"]:
                    ok, note = False, "ไม่มีค่าตัวเลขหรือหน่วยใช้ไม่ได้"
                else:
                    out = [v for v in it["values"] if not (f.lo <= v * p["factor"] <= f.hi)]
                    if out:
                        ok, note = False, f"{len(out)}/{len(it['values'])} ค่าอยู่นอกช่วง {f.lo}–{f.hi} {f.unit}"
            elif f.kind == "categorical":
                bad = [x for x in it["texts"] if _cat_bad(x)]
                if bad:
                    ok, note = False, f"มีค่าที่อ่านเป็นปกติ/ผิดปกติไม่ได้ เช่น {bad[0]}"
        elif t == "__unknown__":
            ok, note = False, "AI ไม่แน่ใจ"
        p["range_ok"], p["range_note"] = ok, note
        proposals[str(it["id"])] = p
    return {"proposals": proposals}


def _cat_bad(x) -> bool:
    try:
        N.parse_categorical(x)
        return False
    except N.Unparseable:
        return True


def verifier_node(state: FileState) -> dict:
    verdicts = dict(state["verdicts"])
    todo = [it for it in state["items"]
            if state["proposals"][str(it["id"])]["target"] != "__unknown__"
            and not verdicts.get(str(it["id"]), {}).get("agrees")]
    props = {it["id"]: state["proposals"][str(it["id"])] for it in todo}

    def run(batch):
        with SessionLocal() as db:
            try:
                out, _ = verifier_agent.verify(_llm_items(batch), props, state["file_labels"], db=db,
                                               source_file_id=state["source_file_id"])
                db.commit()
                return out
            except LLMError as e:
                db.commit()
                return {b["id"]: {"verdict": "unsure", "target": "__unknown__", "unit": None, "factor": None,
                                  "agrees": False, "reason": f"เรียก AI ไม่สำเร็จ: {str(e)[:120]}"} for b in batch}

    for out in _batched(run, todo):
        for i, v in out.items():
            verdicts[str(i)] = v
    return {"verdicts": verdicts}


def after_verifier(state: FileState) -> str:
    disagree = any(not state["verdicts"].get(str(it["id"]), {}).get("agrees")
                   and state["proposals"][str(it["id"])]["target"] != "__unknown__" for it in state["items"])
    return "mapper" if disagree and state["revision"] < MAX_REVISIONS else "decide"


def decide(state: FileState) -> dict:
    auto, pending = [], []
    with SessionLocal() as db:
        sf = db.get(SourceFile, state["source_file_id"])
        for it in state["items"]:
            p = state["proposals"][str(it["id"])]
            v = state["verdicts"].get(str(it["id"]), {})
            ok = (auto_accept_on() and p["confidence"] == "high" and v.get("agrees") and p.get("range_ok")
                  and p["target"] not in (TARGET_IGNORE, "__unknown__")
                  # a column that may be the missing name/department must be answered by a human
                  and it["label"] not in set(state.get("identity_candidates", [])))
            if ok:
                save_mapping(db, sf.hospital_id, it["label"], it["unit"], p["target"], p["factor"],
                             origin="agent_auto", by="auto: mapper+verifier+range")
                auto.append(it["id"])
            else:
                pending.append(it["id"])
        db.commit()
    return {"auto": auto, "pending": pending}


def store(state: FileState) -> dict:
    with SessionLocal() as db:
        sf = db.get(SourceFile, state["source_file_id"])
        process_file(db, sf, evidence=_evidence(state))
    return {}


def after_store(state: FileState) -> str:
    return "human" if state.get("pending") and not state.get("human_done") else END


def human(state: FileState) -> dict:
    """Pauses the graph until the reviewer answers (resume value = list of decisions)."""
    pending = [it for it in state["items"] if it["id"] in set(state["pending"])]
    decisions = interrupt({"source_file_id": state["source_file_id"],
                           "pending": [{"label": it["label"], "unit": it["unit"],
                                        "proposal": state["proposals"].get(str(it["id"])),
                                        "verification": state["verdicts"].get(str(it["id"]))} for it in pending]})
    apply_decisions(state["source_file_id"], decisions or [], state)
    return {"human_done": True}


# ---------------------------------------------------------------------------
# Decisions & mappings
# ---------------------------------------------------------------------------


def save_mapping(db, hospital_id, label, unit, target, factor, origin, by):
    name = norm_label(label)
    unit_key = unit or None
    m = db.query(LabMapping).filter(LabMapping.hospital_id == hospital_id, LabMapping.source_name == name,
                                    LabMapping.source_unit.is_(None) if unit_key is None
                                    else LabMapping.source_unit == unit_key).one_or_none()
    if m is None:
        m = LabMapping(hospital_id=hospital_id, source_name=name, source_unit=unit_key)
        db.add(m)
    m.target_column, m.unit_factor, m.origin, m.approved_by = target, factor if factor is not None else 1, origin, by
    db.flush()
    return m


IDENTITY_ROLES = ("first_name", "last_name", "full_name", "department_id")


def save_identity(db, hospital_id, header, role, by):
    """Remember that this hospital's column `header` holds `role` (profiler reads it next time)."""
    from app.pipeline.profiler import hkey
    if role not in IDENTITY_ROLES:
        raise ValueError(f"unknown identity role {role}")
    name = hkey(header)
    m = db.query(LabMapping).filter(LabMapping.hospital_id == hospital_id, LabMapping.source_name == name,
                                    LabMapping.source_unit.is_(None)).one_or_none()
    if m is None:
        m = LabMapping(hospital_id=hospital_id, source_name=name, source_unit=None)
        db.add(m)
    m.target_column, m.unit_factor, m.origin, m.approved_by = IDENTITY_PREFIX + role, 1, "human", by
    db.flush()


def apply_decisions(source_file_id: int, decisions: list[dict], state: FileState | None = None):
    """
    decisions: [{"label", "unit", "action", "target"?, "factor"?, "by"?}]
      approve  accept the AI proposal       set      a human's own target (+ factor)
      extra    keep as extra_results        ignore   not a result          skip  leave open
    or, for an "identity" review: {"action": "identity", "role", "header"}
    """
    props = {}
    if state:
        for it in state["items"]:
            props[(it["label"], it["unit"])] = state["proposals"].get(str(it["id"]))
    with SessionLocal() as db:
        sf = db.get(SourceFile, source_file_id)
        for d in decisions:
            if d["action"] == "identity":
                save_identity(db, sf.hospital_id, d["header"], d["role"], d.get("by", "reviewer"))
                for r in db.query(PendingReview).filter(PendingReview.source_file_id == source_file_id,
                                                        PendingReview.kind == "identity",
                                                        PendingReview.status == "open"):
                    if d["role"] in (r.payload.get("missing") or []):
                        r.status, r.decision, r.decided_by = "approved", d, d.get("by", "reviewer")
                continue
            key, action, by = (d["label"], d.get("unit")), d["action"], d.get("by", "reviewer")
            if action == "skip":
                continue
            if action == "approve":
                p = props.get(key) or {}
                target, factor, origin = d.get("target") or p.get("target"), d.get("factor") or p.get("factor"), "agent_approved"
            elif action == "set":
                target, factor, origin = d["target"], d.get("factor", 1.0), "human"
            elif action in ("extra", "ignore"):
                target, factor, origin = TARGET_EXTRA if action == "extra" else TARGET_IGNORE, 1.0, "human"
            else:
                raise ValueError(f"unknown action {action}")
            if not target or target == "__unknown__" or (target in FIELDS_BY_COLUMN and factor is None):
                continue
            save_mapping(db, sf.hospital_id, key[0], key[1], target, factor, origin, by)
            for r in db.query(PendingReview).filter(PendingReview.source_file_id == source_file_id,
                                                    PendingReview.kind == "mapping",
                                                    PendingReview.status == "open"):
                if r.payload.get("label") == key[0] and r.payload.get("unit") == key[1]:
                    r.status, r.decision, r.decided_by = "approved", {**d, "target": target, "factor": factor}, by
        db.commit()


def _evidence(state: FileState) -> dict:
    ev = {}
    for it in state.get("items", []):
        p = state.get("proposals", {}).get(str(it["id"]))
        if p is None:
            continue
        v = state.get("verdicts", {}).get(str(it["id"]))
        ev[(it["label"], it["unit"])] = {"proposal": {k: p.get(k) for k in ("target", "unit", "factor", "confidence",
                                                                            "reason", "range_ok", "range_note")},
                                         "verification": v and {k: v.get(k) for k in ("verdict", "target", "unit",
                                                                                      "agrees", "reason")}}
    return ev


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------


def build(checkpointer=None):
    g = StateGraph(FileState)
    g.add_node("analyze", analyze)
    g.add_node("mapper", mapper_node)
    g.add_node("check", check_node)
    g.add_node("verifier", verifier_node)
    g.add_node("decide", decide)
    g.add_node("store", store)
    g.add_node("human", human)
    g.add_edge(START, "analyze")
    g.add_conditional_edges("analyze", lambda s: "mapper" if s["items"] else "store", ["mapper", "store"])
    g.add_edge("mapper", "check")
    g.add_edge("check", "verifier")
    g.add_conditional_edges("verifier", after_verifier, ["mapper", "decide"])
    g.add_edge("decide", "store")
    g.add_conditional_edges("store", after_store, ["human", END])
    g.add_edge("human", "store")
    return g.compile(checkpointer=checkpointer)
