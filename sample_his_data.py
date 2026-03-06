"""
sample_his_data.py
==================
ข้อมูลจำลอง (sample data) ที่เลียนแบบโครงสร้างจาก HIS จริง
แบ่งตามตารางต้นทางใน HIS:
- lab_results     → จากตาราง lab_order (CBC, Liver, Kidney, Toxicology)
- vital_signs     → จากตาราง opdscreen (BMI, BP, Pulse)
- xray_results    → จากตาราง xray_report (Chest X-ray + ILO)
- special_exams   → EKG, Spirometry, Hearing, Vision
- patient_info    → จากตาราง patient (ข้อมูลส่วนบุคคล)
"""


def get_patient_info() -> list[dict]:
    """ข้อมูลผู้ป่วย — จำลองจากตาราง `patient` ใน HIS"""
    return [
        {
            "cid": "1100500112233",
            "hn": "HN001",
            "fname": "สมชาย",
            "lname": "ใจดี",
            "department_id": "DEPT-A01",
        },
        {
            "cid": "1100500445566",
            "hn": "HN002",
            "fname": "สมหญิง",
            "lname": "รักษา",
            "department_id": "DEPT-B02",
        },
        {
            "cid": "1100500778899",
            "hn": "HN003",
            "fname": "วิชัย",
            "lname": "สุขสันต์",
            "department_id": "DEPT-A01",
        },
    ]


