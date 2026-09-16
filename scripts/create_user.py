"""
create_user.py
==============
The first account for the staff web pages (afterwards use จัดการผู้ใช้งาน in the app).

    python scripts/create_user.py --role superadmin --email you@example.com --name "ชื่อ" --surname "นามสกุล"
    python scripts/create_user.py --role admin --hospital H01 --email admin@example.com --name แอดมิน
    python scripts/create_user.py --username admin-1 --reset-password     # new password for an account

The password is printed once and stored only as a PBKDF2 hash.
On the server: docker compose exec app python scripts/create_user.py ...
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

from sqlalchemy import func  # noqa: E402

from app import auth  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import AppUser  # noqa: E402
from app.pipeline.run import get_or_create_hospital  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--role", choices=list(auth.RANK), default="superadmin")
    ap.add_argument("--email")
    ap.add_argument("--name", default="")
    ap.add_argument("--surname", default="")
    ap.add_argument("--hospital", help="รหัสหน่วยบริการ เช่น H01 (ไม่ต้องใส่สำหรับ superadmin)")
    ap.add_argument("--username", help="ใช้กับ --reset-password")
    ap.add_argument("--reset-password", action="store_true")
    a = ap.parse_args()

    with SessionLocal() as db:
        if a.reset_password:
            if not a.username:
                sys.exit("ต้องระบุ --username")
            row = db.query(AppUser).filter(AppUser.username == a.username).one_or_none()
            if row is None:
                sys.exit(f"ไม่พบผู้ใช้ {a.username}")
            password = auth.new_password()
            row.password_hash = auth.hash_password(password)
            row.is_active = True
            db.commit()
            print(f"ตั้งรหัสผ่านใหม่ให้ {row.username} แล้ว\n\n    {password}\n")
            return

        if not a.email:
            sys.exit("ต้องระบุ --email")
        hospital_id = get_or_create_hospital(db, a.hospital).id if a.hospital else None
        if a.role != "superadmin" and hospital_id is None:
            sys.exit("สิทธิ์นี้ต้องระบุ --hospital")
        n = db.query(func.count(AppUser.id)).scalar() + 1
        prefix = "doctor" if a.role == "doctor" else ("staff" if a.role == "staff" else "admin")
        username = f"{prefix}-{n}"
        while db.query(AppUser).filter(AppUser.username == username).count():
            n += 1
            username = f"{prefix}-{n}"
        password = auth.new_password()
        db.add(AppUser(username=username, name=a.name or username, surname=a.surname, email=a.email,
                       password_hash=auth.hash_password(password), role=a.role, hospital_id=hospital_id,
                       created_by="scripts/create_user.py"))
        db.commit()
        print(f"สร้างผู้ใช้ {username} ({auth.ROLE_TH[a.role]}) แล้ว")
        print(f"\n    username: {username}\n    password: {password}\n")
        print("รหัสผ่านแสดงครั้งเดียว ระบบเก็บไว้แค่ค่า hash")


if __name__ == "__main__":
    main()
