"""
mapping_config.py
=================
Mapping Dictionary กลาง:
- แปลงชื่อ Lab ใน HIS → ชื่อ column ใน template
- กำหนดประเภทข้อมูลและแหล่งที่มา
"""

# ---------------------------------------------------------------------------
# Template column order (ต้องตรงกับ result_template_v1.1.xlsx ทุกประการ)
# ---------------------------------------------------------------------------
TEMPLATE_COLUMNS = [
    "เลขบัตรประชาชน",
    "ชื่อ",
    "นามสกุล",
    "ID แผนก",
    "วันที่ตรวจ (ปปปป-ดด-วว)",
    "venous_blood_lead",
    "wbc",
    "hb",
    "hct",
    "plt",
    "neutrophil",
    "lymphocyte",
    "monocyte",
    "eosinophil",
    "basophil",
    "creatinine",
    "sgot_ast",
    "sgpt_alt",
    "alp",
    "tb",
    "db",
    "uric_acid",
    "chest_xray",
    "xray_comment",
    "profusion",
    "primary_lesion",
    "secondary_lesion",
    "rbc_che",
    "plasma_che_bche",
    "ekg",
    "ekg_comment",
    "bmi",
    "bp_systolic",
    "bp_diastolic",
    "pulse_rate",
    "spirometry_fvc_percent",
    "spirometry_fev1_percent",
    "spirometry_fvc",
    "spirometry_fev1",
    "spirometry_fev1_fvc",
    "spirometry_height",
    "hearing_ability",
    "hearing_comment",
    "far_vision_test",
    "far_vision_comment",
]

# ---------------------------------------------------------------------------
# Mapping: ชื่อ Lab ใน HIS → ชื่อ column ใน template
# ---------------------------------------------------------------------------
# Key   = ชื่อที่ HIS ใช้ (ตัวพิมพ์เล็กทั้งหมดเพื่อ case-insensitive matching)
# Value = ชื่อ column ใน template
#
# NOTE: ในการใช้งานจริง ต้องเพิ่มชื่อ Lab ที่แต่ละ รพ. ใช้ให้ครบ
#       เช่น รพ. A อาจเรียก "WBC" แต่ รพ. B เรียก "White Blood Cell Count"
# ---------------------------------------------------------------------------

LAB_NAME_TO_TEMPLATE = {
    # --- CBC ---
    "wbc": "wbc",
    "white blood cell": "wbc",
    "white blood cell count": "wbc",
    "wbc count": "wbc",

    "hb": "hb",
    "hemoglobin": "hb",
    "hgb": "hb",

    "hct": "hct",
    "hematocrit": "hct",

    "plt": "plt",
    "platelet": "plt",
    "platelet count": "plt",

    "neutrophil": "neutrophil",
    "neutrophil %": "neutrophil",
    "neut": "neutrophil",
    "neut%": "neutrophil",

    "lymphocyte": "lymphocyte",
    "lymphocyte %": "lymphocyte",
    "lymph": "lymphocyte",
    "lymph%": "lymphocyte",

    "monocyte": "monocyte",
    "monocyte %": "monocyte",
    "mono": "monocyte",
    "mono%": "monocyte",

    "eosinophil": "eosinophil",
    "eosinophil %": "eosinophil",
    "eos": "eosinophil",
    "eos%": "eosinophil",

    "basophil": "basophil",
    "basophil %": "basophil",
    "baso": "basophil",
    "baso%": "basophil",

    # --- Kidney ---
    "creatinine": "creatinine",
    "serum creatinine": "creatinine",
    "cr": "creatinine",

    # --- Liver ---
    "sgot": "sgot_ast",
    "ast": "sgot_ast",
    "sgot (ast)": "sgot_ast",
    "ast (sgot)": "sgot_ast",
    "sgot_ast": "sgot_ast",

    "sgpt": "sgpt_alt",
    "alt": "sgpt_alt",
    "sgpt (alt)": "sgpt_alt",
    "alt (sgpt)": "sgpt_alt",
    "sgpt_alt": "sgpt_alt",

    "alp": "alp",
    "alkaline phosphatase": "alp",

    "total bilirubin": "tb",
    "tb": "tb",
    "t.bil": "tb",

    "direct bilirubin": "db",
    "db": "db",
    "d.bil": "db",

    # --- Metabolic ---
    "uric acid": "uric_acid",
    "uric": "uric_acid",

    # --- Toxicology ---
    "blood lead": "venous_blood_lead",
    "venous blood lead": "venous_blood_lead",
    "lead (venous)": "venous_blood_lead",
    "bpb": "venous_blood_lead",

    "rbc cholinesterase": "rbc_che",
    "rbc-che": "rbc_che",
    "rbc che": "rbc_che",
    "ache": "rbc_che",

    "plasma cholinesterase": "plasma_che_bche",
    "plasma che": "plasma_che_bche",
    "bche": "plasma_che_bche",
    "butyrylcholinesterase": "plasma_che_bche",

    # --- Spirometry ---
    "fvc%": "spirometry_fvc_percent",
    "fvc percent": "spirometry_fvc_percent",
    "fvc % predicted": "spirometry_fvc_percent",

    "fev1%": "spirometry_fev1_percent",
    "fev1 percent": "spirometry_fev1_percent",
    "fev1 % predicted": "spirometry_fev1_percent",

    "fvc": "spirometry_fvc",
    "fvc (l)": "spirometry_fvc",

    "fev1": "spirometry_fev1",
    "fev1 (l)": "spirometry_fev1",

    "fev1/fvc": "spirometry_fev1_fvc",
    "fev1/fvc ratio": "spirometry_fev1_fvc",
    "fev1/fvc%": "spirometry_fev1_fvc",

    "spirometry height": "spirometry_height",
    "height (spirometry)": "spirometry_height",

    # --- Clinical / Physical Exam (for Long format support) ---
    # X-ray
    "chest x-ray": "chest_xray",
    "chest xray": "chest_xray",
    "cxr": "chest_xray",
    "xray": "chest_xray",
    "chest x-ray result": "chest_xray",
    "ผลเอ็กซเรย์": "chest_xray",
    "ผล xray": "chest_xray",
    "xray comment": "xray_comment",
    "chest x-ray comment": "xray_comment",
    "xray detail": "xray_comment",
    "xray finding": "xray_comment",
    "ilo profusion": "profusion",
    "profusion": "profusion",
    "primary lesion": "primary_lesion",
    "secondary lesion": "secondary_lesion",

    # EKG
    "ekg": "ekg",
    "ecg": "ekg",
    "ekg result": "ekg",
    "ecg result": "ekg",
    "electrocardiogram": "ekg",
    "ผล ekg": "ekg",
    "ผลคลื่นหัวใจ": "ekg",
    "ekg comment": "ekg_comment",
    "ecg comment": "ekg_comment",
    "ekg detail": "ekg_comment",
    "ekg finding": "ekg_comment",

    # Vitals
    "bmi": "bmi",
    "body mass index": "bmi",
    "bp systolic": "bp_systolic",
    "bp_systolic": "bp_systolic",
    "sbp": "bp_systolic",
    "systolic": "bp_systolic",
    "systolic bp": "bp_systolic",
    "bp diastolic": "bp_diastolic",
    "bp_diastolic": "bp_diastolic",
    "dbp": "bp_diastolic",
    "diastolic": "bp_diastolic",
    "diastolic bp": "bp_diastolic",
    "pulse rate": "pulse_rate",
    "pulse": "pulse_rate",
    "heart rate": "pulse_rate",
    "hr": "pulse_rate",

    # Hearing
    "hearing": "hearing_ability",
    "hearing ability": "hearing_ability",
    "hearing test": "hearing_ability",
    "audiometry": "hearing_ability",
    "การได้ยิน": "hearing_ability",
    "ผลการได้ยิน": "hearing_ability",
    "hearing comment": "hearing_comment",
    "hearing detail": "hearing_comment",
    "audiometry comment": "hearing_comment",

    # Vision
    "far vision": "far_vision_test",
    "far vision test": "far_vision_test",
    "vision test": "far_vision_test",
    "visual acuity": "far_vision_test",
    "สายตา": "far_vision_test",
    "ผลสายตา": "far_vision_test",
    "far vision comment": "far_vision_comment",
    "vision comment": "far_vision_comment",
    "vision detail": "far_vision_comment",
}

