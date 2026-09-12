"""
config.py
=========
Model per agent. Change models here (or per run with env LLM_MODEL_<AGENT>,
e.g. LLM_MODEL_VERIFIER=google/gemini-3.7-flash) — no code changes needed.

Pin exact model ids: "~...-latest" aliases and previews can change under us
and make evaluation runs incomparable.
"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentConfig:
    model: str
    temperature: float = 0.0
    max_tokens: int = 8000


# Chosen by evaluation/bench_mapper.py on 2026-09-12 (69 dev labels the rules can't resolve):
#   gemini-3.1-flash-lite 69/69, 0 harmful, ~12 s/call, $0.0097 per run
#   deepseek-v4-flash     67/69, 0 harmful (2 safe misses), ~38 s/call, $0.0028 per run
#   qwen3.6-flash         failed schema adherence (disqualified)
# profiler / comment / qc are not benchmarked yet — re-check when those agents exist.
DEFAULTS = {
    "mapper": AgentConfig("google/gemini-3.1-flash-lite"),
    # different vendor from the mapper so their mistakes are less correlated (D11)
    "verifier": AgentConfig("deepseek/deepseek-v4-flash"),
    "profiler": AgentConfig("google/gemini-3.1-flash-lite"),
    "comment": AgentConfig("google/gemini-3.1-flash-lite"),
    "qc": AgentConfig("google/gemini-3.1-flash-lite"),
}


def agent_config(agent: str) -> AgentConfig:
    base = DEFAULTS[agent]
    model = os.environ.get(f"LLM_MODEL_{agent.upper()}", base.model)
    return AgentConfig(model, base.temperature, base.max_tokens)
