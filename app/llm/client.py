"""
client.py
=========
One way to call an LLM: call_structured(). The answer must validate against
a pydantic schema; invalid answers are retried with the validation error,
and still-invalid ones raise LLMError (the caller then flags for a human).

Every call is logged to agent_decisions (input without PII, output, tokens,
cost, latency) when a DB session is given.

Replay (D4, for a live demo): every successful answer is recorded in
storage/llm_cache/<sha256 of model+prompt+schema>.json (labels and sample lab
values only — no names or CIDs). LLM_MODE:
  live      (default) call the model; record the answer
  fallback  call the model; if it fails or is slower than LLM_TIMEOUT_S, use the recorded answer
  replay    never call the network; recorded answers only
No recorded answer -> LLMError -> the item goes to a human, as for any failed call.
"""

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass

import openai
from dotenv import dotenv_values, load_dotenv
from pydantic import BaseModel, ValidationError

from app.llm.config import agent_config

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(ROOT, ".env"))

_client = None


class LLMError(RuntimeError):
    pass


@dataclass
class CallMeta:
    agent: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    attempts: int = 0
    error: str | None = None
    replayed: bool = False


def _api_key() -> str | None:
    """The project's .env wins over the shell: a stale OPENROUTER_API_KEY exported in a
    shell profile must not silently replace the key configured for this project.
    (Only this key — load_dotenv() elsewhere keeps its no-override behaviour.)"""
    return dotenv_values(os.path.join(ROOT, ".env")).get("OPENROUTER_API_KEY") or os.environ.get("OPENROUTER_API_KEY")


def client() -> openai.OpenAI:
    global _client
    if _client is None:
        key = _api_key()
        if not key:
            raise LLMError("OPENROUTER_API_KEY is not set (.env)")
        _client = openai.OpenAI(api_key=key, base_url=os.environ.get("OPENROUTER_BASE_URL",
                                                                     "https://openrouter.ai/api/v1"),
                                timeout=float(os.environ.get("LLM_TIMEOUT_S", "120")),
                                max_retries=0 if _mode() == "fallback" else 2)
    return _client


def _mode() -> str:
    return os.environ.get("LLM_MODE", "live").lower()


def _cache_dir() -> str:
    return os.environ.get("LLM_CACHE_DIR", os.path.join(ROOT, "storage", "llm_cache"))


def _cache_key(model: str, system: str, user: str, schema: type[BaseModel]) -> str:
    blob = json.dumps({"model": model, "system": system, "user": user, "schema": _strict_schema(schema)},
                      sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()


def _cache_read(key: str) -> str | None:
    path = os.path.join(_cache_dir(), f"{key}.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)["text"]


def _cache_write(key: str, text: str, model: str):
    os.makedirs(_cache_dir(), exist_ok=True)
    tmp = os.path.join(_cache_dir(), f"{key}.json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"model": model, "text": text}, fh, ensure_ascii=False)
    os.replace(tmp, os.path.join(_cache_dir(), f"{key}.json"))


def _strict_schema(model: type[BaseModel]) -> dict:
    """JSON schema in the strict form structured-output providers expect."""
    schema = model.model_json_schema()

    def fix(node):
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"])
            for v in node.values():
                fix(v)
        elif isinstance(node, list):
            for v in node:
                fix(v)
    fix(schema)
    return schema


def _extract_json(text: str) -> str:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    return m.group(1).strip() if m else text


def call_structured(agent: str, system: str, user: str, schema: type[BaseModel], *,
                    db=None, source_file_id: int | None = None, log_input: dict | None = None,
                    model: str | None = None, max_retries: int = 2):
    """Returns (parsed schema instance, CallMeta). Raises LLMError after retries."""
    cfg = agent_config(agent)
    model = model or cfg.model
    meta = CallMeta(agent, model)
    key = _cache_key(model, system, user, schema)
    if _mode() == "replay":
        return _from_cache(key, schema, meta, db, source_file_id, log_input, reason="replay mode")
    # some providers reject json_schema requests unless the prompt itself mentions JSON
    messages = [{"role": "system", "content": system + "\n\nRespond with a single JSON object matching the schema."},
                {"role": "user", "content": user}]
    provider = {"require_parameters": True}
    if os.environ.get("OPENROUTER_DATA_COLLECTION", "deny") == "deny":
        provider["data_collection"] = "deny"
    t0 = time.time()
    last_err, text = None, ""
    for attempt in range(max_retries + 1):
        meta.attempts = attempt + 1
        try:
            resp = client().chat.completions.create(
                model=model, messages=messages, temperature=cfg.temperature, max_tokens=cfg.max_tokens,
                response_format={"type": "json_schema", "json_schema": {
                    "name": schema.__name__, "strict": True, "schema": _strict_schema(schema)}},
                extra_body={"provider": provider, "usage": {"include": True}},
            )
        except openai.APIError as e:
            last_err = f"{type(e).__name__}: {e}"
            if _mode() == "fallback":
                break   # network/provider trouble during a demo: use the recording now, don't wait out retries
            continue
        usage = (resp.model_dump().get("usage") or {})
        meta.tokens_in += usage.get("prompt_tokens") or 0
        meta.tokens_out += usage.get("completion_tokens") or 0
        meta.cost_usd += float(usage.get("cost") or 0)
        text = (resp.choices[0].message.content or "") if resp.choices else ""
        try:
            parsed = schema.model_validate_json(_extract_json(text))
            meta.latency_ms = int((time.time() - t0) * 1000)
            _cache_write(key, _extract_json(text), model)
            _log(db, source_file_id, meta, log_input, parsed.model_dump(), None)
            return parsed, meta
        except (ValidationError, json.JSONDecodeError, ValueError) as e:
            last_err = f"invalid answer: {str(e)[:500]}"
            messages += [{"role": "assistant", "content": text[:4000]},
                         {"role": "user", "content": f"คำตอบไม่ตรง schema: {str(e)[:800]}\n"
                                                     "ตอบใหม่เป็น JSON ตาม schema เท่านั้น"}]
    meta.latency_ms = int((time.time() - t0) * 1000)
    if _mode() == "fallback":
        return _from_cache(key, schema, meta, db, source_file_id, log_input, reason=f"live call failed: {last_err}")
    meta.error = last_err
    _log(db, source_file_id, meta, log_input, None, last_err)
    raise LLMError(f"{agent} ({model}) failed after {meta.attempts} attempts: {last_err}")


def _from_cache(key, schema, meta: CallMeta, db, source_file_id, log_input, reason: str):
    text = _cache_read(key)
    if text is None:
        meta.error = f"{reason}; no recorded answer"
        _log(db, source_file_id, meta, log_input, None, meta.error)
        raise LLMError(f"{meta.agent} ({meta.model}): {meta.error}")
    parsed = schema.model_validate_json(text)
    meta.replayed = True
    _log(db, source_file_id, meta, log_input, parsed.model_dump(), None)
    return parsed, meta


def _log(db, source_file_id, meta: CallMeta, log_input, output, error):
    if db is None:
        return
    from app.models import AgentDecision
    db.add(AgentDecision(source_file_id=source_file_id, agent=meta.agent,
                         model=meta.model + (" (replay)" if meta.replayed else ""),
                         input=log_input or {}, output=output, tokens_in=meta.tokens_in,
                         tokens_out=meta.tokens_out, cost_usd=meta.cost_usd, latency_ms=meta.latency_ms,
                         error=error))
    db.flush()
