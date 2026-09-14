"""
manage_api_keys.py
==================
API keys for hospital HIS systems (D19, docs/api.md).

    python scripts/manage_api_keys.py create --hospital H01 --name "HIS รพ.ตัวอย่าง"
    python scripts/manage_api_keys.py list
    python scripts/manage_api_keys.py revoke 3

The key is printed once by `create` and never stored; send it to the hospital over a
safe channel. A lost key cannot be recovered: revoke it and create a new one.
On the server, run it inside the app container: docker compose exec app python scripts/...
"""

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
except ImportError:   # inside the container the variables come from docker compose
    pass

from sqlalchemy import func  # noqa: E402

from app.api_keys import create_key  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import ApiKey, Hospital  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create", help="ออก key ใหม่ให้โรงพยาบาล")
    c.add_argument("--hospital", required=True, help="รหัสโรงพยาบาล เช่น H01")
    c.add_argument("--name", required=True, help="ใช้กับระบบไหน เช่น 'HIS รพ.ตัวอย่าง'")
    sub.add_parser("list", help="ดู key ทั้งหมด (ไม่แสดงตัว key)")
    r = sub.add_parser("revoke", help="ยกเลิก key")
    r.add_argument("key_id", type=int)
    a = ap.parse_args()

    with SessionLocal() as db:
        if a.cmd == "create":
            row, key = create_key(db, a.hospital, a.name)
            print(f"สร้าง key #{row.id} ให้ {a.hospital} ({a.name})")
            print(f"\n    {key}\n")
            print("key นี้แสดงครั้งเดียว ระบบเก็บไว้แค่ค่า hash ส่งให้โรงพยาบาลทางช่องทางที่ปลอดภัย")
        elif a.cmd == "list":
            rows = db.query(ApiKey, Hospital.code).join(Hospital, Hospital.id == ApiKey.hospital_id).order_by(ApiKey.id)
            for k, code in rows:
                state = f"ยกเลิกแล้ว {k.revoked_at:%Y-%m-%d}" if k.revoked_at else "ใช้งานได้"
                used = f"{k.last_used_at:%Y-%m-%d %H:%M}" if k.last_used_at else "-"
                print(f"#{k.id:<4} {code:<14} {k.prefix}…  {state:<22} ใช้ล่าสุด {used:<16}  {k.name}")
        elif a.cmd == "revoke":
            k = db.get(ApiKey, a.key_id)
            if k is None:
                sys.exit(f"ไม่พบ key #{a.key_id}")
            k.revoked_at = func.now()
            db.commit()
            print(f"ยกเลิก key #{k.id} ({k.name}) แล้ว มีผลทันที")


if __name__ == "__main__":
    main()
