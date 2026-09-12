"""LLM client helpers that don't need the network."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.agents.mapper import MapResult
from app.llm.client import _extract_json, _strict_schema


class Inner(BaseModel):
    model_config = ConfigDict(extra="forbid")
    a: int
    b: str | None


class Outer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[Inner]
    kind: Literal["x", "y"]


def _objects(node):
    if isinstance(node, dict):
        if node.get("type") == "object" and "properties" in node:
            yield node
        for v in node.values():
            yield from _objects(v)
    elif isinstance(node, list):
        for v in node:
            yield from _objects(v)


def test_strict_schema_every_object_closed_and_fully_required():
    for model in (Outer, MapResult):
        for obj in _objects(_strict_schema(model)):
            assert obj["additionalProperties"] is False
            assert set(obj["required"]) == set(obj["properties"])


def test_extract_json_handles_code_fences():
    assert _extract_json('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert _extract_json('  {"a": 1} ') == '{"a": 1}'
