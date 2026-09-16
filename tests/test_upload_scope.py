"""
The hospital a file is filed under comes from the signed-in account (D20).

This is a data-correctness rule, not a UI preference: before it, the browser sent a
free-text hospital code and `get_or_create_hospital` created whatever it was given, so
one typo ("H1" for "H01") filed the data and every mapping learned from it under a
hospital that does not exist — silently, and only visible much later when the next file
from the real hospital asked the same questions again.
"""

import pytest
from sqlalchemy.orm import Session

from app.models import AppUser, Hospital
from app.routes.upload import hospital_code_for


class FakeQuery:
    def __init__(self, hospitals):
        self._hospitals = hospitals
        self._code = None

    def filter(self, clause):
        # the only filter used is Hospital.code == <code>
        self._code = clause.right.value
        return self

    def one_or_none(self):
        return next((h for h in self._hospitals if h.code == self._code), None)


class FakeSession(Session):
    """Just enough Session for hospital_code_for: no database, no writes."""

    def __init__(self, hospitals):
        self._hospitals = hospitals

    def query(self, model):
        assert model is Hospital
        return FakeQuery(self._hospitals)

    def get(self, model, pk):
        assert model is Hospital
        return next((h for h in self._hospitals if h.id == pk), None)


def _hospitals():
    a = Hospital(code="H01", name="โรงพยาบาลหนึ่ง")
    a.id = 1
    b = Hospital(code="H08", name="โรงพยาบาลแปด")
    b.id = 8
    return [a, b]


def _user(role, hospital_id):
    u = AppUser(username=f"{role}-1", name="ทดสอบ", surname="ทดสอบ",
                email="t@example.com", password_hash="x", role=role, hospital_id=hospital_id)
    return u


def test_staff_gets_own_hospital_and_the_request_is_ignored():
    db = FakeSession(_hospitals())
    user = _user("staff", 1)
    # the browser asks for H08; the account says H01, and the account wins
    assert hospital_code_for(db, user, "H08") == "H01"
    assert hospital_code_for(db, user, "") == "H01"


def test_a_typo_never_creates_a_hospital():
    db = FakeSession(_hospitals())
    admin = _user("superadmin", None)
    with pytest.raises(ValueError, match="ไม่พบหน่วยบริการ"):
        hospital_code_for(db, admin, "H1")          # meant H01
    assert [h.code for h in db._hospitals] == ["H01", "H08"]


def test_superadmin_may_name_an_existing_hospital():
    db = FakeSession(_hospitals())
    admin = _user("superadmin", None)
    assert hospital_code_for(db, admin, "H08") == "H08"
    assert hospital_code_for(db, admin, "  H01  ") == "H01"


def test_superadmin_must_choose_one():
    db = FakeSession(_hospitals())
    with pytest.raises(ValueError, match="กรุณาเลือกหน่วยบริการ"):
        hospital_code_for(db, _user("superadmin", None), "")


def test_account_without_a_hospital_is_refused_not_guessed():
    db = FakeSession(_hospitals())
    with pytest.raises(ValueError, match="ยังไม่ได้ผูกกับหน่วยบริการ"):
        hospital_code_for(db, _user("staff", None), "H01")
