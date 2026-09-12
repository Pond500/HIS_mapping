"""
bench_mapper.py
===============
Compares LLMs on the Mapper task: every label in the DEV set that the rules
pipeline can't resolve correctly (unknown names, units, traps, noise
columns), with the sample values a real run would see. Dev only — never exam.

    .venv/bin/python -m evaluation.bench_mapper --models deepseek/deepseek-v4-flash google/gemini-3.1-flash-lite

Scoring per label:
  correct        right target (and right unit factor for numeric columns)
  abstain        "__unknown__" or a unit code can't use -> goes to a human (safe)
  wrong_harmful  a wrong template column or wrong unit factor -> would corrupt records if auto-accepted
  wrong_safe     e.g. __extra__ vs __ignore__ confusion
"""

import argparse
import importlib.util
import json
import os
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

from app.agents import mapper as agent
from app.llm.client import LLMError
from app.pipeline import normalize as N
from app.pipeline.extract import observations
from app.pipeline.mapper import TARGET_BP, Mapper, _TemplateName
from app.pipeline.profiler import profile_sheet
from app.pipeline.reader import read_file
from app.template import FIELDS_BY_COLUMN
from testgen.build import ROOT as TESTDATA
from testgen.cases import DEV

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BATCH = 20


def seed_mapper() -> Mapper:
    spec = importlib.util.spec_from_file_location(
        "seed", os.path.join(ROOT, "alembic", "versions", "0002_seed_central_mappings.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    m = Mapper.__new__(Mapper)
    m.hospital = {}
    m.central = {(name, None): _TemplateName(col) for name, col in mod.CENTRAL_MAPPINGS}
    return m


def dataset() -> list[dict]:
    mp = seed_mapper()
    items = {}
    for case in DEV:
        truth = json.load(open(os.path.join(TESTDATA, "dev", case.name, "truth.json"), encoding="utf-8"))
        for up in truth["uploads"]:
            path = os.path.join(TESTDATA, "dev", case.name, up["file"])
            sheets = read_file(open(path, "rb").read(), path.rsplit(".", 1)[1])
            samples = defaultdict(list)
            for sh in sheets:
                sp = profile_sheet(sh, mp.known_labels())
                if sp.layout == "skip":
                    continue
                for o in observations(sh, sp):
                    k = (o.label, o.unit)
                    if o.label and not N.is_na(o.raw) and len(samples[k]) < 6:
                        samples[k].append(N.text(o.raw))
            file_labels = sorted({k[0] for k in samples})
            for (label, unit), ss in samples.items():
                info = up["lab_names"].get(label)
                if info is None:
                    if up["headers"].get(label) != "__ignore__":
                        continue
                    info = {"target": "__ignore__", "factor": 1}
                if info["target"] == TARGET_BP or mp.resolve(label, unit).target == info["target"]:
                    continue
                items.setdefault((label, unit), {
                    "label": label, "unit": unit, "samples": ss, "layout": up["style"]["layout"],
                    "truth": info["target"], "truth_factor": info["factor"], "case": case.name,
                    "file_labels": file_labels})
    return [{"id": i, **it} for i, it in enumerate(items.values())]


def score(item, pred) -> str:
    t, p = item["truth"], pred["target"]
    numeric = p in FIELDS_BY_COLUMN and FIELDS_BY_COLUMN[p].kind == "numeric"
    if p == "__unknown__" or (numeric and pred["factor"] is None):
        return "abstain"
    if p == t:
        if numeric and abs(pred["factor"] - item["truth_factor"]) > 0.01 * abs(item["truth_factor"]):
            return "wrong_harmful"
        return "correct"
    return "wrong_harmful" if p in FIELDS_BY_COLUMN else "wrong_safe"


def run_model(model: str, data: list[dict]) -> dict:
    batches = [data[i:i + BATCH] for i in range(0, len(data), BATCH)]
    preds, cost, tin, tout, lat, failures = {}, 0.0, 0, 0, [], 0

    def one(batch):
        items = [{k: it[k] for k in ("id", "label", "unit", "samples", "layout")} for it in batch]
        labels = sorted({lab for it in batch for lab in it["file_labels"]})[:80]
        return agent.propose(items, labels, model=model)

    with ThreadPoolExecutor(4) as pool:
        for batch, fut in [(b, pool.submit(one, b)) for b in batches]:
            try:
                out, meta = fut.result()
                cost, tin, tout = cost + meta.cost_usd, tin + meta.tokens_in, tout + meta.tokens_out
                lat.append(meta.latency_ms)
                preds.update({o["id"]: o for o in out})
            except LLMError as e:
                failures += 1
                print(f"   batch failed ({model}): {str(e)[:200]}")
                preds.update({it["id"]: {"target": "__unknown__", "factor": None, "confidence": "low",
                                         "unit": None, "reason": "call failed"} for it in batch})
    buckets, high = Counter(), Counter()
    rows = []
    for it in data:
        p = preds[it["id"]]
        s = score(it, p)
        buckets[s] += 1
        if p["confidence"] == "high":
            high[s] += 1
        rows.append({"label": it["label"], "unit": it["unit"], "truth": it["truth"], "pred": p["target"],
                     "pred_unit": p["unit"], "factor": p["factor"], "truth_factor": it["truth_factor"],
                     "confidence": p["confidence"], "score": s, "reason": p["reason"], "case": it["case"]})
    return {"model": model, "n": len(data), "buckets": dict(buckets), "high_conf": dict(high),
            "cost_usd": round(cost, 5), "tokens_in": tin, "tokens_out": tout,
            "avg_latency_ms": int(sum(lat) / len(lat)) if lat else None, "failed_batches": failures, "rows": rows}


def main(models):
    data = dataset()
    print(f"{len(data)} labels the rules can't resolve  —  truth: {dict(Counter(d['truth'] if d['truth'].startswith('__') else 'column' for d in data))}\n")
    results = []
    for model in models:
        t = time.time()
        r = run_model(model, data)
        r["seconds"] = round(time.time() - t, 1)
        results.append(r)
        b, h = r["buckets"], r["high_conf"]
        n = r["n"]
        print(f"{model:40} correct {b.get('correct', 0) / n:6.1%}  harmful {b.get('wrong_harmful', 0):3}  "
              f"abstain {b.get('abstain', 0):3}  safe-wrong {b.get('wrong_safe', 0):3} | "
              f"high-conf: {sum(h.values())} (harmful {h.get('wrong_harmful', 0)}) | "
              f"${r['cost_usd']:.4f}  {r['avg_latency_ms']} ms/call  failed {r['failed_batches']}")
    out = os.path.join(ROOT, "evaluation", "results", f"bench_mapper_{time.strftime('%Y%m%d-%H%M%S')}.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=1)
    print(f"\nsaved {os.path.relpath(out, ROOT)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", required=True)
    main(ap.parse_args().models)
