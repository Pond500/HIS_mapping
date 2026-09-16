"""Sign-in for the staff pages: passwords, session cookies and who may manage whom."""

from types import SimpleNamespace

import pytest

from app import auth


def user(role, hospital_id=1):
    return SimpleNamespace(role=role, hospital_id=hospital_id)


def test_password_round_trip():
    stored = auth.hash_password("correct horse battery")
    assert stored.startswith("pbkdf2_sha256$")
    assert "correct horse battery" not in stored
    assert auth.verify_password("correct horse battery", stored)
    assert not auth.verify_password("Correct horse battery", stored)


def test_same_password_gets_a_different_hash():
    assert auth.hash_password("abcd1234") != auth.hash_password("abcd1234")


def test_broken_hash_never_verifies():
    for junk in ("", "not-a-hash", "pbkdf2_sha256$x$y$z"):
        assert not auth.verify_password("abcd1234", junk)


def test_generated_passwords_are_random_and_long_enough():
    a, b = auth.new_password(), auth.new_password()
    assert a != b and len(a) >= 10


def test_session_token_round_trip():
    assert auth.read_token(auth.make_token(42)) == 42


def test_tampered_token_is_refused():
    token = auth.make_token(42)
    body, sig = token.rsplit(".", 1)
    other = body.replace("42.", "43.", 1) + "." + sig
    assert auth.read_token(other) is None
    assert auth.read_token(token[:-2] + "xy") is None
    assert auth.read_token("nonsense") is None


def test_token_expires_after_idle_time(monkeypatch):
    token = auth.make_token(7)
    monkeypatch.setattr(auth, "SESSION_MINUTES", -1)     # as if the session had timed out
    assert auth.read_token(token) is None


@pytest.mark.parametrize("actor,target,allowed", [
    ("superadmin", "admin", True),
    ("superadmin", "staff", True),
    ("superadmin", "superadmin", True),
    ("admin", "staff", True),
    ("admin", "admin", True),
    ("admin", "superadmin", False),     # never above your own rank
    ("staff", "staff", False),          # staff manage nobody
    ("doctor", "staff", False),
    ("superadmin", "doctor", False),    # doctors come from the doctor sign-up flow
])
def test_who_may_manage_whom(actor, target, allowed):
    assert auth.may_manage(user(actor), target) is allowed


def test_scope_is_the_own_hospital_except_for_superadmin():
    assert auth.same_scope(user("admin", 1), 1)
    assert not auth.same_scope(user("admin", 1), 2)
    assert not auth.same_scope(user("admin", 1), None)
    assert auth.same_scope(user("superadmin", None), 5)