def get_lab_results() -> list[dict]:
    """
    ผลตรวจ Lab — จำลองจากตาราง `lab_order` ใน HIS
    รูปแบบ Long/EAV: 1 row = 1 ผลตรวจ

    NOTE: ใน HIS จริง ชื่อ lab_name อาจแตกต่างกันไปตามการตั้งค่าของแต่ละ รพ.
    """
    return [
        # ========== คนที่ 1: สมชาย ==========
        # CBC
        {"cid": "1100500112233", "visit_date": "2026-02-15", "lab_name": "WBC", "result": 7500},
        {"cid": "1100500112233", "visit_date": "2026-02-15", "lab_name": "Hemoglobin", "result": 13.2},
        {"cid": "1100500112233", "visit_date": "2026-02-15", "lab_name": "Hematocrit", "result": 39.5},
        {"cid": "1100500112233", "visit_date": "2026-02-15", "lab_name": "Platelet", "result": 250000},
        {"cid": "1100500112233", "visit_date": "2026-02-15", "lab_name": "Neutrophil", "result": 60.5},
        {"cid": "1100500112233", "visit_date": "2026-02-15", "lab_name": "Lymphocyte", "result": 30.2},
        {"cid": "1100500112233", "visit_date": "2026-02-15", "lab_name": "Monocyte", "result": 5.1},
        {"cid": "1100500112233", "visit_date": "2026-02-15", "lab_name": "Eosinophil", "result": 3.5},
        {"cid": "1100500112233", "visit_date": "2026-02-15", "lab_name": "Basophil", "result": 0.7},
        # Kidney
        {"cid": "1100500112233", "visit_date": "2026-02-15", "lab_name": "Creatinine", "result": 1.1},
        # Liver
        {"cid": "1100500112233", "visit_date": "2026-02-15", "lab_name": "AST (SGOT)", "result": 25},
        {"cid": "1100500112233", "visit_date": "2026-02-15", "lab_name": "ALT (SGPT)", "result": 22},
        {"cid": "1100500112233", "visit_date": "2026-02-15", "lab_name": "ALP", "result": 65},
        {"cid": "1100500112233", "visit_date": "2026-02-15", "lab_name": "Total Bilirubin", "result": 0.8},
        {"cid": "1100500112233", "visit_date": "2026-02-15", "lab_name": "Direct Bilirubin", "result": 0.2},
        # Metabolic
        {"cid": "1100500112233", "visit_date": "2026-02-15", "lab_name": "Uric Acid", "result": 6.5},
        # Toxicology
        {"cid": "1100500112233", "visit_date": "2026-02-15", "lab_name": "Blood Lead", "result": 8.5},
        {"cid": "1100500112233", "visit_date": "2026-02-15", "lab_name": "RBC Cholinesterase", "result": 10200},
        {"cid": "1100500112233", "visit_date": "2026-02-15", "lab_name": "Plasma Cholinesterase", "result": 6800},

        # ========== คนที่ 2: สมหญิง ==========
        {"cid": "1100500445566", "visit_date": "2026-02-16", "lab_name": "WBC", "result": 8200},
        {"cid": "1100500445566", "visit_date": "2026-02-16", "lab_name": "Hemoglobin", "result": 12.0},
        {"cid": "1100500445566", "visit_date": "2026-02-16", "lab_name": "Hematocrit", "result": 36.0},
        {"cid": "1100500445566", "visit_date": "2026-02-16", "lab_name": "Platelet", "result": 310000},
        {"cid": "1100500445566", "visit_date": "2026-02-16", "lab_name": "Neutrophil", "result": 55.0},
        {"cid": "1100500445566", "visit_date": "2026-02-16", "lab_name": "Lymphocyte", "result": 35.0},
        {"cid": "1100500445566", "visit_date": "2026-02-16", "lab_name": "Monocyte", "result": 6.0},
        {"cid": "1100500445566", "visit_date": "2026-02-16", "lab_name": "Eosinophil", "result": 3.0},
        {"cid": "1100500445566", "visit_date": "2026-02-16", "lab_name": "Basophil", "result": 1.0},
        {"cid": "1100500445566", "visit_date": "2026-02-16", "lab_name": "Creatinine", "result": 0.8},
        {"cid": "1100500445566", "visit_date": "2026-02-16", "lab_name": "AST (SGOT)", "result": 45},
        {"cid": "1100500445566", "visit_date": "2026-02-16", "lab_name": "ALT (SGPT)", "result": 52},
        {"cid": "1100500445566", "visit_date": "2026-02-16", "lab_name": "ALP", "result": 78},
        {"cid": "1100500445566", "visit_date": "2026-02-16", "lab_name": "Total Bilirubin", "result": 1.2},
        {"cid": "1100500445566", "visit_date": "2026-02-16", "lab_name": "Direct Bilirubin", "result": 0.4},
        {"cid": "1100500445566", "visit_date": "2026-02-16", "lab_name": "Uric Acid", "result": 5.2},
        {"cid": "1100500445566", "visit_date": "2026-02-16", "lab_name": "Blood Lead", "result": 3.2},
        {"cid": "1100500445566", "visit_date": "2026-02-16", "lab_name": "RBC Cholinesterase", "result": 11500},
        {"cid": "1100500445566", "visit_date": "2026-02-16", "lab_name": "Plasma Cholinesterase", "result": 7200},

        # ========== คนที่ 3: วิชัย ==========
        {"cid": "1100500778899", "visit_date": "2026-02-17", "lab_name": "WBC", "result": 6800},
        {"cid": "1100500778899", "visit_date": "2026-02-17", "lab_name": "Hemoglobin", "result": 15.1},
        {"cid": "1100500778899", "visit_date": "2026-02-17", "lab_name": "Hematocrit", "result": 45.2},
        {"cid": "1100500778899", "visit_date": "2026-02-17", "lab_name": "Platelet", "result": 180000},
        {"cid": "1100500778899", "visit_date": "2026-02-17", "lab_name": "Neutrophil", "result": 62.0},
        {"cid": "1100500778899", "visit_date": "2026-02-17", "lab_name": "Lymphocyte", "result": 28.0},
        {"cid": "1100500778899", "visit_date": "2026-02-17", "lab_name": "Monocyte", "result": 4.5},
        {"cid": "1100500778899", "visit_date": "2026-02-17", "lab_name": "Eosinophil", "result": 4.0},
        {"cid": "1100500778899", "visit_date": "2026-02-17", "lab_name": "Basophil", "result": 1.5},
        {"cid": "1100500778899", "visit_date": "2026-02-17", "lab_name": "Creatinine", "result": 1.4},
        {"cid": "1100500778899", "visit_date": "2026-02-17", "lab_name": "AST (SGOT)", "result": 30},
        {"cid": "1100500778899", "visit_date": "2026-02-17", "lab_name": "ALT (SGPT)", "result": 28},
        {"cid": "1100500778899", "visit_date": "2026-02-17", "lab_name": "ALP", "result": 55},
        {"cid": "1100500778899", "visit_date": "2026-02-17", "lab_name": "Total Bilirubin", "result": 0.6},
        {"cid": "1100500778899", "visit_date": "2026-02-17", "lab_name": "Direct Bilirubin", "result": 0.1},
        {"cid": "1100500778899", "visit_date": "2026-02-17", "lab_name": "Uric Acid", "result": 7.8},
        {"cid": "1100500778899", "visit_date": "2026-02-17", "lab_name": "Blood Lead", "result": 15.3},
        {"cid": "1100500778899", "visit_date": "2026-02-17", "lab_name": "RBC Cholinesterase", "result": 9800},
        {"cid": "1100500778899", "visit_date": "2026-02-17", "lab_name": "Plasma Cholinesterase", "result": 5500},
    ]


