"""
นำเข้าทะเบียนพนักงาน (D23, step 3.4).

The register is the gate in front of every result: a person who is not in it
has their results held back. So the thing worth testing is not how many rows go
in, but what it refuses to accept and whether it says why.
"""

import os
from datetime import date

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Company, Department, Employee, Hospital, LabMapping
from app.pipeline.reader import Sheet
from app.pipeline.registry import REG_PREFIX, find_header_row, import_registry

BASE_URL = os.environ["DATABASE_URL"].rsplit("/", 1)[0]
DB_URL = f"{BASE_URL}/his_mapping_test_registry"


@pytest.fixture(scope="module")
def engine():
    admin = create_engine(f"{BASE_URL}/postgres", isolation_level="AUTOCOMMIT")
    name = DB_URL.rsplit("/", 1)[1]
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        c.execute(text(f'CREATE DATABASE "{name}"'))
    eng = create_engine(DB_URL)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def world(engine):
    s = sessionmaker(bind=engine)()
    for t in ("employees", "departments", "companies", "hospitals", "lab_mappings"):
        s.execute(text(f"TRUNCATE {t} RESTART IDENTITY CASCADE"))
    h = Hospital(code="H1", name="รพ.ทดสอบ")
    co = Company(juristic_id="0105500000001", name="บริษัททดสอบ", branch_name="")
    s.add_all([h, co])
    s.flush()
    s.add_all([Department(name="ฝ่ายผลิต", company_id=co.id),
               Department(name="คลังสินค้า", company_id=co.id)])
    s.commit()
    yield {"db": s, "hospital_id": h.id, "company_id": co.id}
    s.rollback()
    s.close()


def _sheet(rows, name="Sheet1"):
    return [Sheet(name, rows)]


HEAD = ["เลขบัตรประชาชน", "ชื่อ", "นามสกุล", "แผนก", "เพศ", "ปีเกิด", "ตำแหน่ง", "อายุงาน"]


def _run(world, rows, **kw):
    return import_registry(world["db"], _sheet([HEAD] + rows),
                           world["hospital_id"], world["company_id"], **kw)


def test_a_clean_file_lands(world):
    res = _run(world, [["1101700207366", "สมชาย", "ใจดี", "ฝ่ายผลิต", "ชาย", "2530", "ช่างกลึง", "5.5"]])
    world["db"].flush()

    assert (res.added, len(res.reviews)) == (1, 0)
    p = world["db"].query(Employee).one()
    assert (p.first_name, p.gender, int(p.birth_year), float(p.work_experience)) == \
           ("สมชาย", "male", 2530, 5.5)


def test_a_title_in_the_name_column_is_stripped(world):
    _run(world, [["1101700207366", "นายสมชาย", "ใจดี", "ฝ่ายผลิต", "ชาย", "2530", "ช่างกลึง", "5"]])
    world["db"].flush()
    assert world["db"].query(Employee).one().first_name == "สมชาย"


def test_a_year_written_in_ce_is_converted_not_rejected(world):
    _run(world, [["1101700207366", "สมชาย", "ใจดี", "ฝ่ายผลิต", "ชาย", "1987", "ช่างกลึง", "5"]])
    world["db"].flush()
    assert int(world["db"].query(Employee).one().birth_year) == 2530


def test_a_bad_cid_stops_that_row_and_says_so(world):
    res = _run(world, [["1101700207360", "สมชาย", "ใจดี", "ฝ่ายผลิต", "ชาย", "2530", "ช่างกลึง", "5"]])
    world["db"].flush()

    assert world["db"].query(Employee).count() == 0
    assert [r["kind"] for r in res.reviews] == ["cid"]
    assert "checksum" in res.reviews[0]["payload"]["reason"]


def test_a_department_that_does_not_exist_is_never_created(world):
    """A department is an organisational unit owned by the workplace. Creating one
    from a spelling in a file would invent it."""
    res = _run(world, [["1101700207366", "สมชาย", "ใจดี", "ฝ่ายที่ไม่มีจริง", "ชาย", "2530", "ช่าง", "5"]])
    world["db"].flush()

    assert world["db"].query(Employee).count() == 0
    assert world["db"].query(Department).count() == 2          # unchanged
    r = res.reviews[0]
    assert r["kind"] == "department_change"
    assert r["payload"]["department_in_file"] == "ฝ่ายที่ไม่มีจริง"
    assert r["payload"]["known_departments"] == ["คลังสินค้า", "ฝ่ายผลิต"]


