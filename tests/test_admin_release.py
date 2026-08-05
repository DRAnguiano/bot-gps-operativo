"""core-consistency-fixes #8 — endpoint admin de liberación de HUMAN_REVIEW.

Verifica la vía operativa: `POST /admin/release-human-review` invoca
`db.release_human_review` y respeta el guard `INTERNAL_API_KEY`. Sin Groq/DB real
(se mockea la función de DB).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    import app.app as A

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "app.db.release_human_review",
        lambda conversation_key, stage_to="START": calls.append((conversation_key, stage_to)),
    )
    return TestClient(A.app), A, calls, monkeypatch


def test_release_invokes_db_when_open(client):
    # Fail-closed (production-security-baseline): sin INTERNAL_API_KEY, TODO acceso se
    # deniega — no hay modo "abierto". Con la key correcta, sí invoca la DB.
    c, A, calls, mp = client
    mp.setattr(A, "INTERNAL_API_KEY", "secret")
    r = c.post(
        "/admin/release-human-review",
        json={"conversation_key": "telegram:123"},
        headers={"x-api-key": "secret"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "released"
    assert body["conversation_key"] == "telegram:123"
    assert calls == [("telegram:123", "START")]


def test_release_fail_closed_when_key_empty(client):
    # production-security-baseline: INTERNAL_API_KEY vacía → deniega TODO acceso
    # (fail-closed), incluso si llega un header x-api-key cualquiera.
    c, A, calls, mp = client
    mp.setattr(A, "INTERNAL_API_KEY", "")
    r = c.post(
        "/admin/release-human-review",
        json={"conversation_key": "z"},
        headers={"x-api-key": "cualquier-cosa"},
    )
    assert r.status_code == 401
    assert calls == []


def test_release_requires_api_key_when_set(client):
    c, A, calls, mp = client
    mp.setattr(A, "INTERNAL_API_KEY", "secret")
    # sin key → 401, no invoca DB
    r = c.post("/admin/release-human-review", json={"conversation_key": "x"})
    assert r.status_code == 401
    assert calls == []
    # con key correcta → 200, invoca DB
    r2 = c.post(
        "/admin/release-human-review",
        json={"conversation_key": "x"},
        headers={"x-api-key": "secret"},
    )
    assert r2.status_code == 200
    assert calls == [("x", "START")]


def test_release_respects_custom_stage(client):
    c, A, calls, mp = client
    mp.setattr(A, "INTERNAL_API_KEY", "secret")
    r = c.post(
        "/admin/release-human-review",
        json={"conversation_key": "y", "stage_to": "PROFILING"},
        headers={"x-api-key": "secret"},
    )
    assert r.status_code == 200
    assert calls == [("y", "PROFILING")]
