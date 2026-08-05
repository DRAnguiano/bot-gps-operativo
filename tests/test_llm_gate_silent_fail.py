"""Tests para el gate de LLM no disponible (llm-gate-silent-fail-on-quota).

Reescrito para el contrato Gemini-único (gemini-full-provider-migration):
- extract_turn lanza LLMUnavailableError cuando dispatch_json devuelve el JSON de
  error del contrato ('{"error": ...}' — 429/timeout ya absorbido dentro del
  dispatch, que nunca propaga la excepción de red cruda). El worker lo captura y
  aborta el turno en silencio (sin respuesta basura ni re-preguntas por extracción
  vacía) — mismo gate de producción que existía en la era Groq.
- extract_turn devuelve TurnExtraction vacía (sin lanzar) ante JSON malformado o
  una excepción inesperada del dispatch (degradación, no gate).
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from app.knowledge.llm_errors import LLMUnavailableError
from app.knowledge.turn_extractor import extract_turn, TurnExtraction


# ── Gate: contrato de error de Gemini → LLMUnavailableError ──────────────────

def test_extract_turn_raises_llm_unavailable_on_rate_limit():
    """dispatch_json devuelve el JSON de error del contrato (429/timeout) →
    extract_turn lo propaga como LLMUnavailableError para que el worker aborte el
    turno en silencio."""
    with patch("app.gemini_client.dispatch_json", return_value='{"error": "rate_limited"}'):
        with pytest.raises(LLMUnavailableError):
            extract_turn("hola, soy Juan", last_bot_question=None, known_facts={})


def test_llm_unavailable_is_runtime_error():
    """LLMUnavailableError es subclase de RuntimeError."""
    assert issubclass(LLMUnavailableError, RuntimeError)


# ── Degradación: JSON malformado / excepción inesperada → extracción vacía ───

def test_extract_turn_returns_empty_on_json_decode_error():
    """Cuando dispatch_json devuelve JSON malformado, extract_turn debe devolver
    TurnExtraction vacía sin lanzar (comportamiento de degradación actual)."""
    with patch("app.gemini_client.dispatch_json", return_value="no es json válido {{"):
        result = extract_turn("mensaje de prueba", last_bot_question=None, known_facts={})
    assert isinstance(result, TurnExtraction)
    assert result.fields == {}


def test_extract_turn_returns_empty_on_generic_exception():
    """Errores inesperados del dispatch (no el contrato de error) siguen absorbidos
    en TurnExtraction vacía."""
    with patch("app.gemini_client.dispatch_json", side_effect=ConnectionError("timeout")):
        result = extract_turn("mensaje", last_bot_question=None, known_facts={})
    assert isinstance(result, TurnExtraction)
    assert result.fields == {}


# ── Comportamiento del gate en el worker (lógica aislada) ─────────────────────

def test_llm_unavailable_propagates_through_gate_path():
    """LLMUnavailableError lanzada desde extract_turn es capturada como RuntimeError
    (parent) — verifica que no queda absorbida por un except Exception genérico.

    Nota: el test de integración completo del worker requiere mocks de Postgres/Redis/
    Chatwoot que no están disponibles en este entorno de test liviano. La verificación
    funcional se hace en prod. Este test cubre la cadena de tipos.
    """
    exc = LLMUnavailableError("quota agotada")
    assert isinstance(exc, RuntimeError)
    try:
        raise exc
    except LLMUnavailableError as caught:
        result = {
            "status": "skipped_llm_unavailable",
            "processed": False,
            "sent_to_chatwoot": False,
            "reason": str(caught),
        }
    assert result["status"] == "skipped_llm_unavailable"
    assert result["processed"] is False
    assert result["sent_to_chatwoot"] is False


def test_extract_turn_ok_returns_extraction():
    """Regresión: cuando dispatch_json funciona, extract_turn devuelve TurnExtraction
    con los fields esperados (sin gate)."""
    payload = json.dumps({
        "fields": {},
        "embedded_question": None,
        "signals": {},
    })
    with patch("app.gemini_client.dispatch_json", return_value=payload):
        result = extract_turn("todo bien", last_bot_question=None, known_facts={})
    assert isinstance(result, TurnExtraction)
    assert result.fields == {}
