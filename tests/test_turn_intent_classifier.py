"""Tests para el Turn Intent Pre-Classifier (TIPC).

Happy-path con Gemini real (marcados external_llm: 5 RPM free tier no aguanta la
ráfaga del gate unitario); fail-safe sin API key.
"""
import os

import pytest

_NO_LLM = not os.getenv("GEMINI_API_KEY")

from app.knowledge.turn_intent_classifier import TurnIntentSignals, classify_turn_intent


def test_empty_message_returns_neutral():
    result = classify_turn_intent("")
    assert isinstance(result, TurnIntentSignals)
    assert result.is_ya_reclamo is False
    assert result.is_memory_claim is False
    assert result.has_embedded_question is False


def test_neutral_signals_default_values():
    s = TurnIntentSignals()
    assert s.is_ya_reclamo is False
    assert s.is_memory_claim is False
    assert s.has_embedded_question is False
    assert s.call_requested is False
    assert s.renewal_proof is None
    assert s.no_road_experience is False
    assert s.has_expiry_context is False
    assert s.experience_context is False
    assert s.is_joke_request is False


@pytest.mark.external_llm
@pytest.mark.skipif(_NO_LLM, reason="Requiere GEMINI_API_KEY")
def test_ya_tengo_licencia_no_es_reclamo():
    result = classify_turn_intent("ya tengo la licencia E vigente")
    assert result.is_ya_reclamo is False


@pytest.mark.external_llm
@pytest.mark.skipif(_NO_LLM, reason="Requiere GEMINI_API_KEY")
def test_ya_le_habia_dicho_es_reclamo():
    result = classify_turn_intent("ya le había dicho que tengo 10 años de experiencia")
    assert result.is_ya_reclamo is True


@pytest.mark.external_llm
@pytest.mark.skipif(_NO_LLM, reason="Requiere GEMINI_API_KEY")
def test_memory_claim_eso_ya_lo_habia_comentado():
    result = classify_turn_intent("eso ya lo había comentado con su compañero")
    assert result.is_memory_claim is True


@pytest.mark.external_llm
@pytest.mark.skipif(_NO_LLM, reason="Requiere GEMINI_API_KEY")
def test_embedded_question_sin_vocabulario_listado():
    result = classify_turn_intent("dan comida en los viajes largos")
    assert result.has_embedded_question is True


@pytest.mark.external_llm
@pytest.mark.skipif(_NO_LLM, reason="Requiere GEMINI_API_KEY")
def test_call_requested_ponerse_en_contacto():
    result = classify_turn_intent("prefiero que se pongan en contacto conmigo por teléfono")
    assert result.call_requested is True


@pytest.mark.external_llm
@pytest.mark.skipif(_NO_LLM, reason="Requiere GEMINI_API_KEY")
def test_renewal_proof_ya_pague_la_cita():
    result = classify_turn_intent("ya pagué la cita del trámite")
    assert result.renewal_proof == "si"


@pytest.mark.external_llm
@pytest.mark.skipif(_NO_LLM, reason="Requiere GEMINI_API_KEY")
def test_no_road_experience_soy_principiante():
    result = classify_turn_intent("soy principiante en esto del tracto")
    assert result.no_road_experience is True


@pytest.mark.external_llm
@pytest.mark.skipif(_NO_LLM, reason="Requiere GEMINI_API_KEY")
def test_expiry_context_se_me_acaba():
    result = classify_turn_intent("se me acaba la vigencia del apto en 3 meses")
    assert result.has_expiry_context is True


@pytest.mark.external_llm
@pytest.mark.skipif(_NO_LLM, reason="Requiere GEMINI_API_KEY")
def test_experience_context_transportista():
    result = classify_turn_intent("llevo 8 años como transportista")
    assert result.experience_context is True


@pytest.mark.external_llm
@pytest.mark.skipif(_NO_LLM, reason="Requiere GEMINI_API_KEY")
def test_pure_profile_message_no_flags():
    result = classify_turn_intent("soy de Gómez Palacio, tengo licencia E")
    assert result.has_embedded_question is False
    assert result.call_requested is False
    assert result.no_road_experience is False


# ── is_joke_request (bug en vivo 2026-07-07, conv 166) ────────────────────────
# El Term Neo4j smalltalk_joke fallaba en mensajes compuestos con aliases exactos
# ("chistes" plural no matcheaba "chiste" singular). Movido al extractor unificado
# — MISMA llamada LLM que ya corre cada turno, sin costo extra — para que el LLM
# distinga (few-shot) una petición real de un uso idiomático/queja de la palabra.

def test_is_joke_request_field_parsed_from_json(monkeypatch):
    import json as _json
    # call_groq_json se importa dentro de la función (from app.indexer import ...) —
    # el patch debe apuntar al módulo real, no al nombre local inexistente.
    monkeypatch.setattr(
        "app.gemini_client.dispatch_json",
        lambda *a, **kw: _json.dumps({"is_joke_request": True}),
    )
    result = classify_turn_intent("cuéntame un chiste")
    assert result.is_joke_request is True


def test_is_joke_request_defaults_false_when_missing(monkeypatch):
    import json as _json
    monkeypatch.setattr(
        "app.gemini_client.dispatch_json",
        lambda *a, **kw: _json.dumps({}),
    )
    result = classify_turn_intent("cualquier mensaje")
    assert result.is_joke_request is False


@pytest.mark.external_llm
@pytest.mark.skipif(_NO_LLM, reason="Requiere GEMINI_API_KEY")
def test_is_joke_request_true_for_genuine_request():
    result = classify_turn_intent("Oye usted no cuenta chistes para animarme que me contraten")
    assert result.is_joke_request is True


@pytest.mark.external_llm
@pytest.mark.skipif(_NO_LLM, reason="Requiere GEMINI_API_KEY")
def test_is_joke_request_false_for_idiomatic_complaint():
    # Feedback del usuario 2026-07-07: "así que chiste" es sarcasmo ("qué ridículo"),
    # NO una petición de humor — un substring/regex no puede distinguir esto.
    result = classify_turn_intent("así que chiste todo este proceso")
    assert result.is_joke_request is False