def get_vital_signs() -> list[dict]:
    """ข้อมูลสัญญาณชีพ — จำลองจากตาราง `opdscreen` ใน HIS"""
    return [
        {
            "cid": "1100500112233",
            "visit_date": "2026-02-15",
            "bmi": 24.5,
            "bp_systolic": 120,
            "bp_diastolic": 78,
            "pulse_rate": 72,
        },
        {
            "cid": "1100500445566",
            "visit_date": "2026-02-16",
            "bmi": 22.1,
            "bp_systolic": 135,
            "bp_diastolic": 88,
            "pulse_rate": 80,
        },
        {
            "cid": "1100500778899",
            "visit_date": "2026-02-17",
            "bmi": 27.8,
            "bp_systolic": 140,
            "bp_diastolic": 92,
            "pulse_rate": 85,
        },
    ]


def get_xray_results() -> list[dict]:
    """ผล X-ray — จำลองจากตาราง `xray_report` ใน HIS"""
    return [
        {
            "cid": "1100500112233",
            "visit_date": "2026-02-15",
            "result": "Normal",              # → chest_xray = 1
            "comment": "No active lung lesion",
            "profusion": None,
            "primary_lesion": None,
            "secondary_lesion": None,
        },
        {
            "cid": "1100500445566",
            "visit_date": "2026-02-16",
            "result": "Abnormal",             # → chest_xray = 2
            "comment": "Mild fibrosis at bilateral lower lobes",
            "profusion": 1,
            "primary_lesion": "s",
            "secondary_lesion": "t",
        },
        {
            "cid": "1100500778899",
            "visit_date": "2026-02-17",
            "result": "Normal",
            "comment": "Clear lung fields",
            "profusion": None,
            "primary_lesion": None,
            "secondary_lesion": None,
        },
    ]


def get_special_exams() -> list[dict]:
    """
    ผลตรวจพิเศษ — EKG, Spirometry, Hearing, Vision
    ใน HIS จริงอาจมาจากตาราง custom หรือ lab_order ก็ได้
    """
    return [
        # ========== คนที่ 1: สมชาย ==========
        {
            "cid": "1100500112233",
            "visit_date": "2026-02-15",
            "ekg": "Normal Sinus Rhythm",
            "ekg_comment": "NSR, rate 72 bpm",
            "spirometry_fvc_percent": 95.0,
            "spirometry_fev1_percent": 92.0,
            "spirometry_fvc": 4.20,
            "spirometry_fev1": 3.50,
            "spirometry_fev1_fvc": 83.3,
            "spirometry_height": 172.0,
            "hearing": "Pass",
            "hearing_comment": "Hearing within normal limits bilateral",
            "vision": "เหมาะสม",
            "vision_comment": "VA 20/20 OU",
        },
        # ========== คนที่ 2: สมหญิง ==========
        {
            "cid": "1100500445566",
            "visit_date": "2026-02-16",
            "ekg": "Abnormal",
            "ekg_comment": "Sinus tachycardia, rate 105 bpm",
            "spirometry_fvc_percent": 78.0,
            "spirometry_fev1_percent": 72.0,
            "spirometry_fvc": 2.80,
            "spirometry_fev1": 2.10,
            "spirometry_fev1_fvc": 75.0,
            "spirometry_height": 158.0,
            "hearing": "Fail",
            "hearing_comment": "High frequency hearing loss at 4000 Hz, right ear",
            "vision": "อาจไม่เหมาะสม",
            "vision_comment": "VA 20/40 OD, 20/25 OS. แนะนำพบจักษุแพทย์",
        },
        # ========== คนที่ 3: วิชัย ==========
        {
            "cid": "1100500778899",
            "visit_date": "2026-02-17",
            "ekg": "Normal",
            "ekg_comment": "NSR, rate 85 bpm, no ST changes",
            "spirometry_fvc_percent": 88.0,
            "spirometry_fev1_percent": 85.0,
            "spirometry_fvc": 4.50,
            "spirometry_fev1": 3.80,
            "spirometry_fev1_fvc": 84.4,
            "spirometry_height": 175.0,
            "hearing": "Pass",
            "hearing_comment": "Normal hearing bilateral",
            "vision": "เหมาะสม",
            "vision_comment": "VA 20/20 OU with correction",
        },
    ]
