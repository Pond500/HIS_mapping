"""
Runs the scenario suite against a scratch database.

    python -m scenarios.run                 every case
    python -m scenarios.run R03 L07         only these
    python -m scenarios.run --export DIR    also write every input file, per case, to DIR
    python -m scenarios.run --list          the cases and what each one checks

Exit status is non-zero if any case fails, so it can gate a change.
"""

import argparse
import sys
import time
import traceback

from scenarios.harness import Harness, Scenario


README_HEAD = """# ชุดไฟล์ทดสอบ — ทุกสถานการณ์

ไฟล์ในแต่ละโฟลเดอร์คือไฟล์ที่เคสนั้นอัปเข้าระบบ **เรียงตามลำดับเลขหน้าไฟล์** (01, 02, ...)
ชื่อไฟล์บอกว่าเป็นไฟล์ทะเบียนหรือไฟล์ผลตรวจ

## ตั้งค่าก่อนลองมือ (ทำครั้งเดียว)

1. ทะเบียนสถานประกอบการ: สร้างบริษัท 1 แห่ง เพิ่มแผนก **ผลิต** และ **คลัง**
2. การสำรวจ Walk Through + รอบตรวจสุขภาพ (ประเภท "ตรวจสุขภาพตามระยะเวลา/ประจำปี") 1 รอบ
3. เลือกหน่วยบริการ **UNSPECIFIED** ทุกครั้งที่อัป (ถ้าเข้าด้วย admin-1)
4. แต่ละเคสที่มีไฟล์ทะเบียน ให้อัปไฟล์ทะเบียนก่อน แล้วค่อยอัปไฟล์ผลตรวจตามลำดับเลข
5. **ล้างรอบ/ทะเบียนก่อนเคสถัดไป** หรือสร้างบริษัทใหม่ต่อเคส เพราะหลายเคสใช้เลขบัตรชุดเดียวกัน
   (เลขบัตรทดสอบขึ้นต้น 1000000000... ผ่าน checksum ทุกตัว)

ทุกเคสรันอัตโนมัติได้ด้วย `python -m scenarios.run` (ฐานข้อมูลทดสอบแยก ไม่แตะข้อมูลจริง)
ตารางด้านล่างคือสิ่งที่แต่ละเคสตรวจ และผลที่ต้องเห็น

"""


def write_readme(folder, chosen):
    import os
    lines = [README_HEAD, "| เคส | สถานการณ์ | ทำอะไร → ผลที่ต้องเห็น |", "|---|---|---|"]
    for c in chosen:
        doc = " ".join(c["doc"].split()) or "-"
        lines.append(f"| {c['id']} | {c['title']} | {doc} |")
    with open(os.path.join(folder, "README.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("only", nargs="*")
    ap.add_argument("--export")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()

    import os
    if a.export:
        os.makedirs(a.export, exist_ok=True)
    h = Harness(export_dir=a.export)
    from scenarios import cases                      # registers the cases; needs no app import
    chosen = [c for c in cases.CASES if not a.only or c["id"] in a.only or
              any(c["id"].startswith(o) and o.endswith("*") is False and len(o) == 1 for o in a.only)]
    if a.list:
        for c in chosen:
            print(f'{c["id"]:5} {c["title"]}')
        return 0

    h.build_database()
    h.boot()
    passed, failed = [], []
    t0 = time.time()
    for c in chosen:
        h.reset()
        h.current_case = c["id"]
        s = Scenario(h, world=c["world"])
        t = time.time()
        try:
            c["fn"](s)
            passed.append(c["id"])
            print(f'  PASS {c["id"]:5} {c["title"]}  ({time.time() - t:.1f}s)')
        except Exception as e:                        # a failed assert and a crash both count
            failed.append((c, e))
            print(f'  FAIL {c["id"]:5} {c["title"]}')
            msg = "".join(traceback.format_exception_only(type(e), e)).strip()
            print("       " + msg.replace("\n", "\n       "))
            if a.verbose:
                traceback.print_exc()
    print(f"\n{len(passed)} passed, {len(failed)} failed  ({time.time() - t0:.0f}s)")
    if a.export:
        write_readme(a.export, chosen)
        print(f"files written to {a.export}")
    h.cleanup()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
