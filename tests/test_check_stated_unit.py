"""flow.check_node: the unit a file writes in its own header decides the factor, not the model."""

from app.graph.flow import check_node


def run(label, unit, prop_unit, factor, values):
    item = {"id": 0, "label": label, "unit": unit, "values": values, "texts": [str(v) for v in values]}
    state = {"items": [item], "proposals": {"0": {"target": "creatinine", "unit": prop_unit, "factor": factor}}}
    return check_node(state)["proposals"]["0"]


def test_model_unit_that_contradicts_the_header_goes_to_a_person():
    # "Creatinine (mg/L)" 6–12 read as mg/dL fits the plausible range 0.1–15, ten times too high
    p = run("Creatinine (mg/L)", None, "mg/dL", 1.0, [6.0, 9.0, 12.0])
    assert p["range_ok"] is False and "mg/L" in p["range_note"], p


def test_model_unit_that_agrees_with_the_header_still_passes():
    p = run("Creatinine (µmol/L)", None, "umol/L", 1 / 88.4, [53.0, 79.6, 106.1])
    assert p["range_ok"] is True, p


def test_unit_column_counts_as_the_files_own_unit():
    p = run("creatinine", "mg/L", "mg/dL", 1.0, [6.0, 9.0])
    assert p["range_ok"] is False, p


def test_thai_unit_is_left_to_the_model():
    p = run("ครีเอตินิน (มก./ดล.)", None, "mg/dL", 1.0, [0.8, 1.1])
    assert p["range_ok"] is True, p
