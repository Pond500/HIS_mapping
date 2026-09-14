"""External API (/api/v1, D19): keys, limits and request checks that need no database."""

import pytest
from fastapi.testclient import TestClient

from app import api_keys
from app.routes import api_v1


def test_keys_are_random_and_only_their_hashes_are_compared():
    a, b = api_keys.new_key(), api_keys.new_key()
    assert a != b and a.startswith(api_keys.PREFIX) and len(a) > 40
    assert api_keys.hash_key(a) == api_keys.hash_key(a) != api_keys.hash_key(b)
    assert len(api_keys.hash_key(a)) == 64


def test_rate_limit_is_per_key():
    lim = api_keys.RateLimiter(per_minute=2)
    assert lim.allow(1) and lim.allow(1)
    assert not lim.allow(1)
    assert lim.allow(2)


@pytest.fixture
def client():
    api_v1.api.dependency_overrides[api_keys.caller] = lambda: api_keys.Caller(1, 1, "H01")
    yield TestClient(api_v1.api)
    api_v1.api.dependency_overrides.clear()


def test_no_key_is_401():
    r = TestClient(api_v1.api).post("/files", files={"file": ("a.csv", b"x")})
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "missing_key"


def test_wrong_file_type_is_refused(client):
    r = client.post("/files", files={"file": ("report.pdf", b"%PDF-1.7")})
    assert r.status_code == 415
    assert r.json()["detail"]["code"] == "unsupported_type"


def test_too_large_is_refused(client, monkeypatch):
    monkeypatch.setattr(api_v1, "MAX_BYTES", 10)
    r = client.post("/files", files={"file": ("a.csv", b"x" * 11)})
    assert r.status_code == 413
    assert r.json()["detail"]["code"] == "too_large"


def test_empty_file_is_refused(client):
    r = client.post("/files", files={"file": ("a.csv", b"")})
    assert r.status_code == 400


def test_docs_show_only_the_hospital_api():
    paths = TestClient(api_v1.api).get("/openapi.json").json()["paths"]
    assert set(paths) == {"/files", "/files/{file_id}"}
