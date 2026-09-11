"""
main.py
=======
Entry point — รัน Pipeline ทั้งหมด: HIS → Template

วิธีใช้:
    python3 main.py

Output:
    output_result.xlsx (ในโฟลเดอร์เดียวกัน)
"""

import os

from his_to_template import run_pipeline
from sample_his_data import (
    get_lab_results,
    get_patient_info,
    get_special_exams,
    get_vital_signs,
    get_xray_results,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "output_result.xlsx")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    """
    จำลองการดึงข้อมูลจาก HIS แล้วแปลงเป็น template

    ในการใช้งานจริง:
      - แทนที่ get_* functions ด้วยการ query จาก HIS database จริง
      - หรืออ่านจากไฟล์ CSV/Excel ที่ export จาก HIS
    """

    # ---- ดึงข้อมูลจาก HIS (ใช้ sample data) ----
    patient_info = get_patient_info()
    lab_results = get_lab_results()
    vital_signs = get_vital_signs()
    xray_results = get_xray_results()
    special_exams = get_special_exams()

    print(f"📊 ข้อมูลที่โหลด:")
    print(f"   - Patient info:  {len(patient_info)} คน")
    print(f"   - Lab results:   {len(lab_results)} รายการ")
    print(f"   - Vital signs:   {len(vital_signs)} รายการ")
    print(f"   - X-ray results: {len(xray_results)} รายการ")
    print(f"   - Special exams: {len(special_exams)} รายการ")

    # ---- รัน Pipeline ----
    result_rows = run_pipeline(
        patient_info=patient_info,
        lab_results=lab_results,
        vital_signs=vital_signs,
        xray_results=xray_results,
        special_exams=special_exams,
        output_path=OUTPUT_FILE,
    )

    # ---- แสดงตัวอย่างผลลัพธ์ ----
    print("\n" + "=" * 60)
    print("📋 ตัวอย่างผลลัพธ์ (3 คนแรก):")
    print("=" * 60)

    for i, row in enumerate(result_rows[:3], 1):
        print(f"\n--- คนที่ {i} ---")
        print(f"  เลขบัตรฯ:  {row['เลขบัตรประชาชน']}")
        print(f"  ชื่อ-สกุล: {row['ชื่อ']} {row['นามสกุล']}")
        print(f"  วันที่:    {row['วันที่ตรวจ (ปปปป-ดด-วว)']}")
        print(f"  WBC:       {row['wbc']}")
        print(f"  Hb:        {row['hb']}")
        print(f"  Cr:        {row['creatinine']}")
        print(f"  AST:       {row['sgot_ast']}")
        print(f"  X-ray:     {row['chest_xray']} (1=ปกติ, 2=ผิดปกติ)")
        print(f"  EKG:       {row['ekg']} (1=ปกติ, 2=ผิดปกติ)")
        print(f"  Hearing:   {row['hearing_ability']} (1=ปกติ, 2=ผิดปกติ)")
        print(f"  Vision:    {row['far_vision_test']} (1=เหมาะสม, 2=อาจไม่เหมาะสม)")

    print(f"\n🎉 เสร็จสมบูรณ์! ไฟล์ output: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
