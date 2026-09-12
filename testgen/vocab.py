"""
vocab.py
========
Vocabulary pools for rendering test files.

Every pool is split into DEV and EXAM. The exam set is drawn only from the
EXAM pools, so a pipeline tuned on dev files meets names, headers and formats
it has never seen. "KNOWN" labels exist in the seeded central dictionary; the
NOVEL ones do not (an agent must work them out).
"""

# ---------------------------------------------------------------------------
# Lab / exam labels per template column
# ---------------------------------------------------------------------------

# Labels present in the central dictionary (0002_seed). Exact match should work.
KNOWN = {
    "venous_blood_lead": ["Blood Lead", "BPb", "Venous Blood Lead"],
    "wbc": ["WBC", "WBC Count", "White Blood Cell"],
    "hb": ["Hb", "Hemoglobin", "HGB"],
    "hct": ["Hct", "Hematocrit"],
    "plt": ["Platelet", "Platelet Count", "PLT"],
    "neutrophil": ["Neutrophil", "Neut%"],
    "lymphocyte": ["Lymphocyte", "Lymph%"],
    "monocyte": ["Monocyte", "Mono%"],
    "eosinophil": ["Eosinophil", "Eos%"],
    "basophil": ["Basophil", "Baso%"],
    "creatinine": ["Creatinine", "Cr", "Serum Creatinine"],
    "sgot_ast": ["SGOT", "AST", "AST (SGOT)"],
    "sgpt_alt": ["SGPT", "ALT", "ALT (SGPT)"],
    "alp": ["ALP", "Alkaline Phosphatase"],
    "tb": ["Total Bilirubin", "T.Bil"],
    "db": ["Direct Bilirubin", "D.Bil"],
    "uric_acid": ["Uric Acid"],
    "rbc_che": ["RBC Cholinesterase", "AChE"],
    "plasma_che_bche": ["Plasma Cholinesterase", "BChE"],
    "chest_xray": ["Chest X-ray", "CXR"],
    "xray_comment": ["Xray Comment"],
    "profusion": ["ILO Profusion"],
    "ekg": ["EKG", "ECG"],
    "ekg_comment": ["EKG Comment"],
    "bmi": ["BMI"],
    "bp_systolic": ["SBP", "Systolic"],
    "bp_diastolic": ["DBP", "Diastolic"],
    "pulse_rate": ["Pulse", "Heart Rate"],
    "spirometry_fvc_percent": ["FVC%"],
    "spirometry_fev1_percent": ["FEV1%"],
    "spirometry_fvc": ["FVC"],
    "spirometry_fev1": ["FEV1"],
    "spirometry_fev1_fvc": ["FEV1/FVC"],
    "spirometry_height": ["Spirometry Height"],
    "hearing_ability": ["Hearing", "Audiometry"],
    "hearing_comment": ["Hearing Comment"],
    "far_vision_test": ["Far Vision Test", "Visual Acuity"],
    "far_vision_comment": ["Vision Comment"],
}

# Mappable names NOT in the dictionary — dev pool
NOVEL_DEV = {
    "venous_blood_lead": ["Pb (Blood)", "ตะกั่วในเลือด"],
    "wbc": ["เม็ดเลือดขาว", "Leukocyte Count"],
    "hb": ["ฮีโมโกลบิน", "Haemoglobin"],
    "hct": ["ฮีมาโตคริต", "PCV"],
    "plt": ["เกล็ดเลือด", "Thrombocyte"],
    "neutrophil": ["Neutrophil (%)", "Segmented Neutrophil"],
    "lymphocyte": ["Lymphocyte (%)"],
    "monocyte": ["Monocyte (%)"],
    "eosinophil": ["Eosinophil (%)"],
    "basophil": ["Basophil (%)"],
    "creatinine": ["S.Creatinine", "ครีเอตินิน"],
    "sgot_ast": ["Aspartate Aminotransferase"],
    "sgpt_alt": ["Alanine Aminotransferase"],
    "alp": ["Alk. Phos."],
    "tb": ["Bilirubin Total", "TBil"],
    "db": ["Bilirubin Direct", "DBil"],
    "uric_acid": ["กรดยูริก", "Urate"],
    "rbc_che": ["Erythrocyte Cholinesterase"],
    "plasma_che_bche": ["Pseudocholinesterase"],
    "chest_xray": ["เอกซเรย์ปอด", "CXR Result"],
    "ekg": ["คลื่นไฟฟ้าหัวใจ"],
    "bmi": ["ดัชนีมวลกาย"],
    "pulse_rate": ["ชีพจร"],
    "spirometry_fvc_percent": ["FVC (% Pred)"],
    "spirometry_fev1_percent": ["FEV1 (% Pred)"],
    "spirometry_fev1_fvc": ["FEV1/FVC Ratio (%)"],
    "hearing_ability": ["ตรวจการได้ยิน"],
    "far_vision_test": ["สายตามองไกล"],
}

