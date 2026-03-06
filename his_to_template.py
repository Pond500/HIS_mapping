"""
his_to_template.py
==================
Core Logic: แปลงข้อมูลจาก HIS (Long/EAV) → Template (Wide)

ขั้นตอน:
  1. Load    — โหลดข้อมูลจากแหล่งต่างๆ (lab, vitals, xray, special)
  2. Map     — แปลชื่อ Lab ใน HIS → ชื่อ column ใน template
  3. Pivot   — รวมหลายแถว (Long) → 1 แถว/คน (Wide)
  4. Transform — แปลงค่า (ค.ศ.→พ.ศ., Normal→1, Abnormal→2)
  5. Export  — เขียนผลลัพธ์ลง Excel ตาม template
"""

from datetime import datetime
from typing import Optional

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from mapping_config import (
    CATEGORICAL_FIELDS,
    COMMENT_FIELDS,
    LAB_NAME_TO_TEMPLATE,
    NORMAL_ABNORMAL_MAP,
    TEMPLATE_COLUMNS,
)


# ======================================================================
# ขั้นตอนที่ 1: LOAD — โหลดข้อมูลจากแหล่งต่างๆ
# ======================================================================


def load_all_data(patient_info, lab_results, vital_signs, xray_results, special_exams):
    """
    รวมข้อมูลจากทุกแหล่งเข้ามาเป็น dict เดียว
    โดยใช้ (cid, visit_date) เป็น key

    Returns:
        dict: {(cid, visit_date): {column_name: value, ...}}
    """
    merged = {}

    # -- สร้าง patient lookup (cid → patient info) --
    patient_lookup = {p["cid"]: p for p in patient_info}

    # -- รวม Lab results (Long → จัดกลุ่มตาม cid+date) --
    for row in lab_results:
        key = (row["cid"], row["visit_date"])
        if key not in merged:
            merged[key] = _init_row(row["cid"], row["visit_date"], patient_lookup)
        merged[key]["_lab_rows"].append(row)

    # -- รวม Vital signs --
    for row in vital_signs:
        key = (row["cid"], row["visit_date"])
        if key not in merged:
            merged[key] = _init_row(row["cid"], row["visit_date"], patient_lookup)
        merged[key]["bmi"] = row.get("bmi")
        merged[key]["bp_systolic"] = row.get("bp_systolic")
        merged[key]["bp_diastolic"] = row.get("bp_diastolic")
        merged[key]["pulse_rate"] = row.get("pulse_rate")

    # -- รวม X-ray results --
    for row in xray_results:
        key = (row["cid"], row["visit_date"])
        if key not in merged:
            merged[key] = _init_row(row["cid"], row["visit_date"], patient_lookup)
        merged[key]["_xray"] = row

    # -- รวม Special exams --
    for row in special_exams:
        key = (row["cid"], row["visit_date"])
        if key not in merged:
            merged[key] = _init_row(row["cid"], row["visit_date"], patient_lookup)
        merged[key]["_special"] = row

    return merged


def _init_row(cid, visit_date, patient_lookup):
    """สร้าง row เริ่มต้นพร้อม patient info"""
    patient = patient_lookup.get(cid, {})
    return {
        "เลขบัตรประชาชน": cid,
        "ชื่อ": patient.get("fname", ""),
        "นามสกุล": patient.get("lname", ""),
        "ID แผนก": patient.get("department_id", ""),
        "วันที่ตรวจ (ปปปป-ดด-วว)": visit_date,   # จะถูกแปลง พ.ศ. ภายหลัง
        "_lab_rows": [],
        "_xray": None,
        "_special": None,
    }


# ======================================================================
# ขั้นตอนที่ 2: MAP — แปลชื่อ Lab ใน HIS → ชื่อ column ใน template
# ======================================================================


def map_lab_name(his_lab_name: str) -> Optional[str]:
    """
    แปลงชื่อ Lab จาก HIS → ชื่อ column ใน template
    ใช้ case-insensitive matching

    Args:
        his_lab_name: ชื่อ Lab ตามที่ HIS ใช้

    Returns:
        ชื่อ column ใน template หรือ None ถ้า map ไม่ได้
    """
    normalized = his_lab_name.strip().lower()
    template_col = LAB_NAME_TO_TEMPLATE.get(normalized)

    if template_col is None:
        print(f"  ⚠️  ไม่พบ mapping สำหรับ Lab: '{his_lab_name}'")

    return template_col


