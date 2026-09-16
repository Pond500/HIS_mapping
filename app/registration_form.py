"""
registration_form.py
====================
The six steps of ขึ้นทะเบียนหน่วยบริการ (Env-Occ manual, pages 6–12), in one place so the
API and the web page never disagree about field names.

Field kinds the page knows how to draw:
    text · textarea · cid · date · number · email · select · radio · docs · people

`docs` fields hold uploaded PDFs; `min` is how many the manual demands.
`people` fields repeat a small form (a doctor, a nurse) and each person carries their own
documents. Everything the manual marks with * is `required`.
"""

STEPS = [
    {
        "id": "step1",
        "title": "ข้อมูลหน่วยบริการ",
        "sections": [
            {
                "title": "ผู้มาขอขึ้นทะเบียน",
                "fields": [
                    {"key": "applicant_kind", "label": "ผู้ขอขึ้นทะเบียน", "kind": "select", "required": True,
                     "options": ["เจ้าของหน่วยบริการ", "ผู้ได้รับมอบอำนาจแทน"],
                     "help": "ถ้าเป็นผู้ได้รับมอบอำนาจแทน ต้องแนบเอกสารมอบอำนาจในหัวข้อเอกสารเพิ่มเติม"},
                    {"key": "applicant_title", "label": "คำนำหน้าชื่อ", "kind": "select", "required": True,
                     "options": ["นาย", "นาง", "นางสาว", "นายแพทย์", "แพทย์หญิง"]},
                    {"key": "applicant_name", "label": "ชื่อ", "kind": "text", "required": True},
                    {"key": "applicant_surname", "label": "นามสกุล", "kind": "text", "required": True},
                    {"key": "applicant_cid", "label": "เลขบัตรประชาชน", "kind": "cid", "required": True},
                    {"key": "applicant_nationality", "label": "สัญชาติ", "kind": "text", "required": True,
                     "default": "ไทย"},
                    {"key": "applicant_birthdate", "label": "วันเกิด", "kind": "date", "required": True},
                ],
            },
            {
                "title": "ข้อมูลของหน่วยบริการสุขภาพ",
                "fields": [
                    {"key": "unit_name", "label": "ชื่อหน่วยบริการ", "kind": "text", "required": True},
                    {"key": "unit_code", "label": "รหัสหน่วยบริการ", "kind": "text", "required": True},
                    {"key": "beds", "label": "จำนวนเตียง", "kind": "number", "required": True},
                    {"key": "phone", "label": "โทรศัพท์", "kind": "text", "required": True},
                    {"key": "phone_ext", "label": "ต่อ", "kind": "text"},
                    {"key": "email", "label": "อีเมล", "kind": "email", "required": True},
                    {"key": "address", "label": "ที่อยู่", "kind": "text", "required": True,
                     "help": "เลขที่ หมู่ ซอย ถนน"},
                    {"key": "province", "label": "จังหวัด", "kind": "text", "required": True},
                    {"key": "district", "label": "เขต / อำเภอ", "kind": "text", "required": True},
                    {"key": "postcode", "label": "รหัสไปรษณีย์", "kind": "text", "required": True},
                    {"key": "risk_note", "label": "ระบุความเสี่ยงด้านอาชีวอนามัยหรือสิ่งแวดล้อมในพื้นที่ของท่าน",
                     "kind": "textarea"},
                ],
            },
            {
                "title": "ประเภทของหน่วยบริการ",
                "fields": [
                    {"key": "unit_type", "label": "หน่วยงาน", "kind": "select", "required": True, "options": [
                        "หน่วยบริการปฐมภูมิ",
                        "หน่วยบริการภาครัฐ",
                        "หน่วยบริการภาครัฐ (เคลื่อนที่)",
                        "หน่วยบริการภาคเอกชน สภากาชาดไทย หรือบริการการประกอบโรคศิลปะ องค์กรที่ให้บริการอื่น ๆ ของกรม",
                        "หน่วยบริการภาคเอกชน สภากาชาดไทย หรือบริการการประกอบโรคศิลปะ องค์กรที่ให้บริการอื่น ๆ ของกรม (เคลื่อนที่)",
                        "สถานที่ประกอบกิจการ (ลูกจ้าง <1000 คน)",
                        "สถานที่ประกอบกิจการ (ลูกจ้าง ≥1000 คน)",
                    ]},
                    {"key": "registration_scope", "label": "ความประสงค์ขึ้นทะเบียนเป็นหน่วยบริการ", "kind": "select",
                     "required": True,
                     "options": ["อาชีวเวชกรรม", "เวชกรรมสิ่งแวดล้อม", "อาชีวเวชกรรมและเวชกรรมสิ่งแวดล้อม"]},
                    {"key": "employees", "label": "ประเภทและจำนวนลูกจ้าง", "kind": "text", "required": True},
                ],
            },
            {
                "title": "เอกสารประกอบ",
                "fields": [
                    {"key": "doc_standard", "label": "แบบประเมินมาตรฐานเบื้องต้นของหน่วยบริการ",
                     "kind": "docs", "required": True, "min": 1},
                    {"key": "doc_extra", "label": "เอกสารเพิ่มเติม", "kind": "docs", "required": True, "min": 1,
                     "help": "ใบอนุญาตให้ประกอบกิจการสถานพยาบาล · ใบอนุญาตดำเนินการสถานพยาบาล · หนังสือจัดตั้งองค์กร · "
                             "กฎหมายจัดตั้งองค์กร · หนังสือรับรองนิติบุคคล · หนังสือมอบอำนาจ (เลือกอย่างน้อย 1 รายการ)"},
                ],
            },
        ],
    },
    {
        "id": "step2",
        "title": "การให้บริการตรวจสุขภาพ และการเก็บสิ่งส่งตรวจทางชีวภาพ",
        "sections": [
            {
                "title": "หลักฐานการให้บริการ",
                "fields": [
                    {"key": "doc_risk_checkup", "label": "1. มีการตรวจสุขภาพตามปัจจัยเสี่ยง",
                     "kind": "docs", "required": True, "min": 1,
                     "help": "แนวปฏิบัติการบ่งชี้และประเมินความเสี่ยงต่อสุขภาพ และแบบรายการตรวจสุขภาพตามปัจจัยเสี่ยง"},
                    {"key": "doc_pre_employment", "label": "2. การตรวจสุขภาพให้เหมาะสมก่อนเข้าทำงาน",
                     "kind": "docs", "required": True, "min": 1},
                    {"key": "doc_return_to_work", "label": "3. มีการตรวจสุขภาพก่อนกลับเข้าทำงานภายหลังการเจ็บป่วย",
                     "kind": "docs", "required": True, "min": 1},
                    {"key": "doc_lab_quality", "label": "4. มีการควบคุมคุณภาพก่อนการวิเคราะห์ตัวอย่างทางห้องปฏิบัติการ",
                     "kind": "docs", "required": True, "min": 1},
                    {"key": "doc_lab_standard", "label": "5. มีการส่งตัวอย่างไปทำการวิเคราะห์ยังห้องปฏิบัติการที่ได้รับการรับรองมาตรฐาน",
                     "kind": "docs", "required": True, "min": 1,
                     "help": "ISO 15189 หรือมาตรฐานงานเทคนิคการแพทย์ หรือมาตรฐานอื่นที่ไม่ต่ำกว่า (เลือกอย่างน้อย 1 รายการ)"},
                ],
            },
        ],
    },
    {
        "id": "step3",
        "title": "บุคลากร",
        "sections": [
            {
                "title": "ข้อมูลแพทย์ (อย่างน้อย 1 คน)",
                "fields": [
                    {"key": "doctors", "label": "แพทย์", "kind": "people", "required": True, "min": 1,
                     "person_docs": [
                         {"key": "license", "label": "สำเนาใบอนุญาตประกอบวิชาชีพเวชกรรม", "min": 1,
                          "help": "ออกภายใน 90 วัน"},
                         {"key": "occ_med", "label": "ใบวุฒิบัตร/หนังสืออนุมัติด้านอาชีวเวชศาสตร์ หรือเทียบเท่า", "min": 1},
                     ]},
                ],
            },
            {
                "title": "ข้อมูลพยาบาล (อย่างน้อย 2 คน)",
                "fields": [
                    {"key": "nurses", "label": "พยาบาล", "kind": "people", "required": True, "min": 2,
                     "person_docs": [
                         {"key": "license", "label": "สำเนาใบอนุญาตประกอบวิชาชีพการพยาบาลและการผดุงครรภ์", "min": 1,
                          "help": "ออกภายใน 90 วัน"},
                         {"key": "occ_nurse", "label": "ใบวุฒิบัตร/ประกาศนียบัตรการอบรมด้านอาชีวอนามัย", "min": 1},
                     ]},
                ],
            },
            {
                "title": "ข้อมูลบุคลากรสนับสนุน (ไม่บังคับ)",
                "fields": [
                    {"key": "support_staff", "label": "บุคลากรสนับสนุน", "kind": "people",
                     "person_docs": [{"key": "evidence", "label": "เอกสารประกอบ", "min": 0}]},
                ],
            },
        ],
    },
    {
        "id": "step4",
        "title": "เครื่องมือ",
        "sections": [
            {
                "title": "เครื่องตรวจสมรรถภาพการได้ยิน",
                "fields": [
                    {"key": "doc_audio_device", "label": "หลักฐานเครื่องตรวจสมรรถภาพการได้ยินตามมาตรฐาน (ANSI S3.6-1996 หรือใหม่กว่า)",
                     "kind": "docs", "required": True, "min": 1},
                    {"key": "doc_audio_room", "label": "หลักฐานห้องหรือพื้นที่ตรวจสมรรถภาพการได้ยิน",
                     "kind": "docs", "required": True, "min": 1},
                    {"key": "doc_audio_photo", "label": "รูปถ่ายห้องหรือพื้นที่ตรวจการได้ยินของหน่วยบริการ",
                     "kind": "docs", "required": True, "min": 1},
                    {"key": "doc_audio_booth", "label": "หลักฐานตู้ตรวจการได้ยินที่มีระดับเสียงขั้นต่ำตามมาตรฐาน",
                     "kind": "docs", "required": True, "min": 1},
                ],
            },
            {
                "title": "เครื่องตรวจสมรรถภาพปอด",
                "fields": [
                    {"key": "doc_spiro_device", "label": "หลักฐานเครื่องตรวจสมรรถภาพปอดที่ได้รับรองมาตรฐานและแสดงผลได้",
                     "kind": "docs", "required": True, "min": 1,
                     "help": "ATS 1994 · ERS 2005 หรือมาตรฐานอื่นที่ไม่ต่ำกว่า (เลือกอย่างน้อย 1 รายการ)"},
                    {"key": "doc_spiro_photo", "label": "รูปถ่ายเครื่องตรวจสมรรถภาพปอด พร้อมอุปกรณ์ปรับความเที่ยงตรงประจำวัน",
                     "kind": "docs", "required": True, "min": 1},
                ],
            },
            {
                "title": "เครื่องมือตรวจสมรรถภาพการมองเห็น และการอบรม",
                "fields": [
                    {"key": "doc_vision_device", "label": "หลักฐานเครื่องตรวจสมรรถภาพการมองเห็น วัดสายตาในระยะใกล้และไกล",
                     "kind": "docs", "required": True, "min": 1},
                    {"key": "doc_vision_room", "label": "สไลด์ชุดสำหรับงานช่วงวัดสายตาตามมาตรฐานที่กำหนด",
                     "kind": "docs", "required": True, "min": 1},
                    {"key": "doc_training", "label": "หลักฐานการอบรมการใช้เครื่องมือสำหรับให้บริการอาชีวเวชกรรม",
                     "kind": "docs", "required": True, "min": 1},
                ],
            },
        ],
    },
    {"id": "step5", "title": "สรุปข้อมูล", "sections": [], "summary": True},
    {
        "id": "step6",
        "title": "ยื่นลงทะเบียน",
        "sections": [
            {
                "title": "ช่องทางการรับเอกสาร",
                "fields": [
                    {"key": "delivery_method", "label": "ช่องทางรับใบขึ้นทะเบียน", "kind": "radio", "required": True,
                     "options": ["ทางอิเล็กทรอนิกส์", "ทางไปรษณีย์ตอบรับ", "รับด้วยตนเอง"]},
                    {"key": "receiver_name", "label": "ชื่อผู้รับ", "kind": "text",
                     "when": {"delivery_method": "ทางไปรษณีย์ตอบรับ"}, "required_when": True},
                    {"key": "receiver_phone", "label": "เบอร์โทรศัพท์", "kind": "text",
                     "when": {"delivery_method": "ทางไปรษณีย์ตอบรับ"}, "required_when": True},
                    {"key": "receiver_address", "label": "ที่อยู่ในการจัดส่ง", "kind": "textarea",
                     "when": {"delivery_method": "ทางไปรษณีย์ตอบรับ"}, "required_when": True},
                ],
            },
        ],
    },
]