# Mappable names NOT in the dictionary — exam pool (never used in dev)
NOVEL_EXAM = {
    "venous_blood_lead": ["Lead, whole blood", "ระดับตะกั่ว"],
    "wbc": ["Total WBC", "จำนวนเม็ดเลือดขาว"],
    "hb": ["Hemoglobin (Hb)", "ค่าฮีโมโกลบิน"],
    "hct": ["Packed Cell Volume"],
    "plt": ["Platelet count (PLT)", "จำนวนเกล็ดเลือด"],
    "neutrophil": ["PMN %", "Neutrophils"],
    "lymphocyte": ["Lymphocytes"],
    "monocyte": ["Monocytes"],
    "eosinophil": ["Eosinophils"],
    "basophil": ["Basophils"],
    "creatinine": ["Creatinine, serum", "Crea"],
    "sgot_ast": ["AST/GOT"],
    "sgpt_alt": ["ALT/GPT"],
    "alp": ["Alkaline phosphatase (ALP)"],
    "tb": ["T-Bilirubin"],
    "db": ["D-Bilirubin"],
    "uric_acid": ["Uric acid, serum"],
    "rbc_che": ["AChE (RBC)"],
    "plasma_che_bche": ["Serum Cholinesterase"],
    "chest_xray": ["ภาพรังสีทรวงอก"],
    "ekg": ["Electrocardiography"],
    "bmi": ["Body Mass Index (BMI)"],
    "pulse_rate": ["อัตราการเต้นหัวใจ"],
    "spirometry_fvc_percent": ["%Pred FVC"],
    "spirometry_fev1_percent": ["%Pred FEV1"],
    "spirometry_fev1_fvc": ["FEV1/FVC (%)"],
    "hearing_ability": ["สมรรถภาพการได้ยิน"],
    "far_vision_test": ["การมองเห็นระยะไกล"],
}

# ---------------------------------------------------------------------------
# Labels that must NOT land in a template column
# (target "__extra__" = real result kept in extra_results; "__ignore__" = not a result)
# ---------------------------------------------------------------------------

# name -> (value generator key, unit)
EXTRAS_DEV = {
    "FBS": ("fbs", "mg/dL"),
    "Cholesterol": ("chol", "mg/dL"),
    "HbA1c": ("hba1c", "%"),
    "RBC": ("rbc", "10^6/µL"),                 # trap: not WBC
    "Indirect Bilirubin": ("ibil", "mg/dL"),   # trap: not direct bilirubin
    "Neut#": ("neut_abs", "10^3/µL"),          # trap: absolute count, not %
    "Lymph#": ("lymph_abs", "10^3/µL"),
}
EXTRAS_EXAM = {
    "Glucose (fasting)": ("fbs", "mg/dL"),
    "Triglyceride": ("tg", "mg/dL"),
    "LDL-C": ("ldl", "mg/dL"),
    "MCV": ("mcv", "fL"),
    "Bilirubin, indirect": ("ibil", "mg/dL"),
    "ANC": ("neut_abs", "10^3/µL"),            # absolute neutrophil count
    "Hb A1c": ("hba1c", "%"),
}

NOISE_DEV = ["HN", "VN", "ลำดับ", "Order No", "Ward"]
NOISE_EXAM = ["AN", "เลขที่ใบสั่ง", "No.", "แพทย์ผู้สั่ง"]

# ---------------------------------------------------------------------------
# Units: rendered = canonical * k  (so the mapping factor is 1/k)
# ---------------------------------------------------------------------------

UNIT_ALTS_DEV = {
    "hb": ("g/L", 10),
    "creatinine": ("µmol/L", 88.4),
    "wbc": ("10^3/µL", 0.001),
    "plt": ("10^3/µL", 0.001),
    "uric_acid": ("µmol/L", 59.48),
}
UNIT_ALTS_EXAM = {
    "tb": ("µmol/L", 17.1),
    "db": ("µmol/L", 17.1),
    "hct": ("L/L", 0.01),
    "wbc": ("10^9/L", 0.001),
    "venous_blood_lead": ("µmol/L", 0.0483),
    "spirometry_height": ("m", 0.01),
}

# ---------------------------------------------------------------------------
# Identity / visit column headers
# ---------------------------------------------------------------------------

