"""Graph decisions that are pure code (no LLM, no DB): range check and routing."""

from app.graph.flow import MAX_REVISIONS, after_verifier, check_node


def _state(target, factor, values, texts=(), confidence="high"):
    return {"items": [{"id": 0, "label": "x", "unit": None, "values": list(values), "texts": list(texts)}],
            "proposals": {"0": {"target": target, "factor": factor, "unit": None, "confidence": confidence}}}


def test_range_check_passes_when_every_value_fits():
    p = check_node(_state("hb", 0.1, [139, 152, 121]))["proposals"]["0"]
    assert p["range_ok"] is True


def test_range_check_fails_on_one_value_out_of_range():
    # g/L read as g/dL: 139 g/dL is impossible
    p = check_node(_state("hb", 1.0, [13.9, 139]))["proposals"]["0"]
    assert p["range_ok"] is False and "นอกช่วง" in p["range_note"]


def test_range_check_numeric_target_needs_numbers_and_a_usable_unit():
    assert check_node(_state("hb", None, [13.9]))["proposals"]["0"]["range_ok"] is False
    assert check_node(_state("hb", 1.0, []))["proposals"]["0"]["range_ok"] is False


def test_range_check_categorical_values_must_parse():
    ok = check_node(_state("ekg", 1.0, [], texts=["ปกติ", "Abnormal"]))["proposals"]["0"]
    bad = check_node(_state("ekg", 1.0, [], texts=["ปกติ", "ST depression"]))["proposals"]["0"]
    assert ok["range_ok"] is True and bad["range_ok"] is False


def test_unknown_is_never_range_ok():
    assert check_node(_state("__unknown__", None, [1]))["proposals"]["0"]["range_ok"] is False


def test_disagreement_goes_back_to_mapper_once():
    s = {"items": [{"id": 0}], "proposals": {"0": {"target": "hb"}}, "verdicts": {"0": {"agrees": False}},
         "revision": 0}
    assert after_verifier(s) == "mapper"
    assert after_verifier({**s, "revision": MAX_REVISIONS}) == "decide"
    assert after_verifier({**s, "verdicts": {"0": {"agrees": True}}}) == "decide"