# the status timeline shown on the registration page (manual page 12)
TIMELINE = [
    "นำเข้าข้อมูล",
    "ตรวจสอบความครบถ้วนและความถูกต้อง",
    "ออกหลักฐานการรับขึ้นทะเบียน",
    "พิจารณาคำขอขึ้นทะเบียน",
    "ขึ้นทะเบียน",
    "รับใบทะเบียน",
]

STATUS_TH = {
    "draft": "แบบร่าง",
    "submitted": "รอเจ้าหน้าที่ตรวจสอบ",
    "changes_requested": "ต้องแก้ไขเอกสาร",
    "approved": "อนุมัติแล้ว",
    "issued": "ขึ้นทะเบียนแล้ว",
    "cancelled": "ยกเลิก",
}

STEP_BY_ID = {s["id"]: s for s in STEPS}


def fields_of(step_id: str):
    for section in STEP_BY_ID[step_id]["sections"]:
        for field in section["fields"]:
            yield field


def visible(field: dict, values: dict) -> bool:
    """A field with `when` only applies while the other answer matches."""
    for key, want in (field.get("when") or {}).items():
        if values.get(key) != want:
            return False
    return True


def missing_in_step(step_id: str, data: dict, documents: dict) -> list[str]:
    """Labels of what the manual requires and the form does not have yet."""
    values = data.get(step_id, {}) or {}
    out = []
    for field in fields_of(step_id):
        if not visible(field, values):
            continue
        required = field.get("required") or field.get("required_when")
        if field["kind"] == "docs":
            if required and len(documents.get(field["key"], [])) < field.get("min", 1):
                out.append(field["label"])
        elif field["kind"] == "people":
            people = values.get(field["key"]) or []
            named = [p for p in people if (p.get("name") or "").strip()]
            if required and len(named) < field.get("min", 1):
                out.append(f'{field["label"]} (ต้องมีอย่างน้อย {field.get("min", 1)} คน)')
            for i, person in enumerate(named, 1):
                for doc in field.get("person_docs", []):
                    if doc.get("min", 0) and len(person.get("documents", {}).get(doc["key"], [])) < doc["min"]:
                        out.append(f'{field["label"]} คนที่ {i}: {doc["label"]}')
        elif required and not str(values.get(field["key"], "")).strip():
            out.append(field["label"])
    return out


def missing_everywhere(data: dict, documents: dict) -> dict[str, list[str]]:
    """{step title: [missing labels]} across every step that has fields."""
    out = {}
    for step in STEPS:
        if step.get("summary"):
            continue
        missing = missing_in_step(step["id"], data, documents)
        if missing:
            out[step["title"]] = missing
    return out
