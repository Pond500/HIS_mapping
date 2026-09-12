"""
catalog.py
==========
What each template column means — the context every agent gets.
General clinical descriptions only (not tuned to any test file).
"""

from app.template import FIELDS_BY_COLUMN, RESULT_COLUMNS

DESC = {
    "venous_blood_lead": "Lead level in venous whole blood (occupational lead exposure)",
    "wbc": "White blood cell (leukocyte) count, total",
    "hb": "Hemoglobin concentration",
    "hct": "Hematocrit (packed cell volume)",
    "plt": "Platelet (thrombocyte) count",
    "neutrophil": "Neutrophil PERCENTAGE of WBC differential (not the absolute count)",
    "lymphocyte": "Lymphocyte PERCENTAGE of WBC differential (not the absolute count)",
    "monocyte": "Monocyte PERCENTAGE of WBC differential (not the absolute count)",
    "eosinophil": "Eosinophil PERCENTAGE of WBC differential (not the absolute count)",
    "basophil": "Basophil PERCENTAGE of WBC differential (not the absolute count)",
    "creatinine": "Serum creatinine (kidney function)",
    "sgot_ast": "AST / SGOT, aspartate aminotransferase (liver enzyme)",
    "sgpt_alt": "ALT / SGPT, alanine aminotransferase (liver enzyme)",
    "alp": "Alkaline phosphatase",
    "tb": "TOTAL bilirubin",
    "db": "DIRECT (conjugated) bilirubin — not indirect, not total",
    "uric_acid": "Serum uric acid",
    "chest_xray": "Chest X-ray overall result: 1 = normal, 2 = abnormal",
    "xray_comment": "Chest X-ray findings as free text",
    "profusion": "ILO classification small-opacity profusion, e.g. 0/1, 1/0 (pneumoconiosis)",
    "primary_lesion": "ILO primary shape/size of small opacities (p, q, r, s, t, u)",
    "secondary_lesion": "ILO secondary shape/size of small opacities (p, q, r, s, t, u)",
    "rbc_che": "Red-cell (erythrocyte) acetylcholinesterase, AChE (pesticide exposure)",
    "plasma_che_bche": "Plasma / serum cholinesterase, butyrylcholinesterase, BChE, pseudocholinesterase",
    "ekg": "Electrocardiogram overall result: 1 = normal, 2 = abnormal",
    "ekg_comment": "EKG findings as free text",
    "bmi": "Body mass index",
    "bp_systolic": "Systolic blood pressure",
    "bp_diastolic": "Diastolic blood pressure",
    "pulse_rate": "Pulse / heart rate",
    "spirometry_fvc_percent": "FVC as PERCENT OF PREDICTED",
    "spirometry_fev1_percent": "FEV1 as PERCENT OF PREDICTED",
    "spirometry_fvc": "FVC measured volume in litres (not % predicted)",
    "spirometry_fev1": "FEV1 measured volume in litres (not % predicted)",
    "spirometry_fev1_fvc": "FEV1/FVC ratio in percent",
    "spirometry_height": "Height recorded for spirometry",
    "hearing_ability": "Hearing / audiometry overall result: 1 = normal, 2 = abnormal",
    "hearing_comment": "Hearing findings as free text",
    "far_vision_test": "Far vision / visual acuity overall result: 1 = suitable/normal, 2 = may be unsuitable",
    "far_vision_comment": "Vision findings as free text",
}
assert set(DESC) == set(RESULT_COLUMNS)


def catalog_text() -> str:
    lines = ["column | kind | canonical unit | plausible range | meaning"]
    for c in RESULT_COLUMNS:
        f = FIELDS_BY_COLUMN[c]
        rng = f"{f.lo:g}–{f.hi:g}" if f.lo is not None else "-"
        lines.append(f"{c} | {f.kind} | {f.unit or '-'} | {rng} | {DESC[c]}")
    return "\n".join(lines)
