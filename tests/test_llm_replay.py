"""LLM_MODE live / fallback / replay without the network (D4)."""

import httpx
import openai
import pytest
from pydantic import BaseModel, ConfigDict

from app.llm import client as C


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: int


class _Msg:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Msg(content)


class _Resp:
    def __init__(self, content):
        self.choices = [_Choice(content)]

    def model_dump(self):
        return {"usage": {"prompt_tokens": 1, "completion_tokens": 1, "cost": 0.0}}


class _FakeClient:
    """Stands in for openai.OpenAI: answers, or fails like a dead network."""
    def __init__(self, answer=None, fail=False):
        outer = self

        class _Completions:
            def create(self, **kw):
                outer.calls += 1
                if fail:
                    raise openai.APITimeoutError(request=httpx.Request("POST", "https://openrouter.ai"))
                return _Resp(answer)

        class _Chat:
            completions = _Completions()

        self.chat, self.calls = _Chat(), 0


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(C, "_client", None)
    return monkeypatch


def _call():
    return C.call_structured("mapper", "sys", "user prompt", Answer)


def test_live_records_and_replay_serves_without_network(env):
    live = _FakeClient(answer='{"value": 7}')
    env.setattr(C, "client", lambda: live)
    env.setenv("LLM_MODE", "live")
    assert _call()[0].value == 7

    dead = _FakeClient(fail=True)
    env.setattr(C, "client", lambda: dead)
    env.setenv("LLM_MODE", "replay")
    parsed, meta = _call()
    assert parsed.value == 7 and meta.replayed and dead.calls == 0   # never touched the network


def test_fallback_uses_recording_when_live_fails(env):
    env.setattr(C, "client", lambda: _FakeClient(answer='{"value": 3}'))
    env.setenv("LLM_MODE", "live")
    _call()
    env.setattr(C, "client", lambda: _FakeClient(fail=True))
    env.setenv("LLM_MODE", "fallback")
    parsed, meta = _call()
    assert parsed.value == 3 and meta.replayed


def test_no_recording_means_llm_error_so_a_human_decides(env):
    env.setattr(C, "client", lambda: _FakeClient(fail=True))
    for mode in ("replay", "fallback"):
        env.setenv("LLM_MODE", mode)
        with pytest.raises(C.LLMError):
            _call()


def test_cache_key_changes_with_the_prompt():
    k1 = C._cache_key("m", "sys", "a", Answer)
    assert k1 == C._cache_key("m", "sys", "a", Answer)
    assert k1 != C._cache_key("m", "sys", "b", Answer) != C._cache_key("m2", "sys", "a", Answer)