def test_an_unknown_gender_is_asked_not_forced(world):
    """The department's column is an enum of exactly male/female."""
    res = _run(world, [["1101700207366", "สมชาย", "ใจดี", "ฝ่ายผลิต", "ไม่ระบุ", "2530", "ช่าง", "5"]])
    world["db"].flush()

    p = world["db"].query(Employee).one()
    assert p.gender is None                      # the row still lands; the field waits
    assert [r["payload"]["column"] for r in res.reviews if r["kind"] == "value"] == ["gender"]


def test_an_unknown_header_becomes_a_question(world):
    rows = [HEAD + ["รหัสพนักงานภายใน"],
            ["1101700207366", "สมชาย", "ใจดี", "ฝ่ายผลิต", "ชาย", "2530", "ช่าง", "5", "EMP-01"]]
    res = import_registry(world["db"], _sheet(rows), world["hospital_id"], world["company_id"])
    world["db"].flush()

    asked = [r for r in res.reviews if r["kind"] == "mapping"]
    assert len(asked) == 1
    assert asked[0]["payload"]["label"] == "รหัสพนักงานภายใน"
    assert asked[0]["payload"]["field_set"] == "registry"
    assert world["db"].query(Employee).count() == 1     # the rest of the row still lands


def test_a_learned_header_needs_no_second_answer(world):
    db = world["db"]
    db.add(LabMapping(hospital_id=world["hospital_id"], source_name="รหัสพนักงานภายใน",
                      target_column=f"{REG_PREFIX}position", origin="human"))
    db.flush()
    rows = [["เลขบัตรประชาชน", "ชื่อ", "นามสกุล", "แผนก", "รหัสพนักงานภายใน"],
            ["1101700207366", "สมชาย", "ใจดี", "ฝ่ายผลิต", "ช่างเชื่อม"]]
    res = import_registry(db, _sheet(rows), world["hospital_id"], world["company_id"])
    db.flush()

    assert [r for r in res.reviews if r["kind"] == "mapping"] == []
    assert db.query(Employee).one().position == "ช่างเชื่อม"


def test_a_changed_value_keeps_the_register_and_asks(world):
    _run(world, [["1101700207366", "สมชาย", "ใจดี", "ฝ่ายผลิต", "ชาย", "2530", "ช่างกลึง", "5"]])
    world["db"].flush()
    res = _run(world, [["1101700207366", "สมชาย", "ใจดี", "ฝ่ายผลิต", "ชาย", "2530", "หัวหน้ากะ", "5"]])
    world["db"].flush()

    assert world["db"].query(Employee).one().position == "ช่างกลึง"   # the stored value stands
    asked = [r for r in res.reviews if r["payload"].get("column") == "position"]
    assert len(asked) == 1
    assert asked[0]["payload"]["current"] == "ช่างกลึง"


def test_the_same_file_twice_changes_nothing(world):
    row = [["1101700207366", "สมชาย", "ใจดี", "ฝ่ายผลิต", "ชาย", "2530", "ช่างกลึง", "5"]]
    _run(world, row)
    world["db"].flush()
    res = _run(world, row)
    world["db"].flush()
    assert (res.added, res.unchanged, len(res.reviews)) == (0, 1, 0)


def test_the_same_person_in_two_departments_is_two_rows(world):
    """The department keys people by (citizen_id, department_id), so this is their
    design, not an accident of ours."""
    _run(world, [["1101700207366", "สมชาย", "ใจดี", "ฝ่ายผลิต", "ชาย", "2530", "ช่าง", "5"],
                 ["1101700207366", "สมชาย", "ใจดี", "คลังสินค้า", "ชาย", "2530", "ช่าง", "5"]])
    world["db"].flush()
    assert world["db"].query(Employee).count() == 2


def test_a_file_with_no_recognisable_header_is_refused(world):
    res = import_registry(world["db"], _sheet([["ก", "ข"], ["1", "2"]]),
                          world["hospital_id"], world["company_id"])
    assert res.rows_read == 0
    assert res.reviews[0]["kind"] == "profile"


def test_the_header_row_is_found_below_a_title(world):
    rows = [["ทะเบียนพนักงาน บริษัททดสอบ ประจำปี 2569"], [], HEAD,
            ["1101700207366", "สมชาย", "ใจดี", "ฝ่ายผลิต", "ชาย", "2530", "ช่าง", "5"]]
    assert find_header_row(rows) == 2
    res = import_registry(world["db"], _sheet(rows), world["hospital_id"], world["company_id"])
    world["db"].flush()
    assert res.added == 1
