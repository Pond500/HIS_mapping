"""The six-step registration form (Env-Occ manual): what counts as missing, and when."""

from app import registration_form as form


def test_every_step_has_an_id_and_a_title():
    ids = [s["id"] for s in form.STEPS]
    assert ids == ["step1", "step2", "step3", "step4", "step5", "step6"]
    assert all(s["title"] for s in form.STEPS)
    assert len(form.TIMELINE) == 6


def test_an_empty_form_is_missing_every_required_field():
    missing = form.missing_everywhere({}, {})
    assert set(missing) == {s["title"] for s in form.STEPS if s["sections"]}
    assert "ชื่อหน่วยบริการ" in missing["ข้อมูลหน่วยบริการ"]


def test_a_filled_text_field_stops_being_missing():
    data = {"step1": {"unit_name": "โรงพยาบาลทดสอบ"}}
    assert "ชื่อหน่วยบริการ" not in form.missing_in_step("step1", data, {})


def test_documents_count_towards_the_minimum():
    key = "doc_risk_checkup"
    assert "1. มีการตรวจสุขภาพตามปัจจัยเสี่ยง" in " ".join(form.missing_in_step("step2", {}, {}))
    docs = {key: [{"sha256": "a", "filename": "a.pdf"}]}
    left = form.missing_in_step("step2", {}, docs)
    assert not any(m.startswith("1.") for m in left)


def test_doctors_need_one_and_nurses_need_two():
    person = {"name": "ก", "documents": {"license": [{"sha256": "x"}], "occ_med": [{"sha256": "y"}]}}
    nurse = {"name": "ข", "documents": {"license": [{"sha256": "x"}], "occ_nurse": [{"sha256": "y"}]}}
    data = {"step3": {"doctors": [person], "nurses": [nurse]}}
    missing = form.missing_in_step("step3", data, {})
    assert any("พยาบาล" in m and "อย่างน้อย 2" in m for m in missing)
    assert not any(m.startswith("แพทย์ (") for m in missing)

    data["step3"]["nurses"] = [nurse, dict(nurse, name="ค")]
    assert form.missing_in_step("step3", data, {}) == []


def test_a_person_without_their_papers_is_reported():
    data = {"step3": {"doctors": [{"name": "หมอ", "documents": {}}], "nurses": []}}
    missing = form.missing_in_step("step3", data, {})
    assert any("แพทย์ คนที่ 1" in m for m in missing)


def test_postal_details_are_only_required_for_post():
    by_hand = {"step6": {"delivery_method": "รับด้วยตนเอง"}}
    assert form.missing_in_step("step6", by_hand, {}) == []

    by_post = {"step6": {"delivery_method": "ทางไปรษณีย์ตอบรับ"}}
    missing = form.missing_in_step("step6", by_post, {})
    assert "ชื่อผู้รับ" in missing and "ที่อยู่ในการจัดส่ง" in missing


def test_summary_step_asks_for_nothing():
    assert form.missing_in_step("step5", {}, {}) == []


def test_status_labels_cover_every_status_the_api_sets():
    assert set(form.STATUS_TH) >= {"draft", "submitted", "changes_requested", "approved", "issued", "cancelled"}
