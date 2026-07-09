"""Paridad de señales entre turn_extractor (camino vivo) y turn_intent_classifier.

Bug en vivo encontrado 2026-07-08: is_joke_request/conversational_purpose se
agregaron solo al prompt de turn_intent_classifier.py, pero el worker llama a
extract_turn (turn_extractor.py), que tiene su PROPIO prompt/parser de señales
duplicado — nunca pedía ni parseaba esos dos campos. En producción,
`turn_signals.is_joke_request` era SIEMPRE False sin importar lo que dijera el
candidato (el fix de conv 166 quedó estructuralmente correcto pero muerto).
"""
from __future__ import annotations

from app.knowledge.turn_extractor import _TURN_EXTRACTOR_SYSTEM, _parse_signals


def test_extractor_schema_requests_joke_and_purpose():
    assert "is_joke_request" in _TURN_EXTRACTOR_SYSTEM
    assert "conversational_purpose" in _TURN_EXTRACTOR_SYSTEM


def test_parse_signals_reads_joke_request():
    signals = _parse_signals({"is_joke_request": True})
    assert signals.is_joke_request is True


def test_parse_signals_reads_conversational_purpose():
    signals = _parse_signals({"conversational_purpose": "queja"})
    assert signals.conversational_purpose == "queja"


def test_parse_signals_defaults_when_absent():
    signals = _parse_signals({})
    assert signals.is_joke_request is False
    assert signals.conversational_purpose == "none"


def test_parse_signals_rejects_invalid_purpose():
    signals = _parse_signals({"conversational_purpose": "hackeo"})
    assert signals.conversational_purpose == "none"


def test_parse_signals_none_raw_returns_neutral():
    signals = _parse_signals(None)
    assert signals.is_joke_request is False
    assert signals.conversational_purpose == "none"
