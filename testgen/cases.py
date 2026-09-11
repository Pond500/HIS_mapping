"""
cases.py
========
Test cases. A case is one or more uploads (in order) into an empty system.
Each upload renders a group of records ("A", "B", ...) from one hospital
in one Style. "modify" changes n values of an earlier upload's records, to
simulate a corrected re-submission (expected: conflicts, no silent overwrite).

DEV cases are for tuning. EXAM cases are generated from the held-out
vocabulary pools and are only used for reported numbers.
"""

from dataclasses import dataclass, field

from testgen.render import Style as S

# identity headers as a HOSxP-style export names them (the old code knows these)
HOSXP = {"cid": "cid", "first_name": "fname", "last_name": "lname", "department_id": "department_id",
         "visit_date": "vstdate", "lab_name": "lab_name", "result": "result", "unit": "unit"}


@dataclass
class Upload:
    hospital: str
    style: S
    records: str = "A"          # which record group to render
    filename: str = "file.xlsx"
    modify: int = 0             # corrupt n values of the group (re-submission with changes)
    same_layout_as: int | None = None  # reuse the label/unit choices of an earlier upload index


@dataclass
class Case:
    name: str
    desc: str
    uploads: list[Upload]
    n: int = 40                 # records per group
    groups: list[str] = field(default_factory=lambda: ["A"])


DEV = [
    Case("d01_long_basic", "Long แบบ HOSxP ชื่อ lab ที่ระบบรู้จัก วันที่ ISO (ควรผ่านเองเกือบทั้งหมด)",
         [Upload("H01", S(layout="long", labels="known", id_headers=HOSXP), filename="lab_export.xlsx")]),
    Case("d02_long_thai_preamble", "Long หัวไทย มีหัวรายงาน 3 แถว วันที่ dd/mm/พ.ศ. คอลัมน์หน่วย ชื่อ lab ไทย Hb เป็น g/L",
         [Upload("H02", S(layout="long", labels="novel", unit_mode="column", alt_units=True,
                          date_fmt="dmy_be", preamble=3), filename="ผลตรวจสุขภาพ.xlsx")]),
    Case("d03_wide_template", "Wide ตรง template อยู่แล้ว (กลุ่มควบคุม)",
         [Upload("H03", S(layout="wide", labels="template", date_fmt="ymd_be"), filename="template_filled.xlsx")]),
    Case("d04_wide_codes_units_in_header", "Wide ชื่อคอลัมน์ของ รพ.เอง หน่วยในหัวคอลัมน์ ตัวเลขมีคอมมา",
         [Upload("H04", S(layout="wide", labels="mixed", unit_mode="header", value_noise=True),
                 filename="checkup_2026.xlsx")]),
    Case("d05_wide_group_header", "Wide หัวคอลัมน์ 2 ชั้น (กลุ่ม merged + ชื่อ) และแถวหน่วย",
         [Upload("H05", S(layout="wide", labels="known", group_header=True, unit_mode="row", preamble=2),
                 filename="annual_report.xlsx")]),
    Case("d06_multisheet", "หลาย sheet แยก CBC / Chemistry / PE ความดันรวมเป็น 120/80",
         [Upload("H06", S(layout="wide", labels="mixed", split_sheets=True, bp_combined=True),
                 filename="multi_sheet.xlsx")]),
    Case("d07_csv_cp874", "CSV encoding TIS-620 (cp874) หัวไทย Wide",
         [Upload("H07", S(layout="wide", labels="novel", fmt="csv", encoding="cp874", date_fmt="dmy_be"),
                 filename="export_tis620.csv")]),
    Case("d08_extras_traps", "มีผลตรวจนอก template และกับดัก (RBC, Indirect Bilirubin, Neut#)",
         [Upload("H08", S(layout="long", labels="mixed", extras=True, unit_mode="column"),
                 filename="lab_with_extras.xlsx")]),
    Case("d09_categorical_text", "ผล X-ray/EKG/การได้ยิน/สายตา เป็นข้อความ ปกติ/Normal/Abnormal",
         [Upload("H09", S(layout="wide", labels="known", columns="pe", categorical="text"),
                 filename="pe_results.xlsx")]),
    Case("d10_comment_only", "มีแต่ข้อความ comment ไม่มีช่อง 1/2 (ต้องจัดประเภทจากข้อความ)",
         [Upload("H10", S(layout="wide", labels="known", columns="pe", categorical="comment_only"),
                 filename="pe_comments.xlsx")]),
    Case("d11_bad_cids", "เลขบัตรหลายรูปแบบ (float/ขีด/เว้นวรรค) และเลขบัตร checksum ผิด 10%",
         [Upload("H11", S(layout="long", labels="known", cid_fmt="mixed", bad_cid_rate=0.1),
                 filename="cid_messy.xlsx")]),
    Case("d12_dates_mixed", "วันที่ปนกันหลายรูปแบบ รวมชื่อเดือนไทยและ Excel date",
         [Upload("H12", S(layout="long", labels="known", date_fmt="mixed"), filename="dates_mixed.xlsx"),
          Upload("H12b", S(layout="wide", labels="known", date_fmt="excel"), records="B",
                 filename="dates_excel.xlsx")], groups=["A", "B"]),
    Case("d13_value_noise_noise_cols", "ค่ามี N/A, -, <0.1, ช่องว่าง และคอลัมน์ขยะ HN/VN/Ward",
         [Upload("H13", S(layout="long", labels="known", value_noise=True, noise_cols=True),
                 filename="noisy.xlsx")]),
    Case("d14_conflict_resubmit", "ส่งไฟล์แก้ไขซ้ำ: ค่าเหมือนเดิมต้องข้าม ค่าที่ต่างต้องเป็นข้อมูลขัดแย้ง",
         [Upload("H14", S(layout="long", labels="known", id_headers=HOSXP), filename="batch1.xlsx"),
          Upload("H14", S(layout="long", labels="known", id_headers=HOSXP), filename="batch1_corrected.xlsx",
                 modify=6, same_layout_as=0)]),
    Case("d15_repeat_hospital", "รพ.เดิมส่งรอบสอง รูปแบบเดิม คนใหม่ (รอบสองควรไม่ต้องถามคน)",
         [Upload("H15", S(layout="long", labels="novel", unit_mode="column", date_fmt="dmy_be"),
                 filename="round1.xlsx"),
          Upload("H15", S(layout="long", labels="novel", unit_mode="column", date_fmt="dmy_be"),
                 records="B", filename="round2.xlsx", same_layout_as=0)], groups=["A", "B"]),
    Case("d16_tb_collision", "TB = Total Bilirubin ที่ รพ.หนึ่ง แต่ = ผลตรวจวัณโรคที่อีก รพ.",
         [Upload("H16A", S(layout="long", labels="known", columns="lab", label_overrides={"tb": "TB"}),
                 filename="hospital_a.xlsx"),
          Upload("H16B", S(layout="long", labels="known", columns="lab", tb_is_tuberculosis=True),
                 records="B", filename="hospital_b.xlsx")], groups=["A", "B"]),
    Case("d17_transposed", "รายงานแนวตั้ง: รายการตรวจเป็นแถว คนเป็นคอลัมน์",
         [Upload("H17", S(layout="transposed", labels="mixed", preamble=2), filename="report_vertical.xlsx")],
         n=12),
    Case("d18_alt_units_no_unit", "หน่วยไม่มาตรฐานและไม่บอกหน่วย (ต้องสังเกตจากช่วงค่า)",
         [Upload("H18", S(layout="wide", labels="known", columns="lab", alt_units=True, unit_mode="none"),
                 filename="units_hidden.csv", ) ]),
]
# d18 is a csv: set its format explicitly
DEV[-1].uploads[0].style.fmt = "csv"