ID_HEADERS_DEV = {
    "cid": ["cid", "เลขบัตรประชาชน", "CID", "เลขประจำตัวประชาชน"],
    "first_name": ["fname", "ชื่อ", "First Name"],
    "last_name": ["lname", "นามสกุล", "Last Name"],
    "department_id": ["department_id", "แผนก", "Dept"],
    "visit_date": ["vstdate", "วันที่ตรวจ", "Visit Date", "วันที่รับบริการ"],
    "lab_name": ["lab_name", "รายการตรวจ", "Test"],
    "result": ["result", "ผล", "Result"],
    "unit": ["unit", "หน่วย", "Unit"],
}
ID_HEADERS_EXAM = {
    "cid": ["PID", "เลขบัตร ปชช.", "National ID"],
    "first_name": ["ชื่อต้น", "Given name"],
    "last_name": ["ชื่อสกุล", "Surname"],
    "department_id": ["หน่วยงาน", "Section"],
    "visit_date": ["วันที่", "Service Date", "date_serv"],
    "lab_name": ["ชื่อการตรวจ", "Item", "Investigation"],
    "result": ["ค่าที่ได้", "Value", "ผลการตรวจ"],
    "unit": ["Units", "หน่วยวัด"],
}

# ---------------------------------------------------------------------------
# Categorical renderings (1 = normal, 2 = abnormal) and comment phrases
# ---------------------------------------------------------------------------

CATEGORICAL_DEV = {1: ["ปกติ", "Normal", "1"], 2: ["ผิดปกติ", "Abnormal", "2"]}
CATEGORICAL_EXAM = {1: ["N", "normal", "ไม่พบความผิดปกติ"], 2: ["AB", "abnormal", "พบความผิดปกติ"]}

# free-text comments whose class is unambiguous (for comment-only files)
COMMENTS_DEV = {
    "chest_xray": {1: ["Normal chest", "No active lung lesion", "ปอดปกติ"],
                   2: ["Fibrosis RUL", "Pleural thickening left", "พบฝ้าที่ปอดขวา"]},
    "ekg": {1: ["Normal sinus rhythm", "NSR", "คลื่นหัวใจปกติ"],
            2: ["Atrial fibrillation", "LVH", "ST depression V4-V6"]},
    "hearing_ability": {1: ["Normal hearing bilateral", "การได้ยินปกติ"],
                        2: ["Bilateral SNHL at 4000 Hz", "Mild hearing loss left"]},
    "far_vision_test": {1: ["VA 20/20 both eyes", "สายตาปกติ"],
                        2: ["Myopia needs correction", "สายตาสั้น ควรตัดแว่น"]},
}
COMMENTS_EXAM = {
    "chest_xray": {1: ["Clear lung fields", "ไม่พบความผิดปกติของปอด"],
                   2: ["Nodule 1 cm LUL", "Old TB scar right apex"]},
    "ekg": {1: ["Sinus rhythm, normal axis", "Within normal limits"],
            2: ["Right bundle branch block", "Sinus tachycardia 120/min"]},
    "hearing_ability": {1: ["Within normal limits both ears"],
                        2: ["Noise-induced hearing loss", "ประสาทหูเสื่อมข้างขวา"]},
    "far_vision_test": {1: ["Normal visual acuity"],
                        2: ["Visual acuity 6/18 OU", "มองไกลไม่ชัด"]},
}

THAI_MONTHS = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
               "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]

FIRST_NAMES = ["สมชาย", "สมหญิง", "วีระ", "สุดา", "ปราณี", "ธนพล", "จำปา", "อรุณ", "มาลี", "ประยุทธ",
               "กนกพร", "ชัยวัฒน์", "ศิริพร", "นพดล", "รัตนา", "สุรชัย", "วันเพ็ญ", "ณัฐพล", "พิมพ์ชนก", "อำนาจ"]
LAST_NAMES = ["ใจดี", "วงศ์สวัสดิ์", "ประสิทธิ์ผล", "สายชล", "วงษ์ดี", "กลิ่นหอม", "มณีรัตน์", "ศรีสุข",
              "บุญมา", "ทองคำ", "แก้วมณี", "พันธุ์ดี", "รุ่งเรือง", "สุขเกษม", "อินทร์แก้ว"]
DEPARTMENTS = ["PROD-01", "PROD-02", "CHEM-02", "WH-01", "QC-03", "ADMIN-01", "PAINT-01", "WELD-02"]
# how some HIS exports write the department instead of its code (dev only)
DEPT_NAMES = {"PROD-01": "ฝ่ายผลิต 1", "PROD-02": "ฝ่ายผลิต 2", "CHEM-02": "ฝ่ายเคมีภัณฑ์", "WH-01": "คลังสินค้า",
              "QC-03": "ตรวจสอบคุณภาพ", "ADMIN-01": "ธุรการ", "PAINT-01": "งานพ่นสี", "WELD-02": "งานเชื่อม"}
TITLES = ["นาย", "นาง", "นางสาว", "น.ส.", "นาง/นางสาว"]
TH_MONTHS_FULL = ["มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
                  "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"]