# ======================================================================
# ขั้นตอนที่ 3: PIVOT — รวมหลายแถว (Long) → 1 แถว/คน (Wide)
# ======================================================================


def pivot_to_wide(merged_data: dict) -> list[dict]:
    """
    แปลงข้อมูลที่รวมแล้ว → 1 dict/คน ที่มี key ตรงกับ TEMPLATE_COLUMNS

    นี่คือหัวใจของ mapping:
    - Lab rows (Long) → pivot เป็น columns
    - X-ray → map ปกติ/ผิดปกติ + comment + ILO fields
    - Special exams → map EKG, Spirometry, Hearing, Vision
    """
    results = []

    for (cid, visit_date), data in merged_data.items():
        row = {col: None for col in TEMPLATE_COLUMNS}

        # --- ข้อมูลพื้นฐาน ---
        row["เลขบัตรประชาชน"] = data["เลขบัตรประชาชน"]
        row["ชื่อ"] = data["ชื่อ"]
        row["นามสกุล"] = data["นามสกุล"]
        row["ID แผนก"] = data["ID แผนก"]
        row["วันที่ตรวจ (ปปปป-ดด-วว)"] = data["วันที่ตรวจ (ปปปป-ดด-วว)"]

        # --- Pivot Lab results ---
        for lab_row in data.get("_lab_rows", []):
            template_col = map_lab_name(lab_row["lab_name"])
            if template_col and template_col in row:
                row[template_col] = lab_row["result"]

        # --- Vital Signs ---
        for vs_field in ["bmi", "bp_systolic", "bp_diastolic", "pulse_rate"]:
            if data.get(vs_field) is not None:
                row[vs_field] = data[vs_field]

        # --- X-ray ---
        xray = data.get("_xray")
        if xray:
            row["chest_xray"] = _convert_normal_abnormal(xray.get("result"))
            row["xray_comment"] = xray.get("comment")
            row["profusion"] = xray.get("profusion")
            row["primary_lesion"] = xray.get("primary_lesion")
            row["secondary_lesion"] = xray.get("secondary_lesion")

        # --- Special exams ---
        special = data.get("_special")
        if special:
            # EKG
            row["ekg"] = _convert_normal_abnormal(special.get("ekg"))
            row["ekg_comment"] = special.get("ekg_comment")

            # Spirometry
            row["spirometry_fvc_percent"] = special.get("spirometry_fvc_percent")
            row["spirometry_fev1_percent"] = special.get("spirometry_fev1_percent")
            row["spirometry_fvc"] = special.get("spirometry_fvc")
            row["spirometry_fev1"] = special.get("spirometry_fev1")
            row["spirometry_fev1_fvc"] = special.get("spirometry_fev1_fvc")
            row["spirometry_height"] = special.get("spirometry_height")

            # Hearing
            row["hearing_ability"] = _convert_normal_abnormal(special.get("hearing"))
            row["hearing_comment"] = special.get("hearing_comment")

            # Vision
            row["far_vision_test"] = _convert_normal_abnormal(special.get("vision"))
            row["far_vision_comment"] = special.get("vision_comment")

        results.append(row)

    return results


def _convert_normal_abnormal(value) -> Optional[int]:
    """
    แปลงค่า ปกติ/ผิดปกติ จาก HIS → 1/2 ตาม template

    ตัวอย่าง:
        "Normal"              → 1
        "Abnormal"            → 2
        "Normal Sinus Rhythm" → 1
        "Pass"                → 1
        "เหมาะสม"              → 1
    """
    if value is None:
        return None

    # ถ้าเป็นตัวเลขอยู่แล้ว
    if isinstance(value, (int, float)):
        return NORMAL_ABNORMAL_MAP.get(value, int(value))

    # แปลเป็น lowercase แล้ว lookup
    normalized = str(value).strip().lower()
    result = NORMAL_ABNORMAL_MAP.get(normalized)

    if result is not None:
        return result

    # ถ้า map ไม่ตรง ลอง partial match
    for keyword, mapped_val in NORMAL_ABNORMAL_MAP.items():
        if isinstance(keyword, str) and keyword in normalized:
            return mapped_val

    print(f"  ⚠️  ไม่สามารถแปลงค่า '{value}' เป็น ปกติ/ผิดปกติ ได้")
    return None


