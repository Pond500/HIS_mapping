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

from app.agents import comments as comment_agent
from app.agents import mapper as mapper_agent
from app.agents import verifier as verifier_agent
from app.graph import progress
from app.database import SessionLocal
from app.llm.client import LLMError
from app.models import (
    TARGET_EXTRA, TARGET_EXTRA_COL_PREFIX, TARGET_IGNORE, CommentLabel, LabMapping, PendingReview,
    SourceFile,
)
from app.pipeline import normalize as N
from app.pipeline.extract import observations
from app.pipeline.mapper import DEPT_PREFIX, IDENTITY_PREFIX, Mapper, norm_label
from app.pipeline.profiler import file_title_date, profile_sheet
from app.pipeline.reader import read_file
from app.pipeline.run import company_id_of, process_file
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
    comments_done: bool
    comment_props: dict        # "column|text_norm" -> {"proposal", "check"} for findings left to a human


def auto_accept_on() -> bool:
    return os.environ.get("AUTO_ACCEPT", "on").lower() in ("on", "1", "true", "yes")


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


def analyze(state: FileState) -> dict:
    fid = state["source_file_id"]
    progress.step(fid, "read")
    with SessionLocal() as db:
        sf = db.get(SourceFile, fid)
        with open(sf.stored_path, "rb") as fh:
            sheets = read_file(fh.read(), os.path.splitext(sf.stored_path)[1])
        mapper = Mapper(db, sf.hospital_id, company_id_of(db, sf))
    progress.note(fid, "read", f"{len(sheets)} ชีต")
    progress.step(fid, "match")
    known = mapper.known_labels()
    raws = defaultdict(list)
    layouts = {}
    cands = set()
    fdate = file_title_date(sheets)
    for sh in sheets:
        spec = profile_sheet(sh, known, mapper.identity_aliases(), fdate)
        cands |= {c["header"] for c in spec.candidates}
        if spec.layout == "skip":
            continue
        for o in observations(sh, spec):
            if o.label and not N.is_na(o.raw) and len(raws[(o.label, o.unit)]) < MAX_VALUES:
                raws[(o.label, o.unit)].append(o.raw)
                layouts[(o.label, o.unit)] = spec.layout
    items, known_n = [], 0
    for (label, unit), vals in raws.items():
        res = mapper.resolve(label, unit)
        known_n += res.target is not None
        if res.target is not None or res.company_column_conflict:
            # a company-column unit conflict is already a fully-formed question (see
            # extract.py) — asking the AI to guess a mapping for it would be noise
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
    progress.note(fid, "match", f"รู้จักแล้ว {known_n} จาก {len(raws)} ชื่อผลตรวจ"
                                + (f" · ส่งให้ AI {len(items)} ชื่อ" if items else " · ไม่ต้องใช้ AI"))
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
    progress.step(state["source_file_id"], "ai_propose",
                  f"แก้ไขอีกรอบ {len(todo)} ชื่อตามที่ AI ตัวที่สองแย้ง" if revising else f"{len(todo)} ชื่อ")
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
    progress.step(state["source_file_id"], "ai_verify",
                  (f"ตรวจซ้ำ {len(todo)} ชื่อ" if state["revision"] else f"{len(todo)} ชื่อ") if todo
                  else "AI ตัวแรกไม่ได้เสนอคำตอบ จึงไม่มีอะไรให้ตรวจ")

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
        # in a company's file an extra is a named company column (CONTEXT.md), and only
        # a person names it; the model's bare "__extra__" would be the old nameless row
        no_auto = {TARGET_IGNORE, "__unknown__"} | ({TARGET_EXTRA} if company_id_of(db, sf) else set())
        for it in state["items"]:
            p = state["proposals"][str(it["id"])]
            v = state["verdicts"].get(str(it["id"]), {})
            ok = (auto_accept_on() and p["confidence"] == "high" and v.get("agrees") and p.get("range_ok")
                  and p["target"] not in no_auto
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
    progress.step(state["source_file_id"], "store")
    with SessionLocal() as db:
        sf = db.get(SourceFile, state["source_file_id"])
        process_file(db, sf, evidence=_evidence(state), comment_evidence=_comment_evidence(state))
    return {}


def _open_comment_reviews(file_id: int) -> list:
    with SessionLocal() as db:
        return db.query(PendingReview).filter(PendingReview.source_file_id == file_id,
                                              PendingReview.kind == "comment",
                                              PendingReview.status == "open").all()


def after_store(state: FileState) -> str:
    if not state.get("comments_done") and _open_comment_reviews(state["source_file_id"]):
        return "comments"
    return "human" if state.get("pending") and not state.get("human_done") else END


def comments_node(state: FileState) -> dict:
    """
    Findings with no 1/2 column: two classifiers from different vendors, blind to each other.
    Same value + both high confidence (+ AUTO_ACCEPT) -> learned CommentLabel; else a human decides.
    Only the finding text goes to the LLMs.
    """
    distinct = {}
    for r in _open_comment_reviews(state["source_file_id"]):
        key = (r.payload["column"], N.norm_comment(r.payload.get("text", "")))
        distinct.setdefault(key, r.payload.get("text", ""))
    items = [{"id": i, "column": k[0], "text": text} for i, (k, text) in enumerate(distinct.items())]
    keys = list(distinct)
    progress.step(state["source_file_id"], "comments", f"{len(items)} ข้อความ")

    def run(agent):
        def one(batch):
            with SessionLocal() as db:
                try:
                    out, _ = comment_agent.classify(batch, agent=agent, db=db, source_file_id=state["source_file_id"])
                except LLMError as e:
                    out = {b["id"]: {"value": None, "confidence": "low", "reason": f"เรียก AI ไม่สำเร็จ: {str(e)[:100]}"}
                           for b in batch}
                db.commit()
                return out
        merged = {}
        for out in _batched(one, items):
            merged.update(out)
        return merged

    with ThreadPoolExecutor(2) as pool:
        first, second = pool.map(run, ["comment", "comment_check"])
    props = {}
    with SessionLocal() as db:
        for it, key in zip(items, keys):
            a, b = first[it["id"]], second[it["id"]]
            agree = a["value"] is not None and a["value"] == b["value"]
            if auto_accept_on() and agree and a["confidence"] == b["confidence"] == "high":
                save_comment_label(db, key[0], it["text"], a["value"], "agent_auto", "auto: comment+comment_check")
            else:
                props[f"{key[0]}|{key[1]}"] = {"proposal": a, "check": b, "agree": agree}
        db.commit()
    return {"comments_done": True, "comment_props": props}


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


def resolve_company_column(db, company_id: int, label: str, unit: str | None, d: dict, by: str):
    """The company-column half of an "extra" decision (CONTEXT.md "คอลัมน์ของบริษัท").
    Picking an existing one (`column_id`) always wins; naming a new one reuses an
    exact name match for this company rather than creating a near-duplicate, and
    refuses only when that match's kind disagrees (a genuine mistake to surface, not
    silently paper over). Either way, THIS file's (label, unit) is remembered as an
    alias for the column, so a differently-spelled label still resolves next time —
    company-scoped, like the column itself, never written to lab_mappings."""
    from app.models import CompanyColumnAlias, CompanyExtraColumn
    if d.get("column_id"):
        col = db.get(CompanyExtraColumn, d["column_id"])
        if col is None or col.company_id != company_id:
            raise ValueError("ไม่พบคอลัมน์ของบริษัทนี้")
    else:
        name = (d.get("column_name") or "").strip()
        kind = d.get("column_kind")
        if not name or kind not in ("numeric", "text"):
            raise ValueError("ต้องระบุชื่อคอลัมน์และชนิดข้อมูล (ตัวเลข/ข้อความ) หรือเลือกคอลัมน์ที่มีอยู่แล้ว")
        col = (db.query(CompanyExtraColumn)
              .filter(CompanyExtraColumn.company_id == company_id, CompanyExtraColumn.name == name)
              .one_or_none())
        if col:
            if col.kind != kind:
                raise ValueError(f"บริษัทนี้มีคอลัมน์ชื่อ “{name}” อยู่แล้วเป็นชนิด {col.kind} "
                                 f"— เลือกคอลัมน์เดิมจากรายการแทนการตั้งชื่อใหม่")
        else:
            col = CompanyExtraColumn(company_id=company_id, name=name, kind=kind,
                                     unit=d.get("column_unit") if kind == "numeric" else None, created_by=by)
            db.add(col)
            db.flush()

    alias_name, alias_unit = norm_label(label), (unit or None)
    alias = (db.query(CompanyColumnAlias)
            .filter(CompanyColumnAlias.company_id == company_id, CompanyColumnAlias.source_name == alias_name,
                    CompanyColumnAlias.source_unit.is_(None) if alias_unit is None
                    else CompanyColumnAlias.source_unit == alias_unit).one_or_none())
    if alias is None:
        db.add(CompanyColumnAlias(company_id=company_id, source_name=alias_name, source_unit=alias_unit,
                                  column_id=col.id))
    else:
        alias.column_id = col.id
    db.flush()
    return col


IDENTITY_ROLES = ("first_name", "last_name", "full_name", "department_id", "visit_date")


def save_department(db, hospital_id, name, code, by):
    """D18: remember this hospital's department name -> code."""
    from app.pipeline.normalize import looks_like_code
    if not looks_like_code(code):
        raise ValueError(f"not a department code: {code}")
    key = norm_label(name)
    m = db.query(LabMapping).filter(LabMapping.hospital_id == hospital_id, LabMapping.source_name == key,
                                    LabMapping.source_unit.is_(None)).one_or_none()
    if m is None:
        m = LabMapping(hospital_id=hospital_id, source_name=key, source_unit=None)
        db.add(m)
    m.target_column, m.unit_factor, m.origin, m.approved_by = DEPT_PREFIX + code.strip(), 1, "human", by
    db.flush()


def save_comment_label(db, column, text, value, origin, by):
    if value not in (1, 2):
        raise ValueError("comment value must be 1 or 2")
    key = N.norm_comment(text)
    m = db.query(CommentLabel).filter(CommentLabel.column == column, CommentLabel.text_norm == key).one_or_none()
    if m is None:
        m = CommentLabel(column=column, text_norm=key)
        db.add(m)
    m.value, m.origin, m.approved_by = value, origin, by
    db.flush()


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
            if d["action"] == "department":
                save_department(db, sf.hospital_id, d["name"], d["code"], d.get("by", "reviewer"))
                for r in db.query(PendingReview).filter(PendingReview.source_file_id == source_file_id,
                                                        PendingReview.kind == "department",
                                                        PendingReview.status == "open"):
                    if r.payload.get("name") == d["name"]:
                        r.status, r.decision, r.decided_by = "approved", d, d.get("by", "reviewer")
                continue
            if d["action"] == "comment":
                save_comment_label(db, d["column"], d["text"], int(d["value"]), "human", d.get("by", "reviewer"))
                key = (d["column"], N.norm_comment(d["text"]))
                for r in db.query(PendingReview).filter(PendingReview.source_file_id == source_file_id,
                                                        PendingReview.kind == "comment",
                                                        PendingReview.status == "open"):
                    if (r.payload.get("column"), N.norm_comment(r.payload.get("text", ""))) == key:
                        r.status, r.decision, r.decided_by = "approved", d, d.get("by", "reviewer")
                continue
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
            elif action == "ignore":
                target, factor, origin = TARGET_IGNORE, 1.0, "human"
            elif action == "extra":
                # named company column, not the old anonymous extra_results row
                # (CONTEXT.md "คอลัมน์ของบริษัท") — remembered per company, not per
                # hospital, so it is never written to lab_mappings at all
                company_id = company_id_of(db, sf)
                if company_id is None:
                    raise ValueError("ไฟล์นี้ยังไม่ผูกกับสถานประกอบการ จึงยังตั้งคอลัมน์ของบริษัทไม่ได้")
                col = resolve_company_column(db, company_id, key[0], key[1], d, by)
                for r in db.query(PendingReview).filter(PendingReview.source_file_id == source_file_id,
                                                        PendingReview.kind == "mapping",
                                                        PendingReview.status == "open"):
                    if r.payload.get("label") == key[0] and r.payload.get("unit") == key[1]:
                        r.status, r.decision, r.decided_by = ("approved",
                            {**d, "target": f"{TARGET_EXTRA_COL_PREFIX}{col.id}"}, by)
                continue
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


def _comment_evidence(state: FileState) -> dict:
    out = {}
    for k, v in (state.get("comment_props") or {}).items():
        column, text_norm = k.split("|", 1)
        out[(column, text_norm)] = v
    return out


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
    g.add_node("comments", comments_node)
    g.add_edge(START, "analyze")
    g.add_conditional_edges("analyze", lambda s: "mapper" if s["items"] else "store", ["mapper", "store"])
    g.add_edge("mapper", "check")
    g.add_edge("check", "verifier")
    g.add_conditional_edges("verifier", after_verifier, ["mapper", "decide"])
    g.add_edge("decide", "store")
    g.add_conditional_edges("store", after_store, ["comments", "human", END])
    g.add_edge("comments", "store")
    g.add_edge("human", "store")
    return g.compile(checkpointer=checkpointer)
