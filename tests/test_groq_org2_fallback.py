"""Tests para el tercer nivel de fallback GROQ_API_KEY_ORG2 en _groq_with_fallback.

Verifica que:
- Primaria OK → devuelve resultado (sin tocar backup/org2).
- Primaria falla, backup OK → devuelve resultado.
- Primaria falla, backup falla, org2 OK → devuelve resultado.
- Primaria falla, backup falla, sin org2 → propaga GroqRateLimitError.
- call_groq_json pasa org2_key desde el entorno.
"""
import os
from unittest import mock

import pytest
from groq import RateLimitError as GroqRateLimitError

from app.indexer import _groq_with_fallback, call_groq_json

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rate_limit_error() -> GroqRateLimitError:
    """Crea una instancia mínima de GroqRateLimitError sin llamar a Groq."""
    return GroqRateLimitError.__new__(GroqRateLimitError)


_MESSAGES = [{"role": "user", "content": "hola"}]
_MODEL = "llama-3.1-8b-instant"


# ---------------------------------------------------------------------------
# Tests de _groq_with_fallback
# ---------------------------------------------------------------------------

def test_primary_ok_no_fallback_needed():
    """Primaria responde OK: devuelve resultado sin tocar backup/org2."""
    with mock.patch("app.indexer._groq_call", return_value="ok_primary") as mock_call:
        result = _groq_with_fallback(
            "key_primary", "key_backup", "test_fn", _MESSAGES, _MODEL,
            org2_key="key_org2",
        )
    assert result == "ok_primary"
    assert mock_call.call_count == 1


def test_backup_ok_when_primary_fails():
    """Primaria falla con RateLimitError, backup responde OK."""
    call_count = {"n": 0}

    def side_effect(key, *args, **kwargs):
        call_count["n"] += 1
        if key == "key_primary":
            raise _rate_limit_error()
        return "ok_backup"

    with mock.patch("app.indexer._groq_call", side_effect=side_effect):
        result = _groq_with_fallback(
            "key_primary", "key_backup", "test_fn", _MESSAGES, _MODEL,
        )
    assert result == "ok_backup"
    assert call_count["n"] == 2


def test_org2_ok_when_primary_and_backup_fail():
    """Primaria y backup agotan cuota; org2 responde OK."""
    def side_effect(key, *args, **kwargs):
        if key == "key_org2":
            return "ok_org2"
        raise _rate_limit_error()

    with mock.patch("app.indexer._groq_call", side_effect=side_effect):
        result = _groq_with_fallback(
            "key_primary", "key_backup", "test_fn", _MESSAGES, _MODEL,
            org2_key="key_org2",
        )
    assert result == "ok_org2"


def test_raises_when_all_keys_exhausted():
    """Todas las claves agotan cuota: propaga GroqRateLimitError."""
    with mock.patch("app.indexer._groq_call", side_effect=_rate_limit_error()):
        with pytest.raises(GroqRateLimitError):
            _groq_with_fallback(
                "key_primary", "key_backup", "test_fn", _MESSAGES, _MODEL,
                org2_key="key_org2",
            )


def test_raises_without_org2_when_both_fail():
    """Sin org2: propaga GroqRateLimitError cuando primaria y backup fallan."""
    with mock.patch("app.indexer._groq_call", side_effect=_rate_limit_error()):
        with pytest.raises(GroqRateLimitError):
            _groq_with_fallback(
                "key_primary", "key_backup", "test_fn", _MESSAGES, _MODEL,
            )


def test_log_emitted_on_org2_fallback(capsys):
    """Verifica que se emite [groq-fallback] usando ORG2 en el log."""
    def side_effect(key, *args, **kwargs):
        if key == "key_org2":
            return "ok_org2"
        raise _rate_limit_error()

    with mock.patch("app.indexer._groq_call", side_effect=side_effect):
        _groq_with_fallback(
            "key_primary", "key_backup", "test_fn", _MESSAGES, _MODEL,
            org2_key="key_org2",
        )

    captured = capsys.readouterr()
    # El log incluye la etapa que se agotó (p. ej. "BACKUP agotada, usando ORG2");
    # verificamos la propiedad de dominio (se registró el fallback a ORG2), no el
    # prefijo literal exacto.
    assert "[groq-fallback]" in captured.out
    assert "usando ORG2" in captured.out


# ---------------------------------------------------------------------------
# Test: call_groq_json pasa org2_key desde entorno
# ---------------------------------------------------------------------------

def test_call_groq_json_passes_org2_from_env():
    """call_groq_json lee GROQ_API_KEY_ORG2 y lo pasa a _groq_with_fallback."""
    env = {
        "GROQ_API_KEY": "primary",
        "GROQ_API_KEY_BACKUP": "backup",
        "GROQ_API_KEY_ORG2": "org2_from_env",
    }

    captured_kwargs = {}

    def fake_fallback(primary, backup, fn_name, messages, model, **kwargs):
        captured_kwargs.update(kwargs)
        return '{"ok": true}'

    with mock.patch.dict(os.environ, env):
        with mock.patch("app.indexer._groq_with_fallback", side_effect=fake_fallback):
            call_groq_json("user prompt", "system prompt")

    assert captured_kwargs.get("org2_key") == "org2_from_env"


def test_call_groq_json_no_org2_when_env_not_set():
    """call_groq_json no pasa org2_key si GROQ_API_KEY_ORG2 no está en el entorno."""
    env = {
        "GROQ_API_KEY": "primary",
        "GROQ_API_KEY_BACKUP": "backup",
    }
    env_without_org2 = {k: v for k, v in os.environ.items()}
    env_without_org2.pop("GROQ_API_KEY_ORG2", None)
    env_without_org2.update(env)

    captured_kwargs = {}

    def fake_fallback(primary, backup, fn_name, messages, model, **kwargs):
        captured_kwargs.update(kwargs)
        return '{"ok": true}'

    with mock.patch.dict(os.environ, env_without_org2, clear=True):
        with mock.patch("app.indexer._groq_with_fallback", side_effect=fake_fallback):
            call_groq_json("user prompt", "system prompt")

    assert captured_kwargs.get("org2_key") is None
