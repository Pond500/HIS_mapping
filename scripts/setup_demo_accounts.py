"""
setup_demo_accounts.py
======================
One account per demo set (การรายงานผลตรวจสุขภาพ/เดโม1_… to เดโม5_…), each with its
own hospital and its own company, ready to search for and start.

Why one hospital each: what the system learns (column meanings, units, the meaning
of a finding's text) is remembered per hospital. On a shared hospital, the set run
first would answer the questions a later set is meant to show.

Safe to run again: existing hospitals, accounts and companies are kept, and only
what is missing is created. scripts/reset_demo.py deletes every company, so run
this again after a reset. Passwords are printed once, for new accounts only; pass
--reset-passwords to issue new ones for all five.

    python scripts/setup_demo_accounts.py
    python scripts/setup_demo_accounts.py --reset-passwords
"""

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
except ImportError:
    pass

from app import auth  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import AppUser, Company, Department  # noqa: E402
from app.pipeline.run import get_or_create_hospital  # noqa: E402

# n, theme (the set's folder), company name, juristic id, departments
SETS = [
    (1, "ไฟล์หน้าตาไหนก็ได้", "บริษัท เดโมหนึ่ง จำกัด", "0105569000101", ["ผลิต1"]),
    (2, "หน่วยและสเกล", "บริษัท เดโมสอง จำกัด", "0105569000201", ["ผลิต1"]),
    (3, "คนและแผนกไม่ตรงทะเบียน", "บริษัท เดโมสาม จำกัด", "0105569000301", ["ผลิต1", "คลัง"]),
    (4, "ข้อมูลขัดแย้งและค่าแปลก", "บริษัท เดโมสี่ จำกัด", "0105569000401", ["ผลิต1"]),
    (5, "ข้อความผลตรวจจากแพทย์", "บริษัท เดโมห้า จำกัด", "0105569000501", ["ผลิต1"]),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reset-passwords", action="store_true")
    a = ap.parse_args()
    out = []
    with SessionLocal() as db:
        for n, theme, company_name, juristic_id, departments in SETS:
            h = get_or_create_hospital(db, f"DEMO{n}")
            h.name = f"หน่วยบริการเดโม {n} ({theme})"

            username = f"demo{n}"
            user = db.query(AppUser).filter(AppUser.username == username).one_or_none()
            password = None
            if user is None:
                password = auth.new_password()
                user = AppUser(username=username, name=f"เดโม {n}", surname=theme,
                               email=f"demo{n}@example.com", password_hash=auth.hash_password(password),
                               role="staff", hospital_id=h.id, created_by="scripts/setup_demo_accounts.py")
                db.add(user)
            else:
                user.hospital_id, user.is_active = h.id, True
                if a.reset_passwords:
                    password = auth.new_password()
                    user.password_hash = auth.hash_password(password)

            company = (db.query(Company).filter(Company.juristic_id == juristic_id, Company.branch_name == "")
                       .one_or_none())
            if company is None:
                company = Company(juristic_id=juristic_id, name=company_name, branch_name="",
                                  address="กรุงเทพมหานคร", industry_group="การผลิต")
                db.add(company)
                db.flush()
            have = {d.name for d in db.query(Department).filter(Department.company_id == company.id)}
            for d in departments:
                if d not in have:
                    db.add(Department(company_id=company.id, name=d))
            out.append((n, username, password, h.code, company_name, ", ".join(departments), theme))
        db.commit()

    print(f"{'ชุด':<4}{'username':<10}{'password':<14}{'หน่วยบริการ':<12}บริษัท (แผนก)")
    for n, username, password, code, company_name, departments, theme in out:
        print(f"{n:<4}{username:<10}{password or '(เดิม)':<14}{code:<12}{company_name} ({departments}) · {theme}")
    if any(o[2] for o in out):
        print("\nรหัสผ่านแสดงครั้งเดียว ระบบเก็บไว้แค่ค่า hash")


if __name__ == "__main__":
    main()