# ---------------------------------------------------------------------------
# Fields ที่เป็น Categorical เมื่ออยู่ใน Long format
# ถ้า lab_name map ไปยัง field เหล่านี้ → ต้องแปลง result เป็น 1/2
# ---------------------------------------------------------------------------

CLINICAL_CATEGORICAL_IN_LONG = {
    "chest_xray", "ekg", "hearing_ability", "far_vision_test",
}

# ---------------------------------------------------------------------------
# Mapping สำหรับข้อมูลที่เป็น ปกติ/ผิดปกติ (categorical)
# ค่าที่ HIS อาจส่งมา → ค่าที่ template ต้องการ (1=ปกติ, 2=ผิดปกติ)
# ---------------------------------------------------------------------------

NORMAL_ABNORMAL_MAP = {
    # ภาษาอังกฤษ
    "normal": 1,
    "abnormal": 2,
    "unremarkable": 1,
    "remarkable": 2,
    "within normal limits": 1,
    "wnl": 1,

    # ค่าที่เป็นตัวเลขอยู่แล้ว
    "1": 1,
    "2": 2,
    1: 1,
    2: 2,

    # ภาษาไทย
    "ปกติ": 1,
    "ผิดปกติ": 2,

    # EKG specific
    "nsr": 1,           # Normal Sinus Rhythm
    "normal sinus rhythm": 1,
    "sinus rhythm": 1,

    # Hearing
    "pass": 1,
    "fail": 2,
    "ผ่าน": 1,
    "ไม่ผ่าน": 2,

    # Vision
    "เหมาะสม": 1,
    "อาจไม่เหมาะสม": 2,
    "suitable": 1,
    "not suitable": 2,
}

# ---------------------------------------------------------------------------
# ข้อมูล Categorical fields ที่ต้องแปลง ปกติ/ผิดปกติ
# ---------------------------------------------------------------------------

CATEGORICAL_FIELDS = {
    "chest_xray",
    "ekg",
    "hearing_ability",
    "far_vision_test",
}

# ---------------------------------------------------------------------------
# Comment fields — เก็บ comment ตามผลตรวจ categorical
# ---------------------------------------------------------------------------

COMMENT_FIELDS = {
    "chest_xray": "xray_comment",
    "ekg": "ekg_comment",
    "hearing_ability": "hearing_comment",
    "far_vision_test": "far_vision_comment",
}