# ======================================================================
# ขั้นตอนที่ 4: TRANSFORM — แปลงค่า
# ======================================================================


def transform_dates(rows: list[dict]) -> list[dict]:
    """
    แปลงวันที่จาก ค.ศ. (YYYY-MM-DD) → พ.ศ. (ปปปป-ดด-วว)
    เช่น 2026-02-15 → 2569-02-15
    """
    for row in rows:
        date_str = row.get("วันที่ตรวจ (ปปปป-ดด-วว)")
        if date_str:
            try:
                dt = datetime.strptime(str(date_str), "%Y-%m-%d")
                buddhist_year = dt.year + 543
                row["วันที่ตรวจ (ปปปป-ดด-วว)"] = f"{buddhist_year}-{dt.month:02d}-{dt.day:02d}"
            except ValueError:
                print(f"  ⚠️  ไม่สามารถแปลงวันที่: '{date_str}'")
    return rows


# ======================================================================
# ขั้นตอนที่ 5: EXPORT — เขียนลง Excel
# ======================================================================


def export_to_excel(rows: list[dict], output_path: str):
    """
    เขียนผลลัพธ์ลง Excel ตาม template format

    Args:
        rows: list ของ dict ที่มี key ตรงกับ TEMPLATE_COLUMNS
        output_path: path ที่จะบันทึกไฟล์ Excel
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Employees"

    # --- Style definitions ---
    header_font = Font(name="Tahoma", bold=True, size=10, color="FFFFFF")
    header_fill = PatternFill(start_color="2E5090", end_color="2E5090", fill_type="solid")
    header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    cell_font = Font(name="Tahoma", size=10)
    cell_alignment = Alignment(horizontal="center", vertical="center")
    thin_border = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )

    # --- Write header row ---
    for col_idx, col_name in enumerate(TEMPLATE_COLUMNS, 1):
        cell = ws.cell(row=1, column=col_idx, value=col_name)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = thin_border

    # --- Write data rows ---
    for row_idx, row_data in enumerate(rows, 2):
        for col_idx, col_name in enumerate(TEMPLATE_COLUMNS, 1):
            value = row_data.get(col_name)
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.font = cell_font
            cell.alignment = cell_alignment
            cell.border = thin_border

    # --- Auto-adjust column widths ---
    for col_idx, col_name in enumerate(TEMPLATE_COLUMNS, 1):
        # ใช้ความยาวของชื่อ header เป็นขั้นต่ำ, จำกัดที่ 25
        width = min(max(len(col_name) + 4, 12), 25)
        ws.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = width

    # --- Freeze header row ---
    ws.freeze_panes = "A2"

    wb.save(output_path)
    print(f"\n✅ บันทึกไฟล์สำเร็จ: {output_path}")
    print(f"   จำนวนข้อมูล: {len(rows)} แถว × {len(TEMPLATE_COLUMNS)} คอลัมน์")


# ======================================================================
# Function หลัก: รัน pipeline ทั้งหมด
# ======================================================================


def run_pipeline(patient_info, lab_results, vital_signs, xray_results, special_exams,
                 output_path: str) -> list[dict]:
    """
    รัน pipeline ทั้งหมด: Load → Map → Pivot → Transform → Export

    Returns:
        list[dict]: ข้อมูลที่แปลงแล้ว (Wide format)
    """
    print("=" * 60)
    print("🏥 HIS → Template Mapping Pipeline")
    print("=" * 60)

    # Step 1: Load
    print("\n📥 Step 1: Load — โหลดข้อมูลจากแหล่งต่างๆ")
    merged = load_all_data(patient_info, lab_results, vital_signs,
                           xray_results, special_exams)
    print(f"   พบข้อมูล {len(merged)} คน")

    # Step 2 & 3: Map + Pivot
    print("\n🔄 Step 2-3: Map + Pivot — แปลชื่อ Lab & รวมเป็น Wide format")
    wide_rows = pivot_to_wide(merged)
    print(f"   แปลงเป็น Wide format สำเร็จ: {len(wide_rows)} แถว")

    # Step 4: Transform
    print("\n🔧 Step 4: Transform — แปลงวันที่ ค.ศ.→พ.ศ.")
    wide_rows = transform_dates(wide_rows)
    print("   แปลงวันที่สำเร็จ")

    # Step 5: Export
    print("\n📤 Step 5: Export — เขียนลง Excel")
    export_to_excel(wide_rows, output_path)

    return wide_rows
