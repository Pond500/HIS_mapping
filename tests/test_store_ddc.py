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


def test_processing_the_same_file_again_does_not_ask_twice(world):
    """Answering a review re-runs the whole file. The disagreement it found the
    first time is still there, and a second copy of it would mean the reviewer
    decides once and the other copy stays open for ever."""
    db, sf = world["db"], world["sf"]
    save(db, sf, _ex("1101700207364", {"wbc": 8383}))
    db.flush()
    for _ in range(3):
        save(db, sf, _ex("1101700207364", {"wbc": 9100}))
        db.flush()

    assert db.query(Conflict).count() == 1


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


def test_registering_a_stranger_who_is_already_there_is_not_an_error(world):
    """Two files can each ask about the same stranger. Answering the second one
    used to hit the (citizen_id, department_id) key and 500, which threw away
    every other answer saved in the same click."""
    from app.routes.reviews import Decision, _apply_people_decision

    db, sf, dept = world["db"], world["sf"], world["dept"]
    r = PendingReview(source_file_id=sf.id, kind="unregistered_person", status="open",
                      field_set="result",
                      payload={"cid": "1101700207994", "name_in_file": "คนใหม่ มาก่อน",
                               "known_departments": [dept.name]})
    db.add(r)
    db.flush()
    d = Decision(review_id=r.id, action="register", header=dept.name,
                 first_name="คนใหม่", last_name="มาก่อน")

    _apply_people_decision(db, sf, r, d, "reviewer")
    db.flush()
    _apply_people_decision(db, sf, r, d, "reviewer")   # the second file's question
    db.flush()

    assert db.query(Employee).filter(Employee.cid == "1101700207994").count() == 1


def test_a_results_file_is_not_asked_for_a_department_column(world):
    """D23 moved the department to the register. Asking a results file for one
    offered the reviewer whatever text column the file happened to have — on the
    department's own files, the chest X-ray finding."""
    from app.pipeline.extract import extract
    from app.pipeline.mapper import Mapper
    from app.pipeline.profiler import profile_sheet
    from app.pipeline.reader import Sheet

    db, sf = world["db"], world["sf"]
    rows = [["เลขบัตรประชาชน", "ชื่อ-สกุล", "Hb"],
            ["1101700207364", "สมชาย ใจดี", "13.9"]]
    mapper = Mapper(db, sf.hospital_id)
    spec = profile_sheet(Sheet("csv", rows), mapper.known_labels(), mapper.identity_aliases(), None)
    assert "department_id" in spec.missing_roles        # the profiler still reports it

    ex = extract([Sheet("csv", rows)], [spec], mapper, {}, {}, {}, "2026-03-01")
    assert [r for r in ex.reviews if r["kind"] == "identity"] == []


def test_a_retry_after_a_failed_reprocess_still_stores_the_held_back_results(world, monkeypatch):
    """Registering a stranger commits first, then the file is re-run to store the
    results that were waiting on them. If that re-run fails and the reviewer presses
    save again, the registration is already decided and is skipped. The retry must
    still re-run the file, or the held-back results stay unsaved with nothing on
    screen to say so.

    Today it does — with nothing decided, the route hands the file to
    service.decide, which re-runs it whether the graph is waiting or finished. This
    test pins that: it is the property, not the mechanism, that must not be lost."""
    from sqlalchemy.orm import sessionmaker
    from app.routes import reviews as route

    db, sf, dept = world["db"], world["sf"], world["dept"]
    r = PendingReview(source_file_id=sf.id, kind="unregistered_person", status="open",
                      field_set="result",
                      payload={"cid": "1101700207994", "name_in_file": "คนใหม่ มาก่อน",
                               "known_departments": [dept.name]})
    db.add(r)
    db.commit()
    # the route closes the session it is given, so take what the test needs first
    file_id, review_id, dept_name = sf.id, r.id, dept.name

    reruns = []

    def flaky_process(session, file):
        reruns.append("process_file")
        if len(reruns) == 1:
            raise RuntimeError("the re-run fell over")

    class StubService:
        @staticmethod
        def status(fid):
            return {"upload_id": fid}

        @staticmethod
        def decide(fid, decisions):
            reruns.append("service.decide")      # the real one re-runs the file
            return {"upload_id": fid}

    monkeypatch.setattr(route, "process_file", flaky_process)
    monkeypatch.setattr(route, "service", StubService)
    monkeypatch.setattr(route, "SessionLocal", sessionmaker(bind=db.get_bind()))

    class U:
        username = "tester"

    body = route.DecisionBody(decisions=[route.Decision(
        review_id=review_id, action="register", header=dept_name,
        first_name="คนใหม่", last_name="มาก่อน")])

    with pytest.raises(RuntimeError):
        route.decide(file_id, body, db=db, user=U())        # registered, re-run failed
    route.decide(file_id, body, db=db, user=U())            # the reviewer presses save again

    assert reruns == ["process_file", "service.decide"], \
        "the retry must re-run the file even though nothing new was decided"


def test_a_range_suspect_question_says_why_and_the_unit_is_a_choice(world):
    """The reviewer answered "this is wbc" with no unit, was asked again because 4.7 is
    not a plausible count in cells/µL, and the screen never said why: the reason was in
    the payload and nothing displayed it. The payload now flags it, and the units the
    reviewer may pick are exactly the ones the system can convert."""
    from app.pipeline import units
    from app.pipeline.extract import extract
    from app.pipeline.mapper import Mapper
    from app.pipeline.profiler import profile_sheet
    from app.pipeline.reader import Sheet

    db, sf = world["db"], world["sf"]
    rows = [["เลขบัตรประชาชน", "ชื่อ-สกุล", "wbc"],
            ["1101700207364", "สมชาย ใจดี", "4.7"],
            ["1101700207364", "สมชาย ใจดี", "4.91"],
            ["1101700207364", "สมชาย ใจดี", "6.46"]]        # the rule needs 3+ values to suspect anything
    mapper = Mapper(db, sf.hospital_id)
    spec = profile_sheet(Sheet("csv", rows), mapper.known_labels(), mapper.identity_aliases(), None)
    ex = extract([Sheet("csv", rows)], [spec], mapper, {}, {}, {}, "2026-03-01")

    q = [r for r in ex.reviews if r["kind"] == "mapping"]
    assert len(q) == 1
    p = q[0]["payload"]
    assert p["range_suspect"] is True and p["canonical_unit"] == "cells/µL"
    assert (p["lo"], p["hi"]) == (1000, 50000)

    # what a reviewer can pick converts, and includes the unit those numbers are in
    assert "10^3/µl" in units.accepted_units("wbc")
    assert all(units.factor("wbc", u) for u in units.accepted_units("wbc"))
    assert units.accepted_units("chest_xray") == []          # not a numeric column