EXAM = [
    Case("e01_long_thai_units", "Long หัวไทยชุดสอบ หน่วยไม่มาตรฐาน พ.ศ. ชื่อเดือนไทย",
         [Upload("X01", S(layout="long", labels="novel", unit_mode="column", alt_units=True,
                          date_fmt="thai_month_be", preamble=2), filename="รายงานผลแล็บ.xlsx")]),
    Case("e02_wide_semicolon_csv", "CSV คั่นด้วย ; UTF-8 BOM Wide ชื่อผสม หน่วยในหัวคอลัมน์",
         [Upload("X02", S(layout="wide", labels="mixed", unit_mode="header", fmt="csv", encoding="utf-8-sig",
                          delimiter=";", value_noise=True), filename="export.csv")]),
    Case("e03_multisheet_long", "หลาย sheet แบบ Long มีคอลัมน์ขยะ ชื่อ-สกุลคอลัมน์เดียว",
         [Upload("X03", S(layout="long", labels="novel", split_sheets=True, noise_cols=True, full_name=True,
                          date_fmt="dmy_be2"), filename="his_dump.xlsx")]),
    Case("e04_transposed_units", "รายงานแนวตั้งพร้อมหน่วยไม่มาตรฐาน",
         [Upload("X04", S(layout="transposed", labels="novel", alt_units=True, preamble=3),
                 filename="vertical.xlsx")], n=10),
    Case("e05_extras_traps", "ผลนอก template และกับดักชุดสอบ (MCV, ANC, Bilirubin indirect)",
         [Upload("X05", S(layout="wide", labels="mixed", extras=True, group_header=True),
                 filename="extended_panel.xlsx")]),
    Case("e06_comment_text", "ผลตรวจร่างกายเป็นข้อความชุดสอบ + comment อย่างเดียวบางส่วน",
         [Upload("X06", S(layout="long", labels="novel", columns="pe", categorical="text", bp_combined=True),
                 filename="pe_text.xlsx"),
          Upload("X06b", S(layout="wide", labels="novel", columns="pe", categorical="comment_only"),
                 records="B", filename="pe_comment_only.xlsx")], groups=["A", "B"]),
    Case("e07_conflict_bad_cid", "ส่งซ้ำพร้อมแก้ค่า + เลขบัตรผิด + tab-delimited",
         [Upload("X07", S(layout="wide", labels="known", fmt="csv", delimiter="\t", cid_fmt="float",
                          bad_cid_rate=0.08), filename="first.tsv.csv"),
          Upload("X07", S(layout="wide", labels="known", fmt="csv", delimiter="\t", cid_fmt="float"),
                 filename="second.tsv.csv", modify=5, same_layout_as=0)]),
    Case("e08_subset_mixed_everything", "คอลัมน์บางส่วน วันที่ปน ค่าขยะ หน่วยในค่า",
         [Upload("X08", S(layout="long", labels="mixed", columns="subset", date_fmt="mixed",
                          unit_mode="inline", value_noise=True), filename="mixed.xlsx")]),
    Case("e09_repeat_hospital", "รพ.เดิมส่งรอบสอง รูปแบบเดิม คนใหม่ (วัดเป้าทำเองได้ ≥ 95%)",
         [Upload("X09", S(layout="wide", labels="novel", unit_mode="header", alt_units=True, preamble=1,
                          date_fmt="dmy_be"), filename="lot1.xlsx"),
          Upload("X09", S(layout="wide", labels="novel", unit_mode="header", alt_units=True, preamble=1,
                          date_fmt="dmy_be"), records="B", filename="lot2.xlsx", same_layout_as=0)],
         groups=["A", "B"]),
]
