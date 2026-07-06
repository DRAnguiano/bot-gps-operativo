"""Tests de producción: auth fail-closed, dedupe y validación de arranque."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# 5.2 — _dedupe_messages
# ---------------------------------------------------------------------------

def _get_dedupe():
    from app.tasks_chatwoot import _dedupe_messages
    return _dedupe_messages


def test_dedupe_by_message_id():
    _dedupe_messages = _get_dedupe()
    msgs = [
        {"message_id": "abc", "content": "hola"},
        {"message_id": "abc", "content": "hola"},
    ]
    assert len(_dedupe_messages(msgs)) == 1


def test_dedupe_keeps_different_ids():
    _dedupe_messages = _get_dedupe()
    msgs = [
        {"message_id": "x1", "content": "hola"},
        {"message_id": "x2", "content": "hola"},
    ]
    assert len(_dedupe_messages(msgs)) == 2


def test_dedupe_fallback_no_id_same_content():
    _dedupe_messages = _get_dedupe()
    msgs = [
        {"received_at": 1.0, "content": "hola"},
        {"received_at": 1.0, "content": "hola"},
    ]
    assert len(_dedupe_messages(msgs)) == 1


def test_dedupe_fallback_different_content():
    _dedupe_messages = _get_dedupe()
    msgs = [
        {"received_at": 1.0, "content": "hola"},
        {"received_at": 1.0, "content": "adios"},
    ]
    assert len(_dedupe_messages(msgs)) == 2


def test_dedupe_no_crash_on_missing_fields():
    _dedupe_messages = _get_dedupe()
    result = _dedupe_messages([{}])
    assert result == [{}]


def test_dedupe_empty_list():
    _dedupe_messages = _get_dedupe()
    assert _dedupe_messages([]) == []


# ---------------------------------------------------------------------------
# 5.3 — Auth fail-closed en endpoints internos
# ---------------------------------------------------------------------------

TOKEN = "test-token"
VALID_KEY = "valid-internal-key"


@pytest.fixture
def client_with_keys(monkeypatch):
    monkeypatch.setenv("CHATWOOT_WEBHOOK_TOKEN", TOKEN)
    monkeypatch.setenv("INBOUND_DEBOUNCE_ENABLED", "false")
    monkeypatch.setenv("WEBHOOK_RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("INTERNAL_API_KEY", VALID_KEY)
    monkeypatch.setenv("REINDEX_API_KEY", VALID_KEY)
    import app.app as A
    importlib_reload(A)
    return TestClient(A.app)


@pytest.fixture
def client_empty_keys(monkeypatch):
    monkeypatch.setenv("CHATWOOT_WEBHOOK_TOKEN", TOKEN)
    monkeypatch.setenv("INBOUND_DEBOUNCE_ENABLED", "false")
    monkeypatch.setenv("WEBHOOK_RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("INTERNAL_API_KEY", "")
    monkeypatch.setenv("REINDEX_API_KEY", "")
    import app.app as A
    importlib_reload(A)
    return TestClient(A.app)


def importlib_reload(module):
    import importlib
    # `app.app._validate_security_config` lee INTERNAL_API_KEY/REINDEX_API_KEY vía
    # `from .settings import ...` — nombres resueltos contra el módulo `app.settings`
    # YA IMPORTADO (congelados en su primer import). Recargar solo `app.app` no
    # actualiza esos valores; hay que recargar `app.settings` primero para que
    # relea los env vars fijados por monkeypatch en este test.
    import app.settings
    importlib.reload(app.settings)
    importlib.reload(module)


def test_ask_returns_401_when_key_empty(client_empty_keys):
    resp = client_empty_keys.post("/ask", json={"q": "hola"}, headers={"x-api-key": ""})
    assert resp.status_code == 401


def test_ask_returns_401_when_key_wrong(client_with_keys):
    resp = client_with_keys.post("/ask", json={"q": "hola"}, headers={"x-api-key": "wrong"})
    assert resp.status_code == 401


def test_ask_accepts_correct_key(monkeypatch):
    # APP_ENV explícito (no producción): otros tests de este archivo hacen
    # `importlib.reload(A)` con APP_ENV=production + key vacía, que hace RAISE a
    # mitad del reload (deja el módulo en estado parcial). Fijar el valor aquí
    # evita depender del orden de ejecución / reloads previos.
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("REINDEX_API_KEY", VALID_KEY)
    monkeypatch.setenv("CHATWOOT_WEBHOOK_TOKEN", TOKEN)
    monkeypatch.setenv("INBOUND_DEBOUNCE_ENABLED", "false")
    monkeypatch.setenv("WEBHOOK_RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("INTERNAL_API_KEY", VALID_KEY)

    import app.app as A
    importlib_reload(A)

    async def fake_rag(*a, **kw):
        return []
    monkeypatch.setattr(A, "retrieve_context_for_guardrail", fake_rag if False else lambda *a, **kw: [])

    c = TestClient(A.app)
    resp = c.post("/ask", json={"q": "hola"}, headers={"x-api-key": VALID_KEY})
    # 200 o cualquier código que no sea 401 indica que pasó el guard de auth
    assert resp.status_code != 401


# ---------------------------------------------------------------------------
# 5.4 — Validación de arranque en producción con secreto vacío
# ---------------------------------------------------------------------------

def test_startup_raises_in_production_with_empty_key(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("INTERNAL_API_KEY", "")
    monkeypatch.setenv("REINDEX_API_KEY", "some-key")
    monkeypatch.setenv("CHATWOOT_WEBHOOK_TOKEN", "some-token")

    import app.app as A
    importlib_reload(A)

    with pytest.raises(RuntimeError, match="Configuración insegura"):
        A._validate_security_config()


def test_startup_raises_in_production_with_dev_token(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("INTERNAL_API_KEY", "some-key")
    monkeypatch.setenv("REINDEX_API_KEY", "some-key")
    monkeypatch.setenv("CHATWOOT_WEBHOOK_TOKEN", "dev_chatwoot_webhook_token_123")

    import app.app as A
    importlib_reload(A)

    with pytest.raises(RuntimeError, match="Configuración insegura"):
        A._validate_security_config()


def test_startup_ok_in_production_with_all_keys(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("INTERNAL_API_KEY", "a" * 32)
    monkeypatch.setenv("REINDEX_API_KEY", "b" * 32)
    monkeypatch.setenv("CHATWOOT_WEBHOOK_TOKEN", "c" * 32)

    import app.app as A
    importlib_reload(A)

    # No debe lanzar excepción
    A._validate_security_config()


def test_startup_warns_not_raises_in_dev_with_empty_key(monkeypatch, capsys):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("INTERNAL_API_KEY", "")
    monkeypatch.setenv("REINDEX_API_KEY", "")
    monkeypatch.setenv("CHATWOOT_WEBHOOK_TOKEN", "")

    import app.app as A
    importlib_reload(A)

    # En dev no levanta excepción
    A._validate_security_config()
    captured = capsys.readouterr()
    assert "SECURITY" in captured.out
