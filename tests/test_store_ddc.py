"""
The storage path, which nothing covered before (D23).

Until now the only thing exercising store.py was evaluation/, and that is paused
while the schema moves. These tests stand in for it on the part that matters
most: that a value either lands in the department's form, correctly converted,
or becomes a question for a human — and never quietly goes missing.
"""

import os
from datetime import date

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import (
    CheckupBatch, CheckupType, Company, Conflict, Department, Employee,
    EmployeeCheckup, Hospital, PendingReview, SourceFile, ValueProvenance,
    WalkthroughSurvey,
)
from app.pipeline.extract import Extraction
from app.pipeline.store import save

# Its own database, never the dev one: these tests truncate everything they touch.
# Credentials come from DATABASE_URL so there is nothing to keep in step by hand.
BASE_URL = os.environ["DATABASE_URL"].rsplit("/", 1)[0]
DB_URL = f"{BASE_URL}/his_mapping_test_store"


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
def db(engine):
    s = sessionmaker(bind=engine)()
    for t in ("value_provenance", "conflicts", "extra_results", "employee_checkups",
              "pending_reviews", "employees", "employee_checkup_batches",
              "walkthrough_surveys", "departments", "companies", "source_files",
              "hospitals", "employee_checkup_types"):
        s.execute(text(f"TRUNCATE {t} RESTART IDENTITY CASCADE"))
    s.commit()
    yield s
    s.rollback()
    s.close()


@pytest.fixture
def world(db):
    """A workplace with one department, one round, and one registered person."""
    h = Hospital(code="H1", name="รพ.ทดสอบ")
    co = Company(juristic_id="0105500000001", name="บริษัททดสอบ", branch_name="")
    t = CheckupType(id=2, name="ตรวจสุขภาพตามระยะเวลา/ประจำปี")
    db.add_all([h, co, t])
    db.flush()
    dept = Department(name="ฝ่ายผลิต", company_id=co.id)
    other = Department(name="คลังสินค้า", company_id=co.id)
    survey = WalkthroughSurvey(company_id=co.id, survey_date=date(2026, 1, 5))
    db.add_all([dept, other, survey])
    db.flush()
    batch = CheckupBatch(checkup_type=t.id, appoint_date=date(2026, 3, 1),
                         survey_id=survey.id, hospital_id=h.id)
    db.add(batch)
    db.flush()
    person = Employee(cid="1101700207364", first_name="สมชาย", last_name="ใจดี",
                      department_pk=dept.id)
    db.add(person)
    db.flush()
    sf = SourceFile(hospital_id=h.id, filename="f.csv", file_type="csv", sha256="a" * 64,
                    stored_path="/tmp/f.csv", checkup_batch_id=batch.id, field_set="result")
    db.add(sf)
    db.flush()
    return {"db": db, "sf": sf, "batch": batch, "person": person,
            "dept": dept, "other": other, "company": co}


def _ex(cid, cells, person=None):
    ex = Extraction()
    ex.rows[(cid, "2026-03-01")] = {
        "person": person or {},
        "cells": {c: (v, {"sheet": "Sheet1", "cell": "A1", "raw_value": str(v)})
                  for c, v in cells.items()},
    }
    return ex


def test_values_land_in_the_departments_units(world):
    db, sf = world["db"], world["sf"]
    stats = save(db, sf, _ex("1101700207364", {"wbc": 8383, "plt": 210186, "hb": 14.2}))
    db.flush()

    c = db.query(EmployeeCheckup).one()
    assert stats["stored"] == 3
    # 10^3/uL, not cells/µL — and no binary floating point tail
    assert str(c.wbc) == "8.38"          # Numeric(10, 2)
    assert str(c.plt) == "210.19"
    assert str(c.hb) == "14.20"          # untouched: same unit either side


def test_categorical_becomes_zero_based(world):
    db, sf = world["db"], world["sf"]
    save(db, sf, _ex("1101700207364", {"chest_xray": 1, "ekg": 2}))
    db.flush()
    c = db.query(EmployeeCheckup).one()
    assert (c.chest_xray, c.ekg) == (0, 1)     # 1=ปกติ -> 0, 2=ผิดปกติ -> 1


def test_the_raw_value_survives_the_conversion(world):
    """The whole 0/1-vs-1/2 question rests on being able to undo this later."""
    db, sf = world["db"], world["sf"]
    save(db, sf, _ex("1101700207364", {"wbc": 8383}))
    db.flush()
    p = db.query(ValueProvenance).one()
    assert p.raw_value == "8383"               # what the file said, not what we stored


def test_an_unregistered_person_blocks_and_asks(world):
    db, sf = world["db"], world["sf"]
    stats = save(db, sf, _ex("1409901234123", {"wbc": 8383}, {"first_name": "สมหญิง"}))
    db.flush()

    assert db.query(EmployeeCheckup).count() == 0      # nothing written
    assert stats["unregistered"] == 1
    r = db.query(PendingReview).filter_by(kind="unregistered_person").one()
    assert r.payload["cid"] == "1409901234123"
    assert r.payload["values_waiting"] == 1            # the human can see what is held up


def test_a_different_department_becomes_a_question_not_a_guess(world):
    db, sf = world["db"], world["sf"]
    stats = save(db, sf, _ex("1101700207364", {"wbc": 8383},
                             {"department_id": "คลังสินค้า"}))
    db.flush()

    assert db.query(EmployeeCheckup).count() == 0
    assert stats["department_change"] == 1
    r = db.query(PendingReview).filter_by(kind="department_change").one()
    assert r.payload["department_in_register"] == "ฝ่ายผลิต"
    assert r.payload["department_in_file"] == "คลังสินค้า"


def test_the_same_value_again_is_not_a_conflict(world):
    db, sf = world["db"], world["sf"]
    save(db, sf, _ex("1101700207364", {"wbc": 8383}))
    db.flush()
    stats = save(db, sf, _ex("1101700207364", {"wbc": 8383}))
    db.flush()
    assert stats["skipped_same"] == 1
    assert db.query(Conflict).count() == 0


def test_a_different_value_keeps_the_first_and_opens_a_conflict(world):
    db, sf = world["db"], world["sf"]
    save(db, sf, _ex("1101700207364", {"wbc": 8383}))
    db.flush()
    save(db, sf, _ex("1101700207364", {"wbc": 9100}))
    db.flush()

    assert str(db.query(EmployeeCheckup).one().wbc) == "8.38"   # first value stands
    c = db.query(Conflict).one()
    assert (c.current_value, c.incoming_value, c.status) == ("8.38", "9.1", "open")


def test_a_second_round_is_a_new_row_not_a_conflict(world):
    """The old schema keyed on (cid, visit_date), so this case never arose. Under
    the department's keys a later round must not look like a disagreement."""
    db, sf, batch = world["db"], world["sf"], world["batch"]
    save(db, sf, _ex("1101700207364", {"wbc": 8383}))
    db.flush()

    later = CheckupBatch(checkup_type=batch.checkup_type, appoint_date=date(2026, 9, 1),
                         survey_id=batch.survey_id, hospital_id=batch.hospital_id)
    db.add(later)
    db.flush()
    sf.checkup_batch_id = later.id
    save(db, sf, _ex("1101700207364", {"wbc": 9100}))
    db.flush()

    assert db.query(EmployeeCheckup).count() == 2
    assert db.query(Conflict).count() == 0


def test_a_results_file_without_a_round_is_refused(world):
    db, sf = world["db"], world["sf"]
    sf.checkup_batch_id = None
    with pytest.raises(ValueError):
        save(db, sf, _ex("1101700207364", {"wbc": 8383}))
