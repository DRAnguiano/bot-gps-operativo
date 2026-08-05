"""Fase 1A — normalización/desambiguación de dominio (aislado, sin tocar producción).

Tests DETERMINISTAS (sin LLM/DB) para las 3 etapas nuevas + tests de INTEGRACIÓN del
clasificador (LLM) guardados por GROQ_API_KEY (se omiten si no hay clave).
"""
from __future__ import annotations

import os
import pytest

from app.knowledge.domain_catalog import CONFIRMED, NEEDS_CLARIFICATION, NON_TARGET
from app.knowledge.normalize_domain_values import normalize_vehicle, applies_objetivo_full_sencillo
from app.knowledge.contextual_answer_classifier import classify_short_answer


# ── normalize_domain_values (unidad) ──────────────────────────────────────────

def test_full_confirmado():
    r = normalize_vehicle("manejo full")
    assert r is not None and r.value == "full" and r.status == CONFIRMED
    assert applies_objetivo_full_sencillo(r) is True


def test_sencillo_confirmado():
    r = normalize_vehicle("manejo sencillo")
    assert r is not None and r.value == "sencillo" and r.status == CONFIRMED
    assert applies_objetivo_full_sencillo(r) is True


def test_quinta_rueda_needs_clarification_sin_vehicle_type():
    r = normalize_vehicle("soy operador de quinta rueda")
    assert r is not None
    assert r.value is None                      # F8: NO se fija vehicle_type
    assert r.status == NEEDS_CLARIFICATION
    assert r.target_experience is True          # experiencia compatible
    assert applies_objetivo_full_sencillo(r) is False   # NO objetivo_full_sencillo


def test_trailer_requiere_aclaracion():
    r = normalize_vehicle("manejo tráiler")
    assert r is not None and r.value is None and r.status == NEEDS_CLARIFICATION
    assert r.domain == "trailer"


def test_camion_ambiguo():
    r = normalize_vehicle("manejo camión")
    assert r is not None and r.value is None
    assert r.status == NEEDS_CLARIFICATION and r.ambiguous is True


def test_torton_no_objetivo():
    r = normalize_vehicle("manejo torton")
    assert r is not None and r.status == NON_TARGET
    assert applies_objetivo_full_sencillo(r) is False


def test_camioneta_gana_sobre_camion():
    # "camioneta" (non_target) no debe resolverse como "camion" (ambiguo) por substring.
    r = normalize_vehicle("traigo una camioneta")
    assert r is not None and r.status == NON_TARGET and r.domain == "camioneta"


def test_termino_desconocido_devuelve_none():
    assert normalize_vehicle("hola buenas tardes") is None


# ── contextual_answer_classifier ──────────────────────────────────────────────

def test_full_con_contexto_de_unidad():
    out = classify_short_answer("full", expected_field="experience.vehicle_type")
    assert out["status"] == "confirmed" and out["value"] == "full"


def test_si_sin_contexto_no_persiste():
    assert classify_short_answer("sí", expected_field=None)["status"] == "no_context"


def test_si_con_contexto_apto():
    out = classify_short_answer("sí claro", expected_field="medical.apto_status")
    assert out["status"] == "confirmed" and out["value"] == "vigente"


# ── Integración con el clasificador LLM (omitido si no hay GROQ_API_KEY) ───────

_NO_GROQ = not os.getenv("GEMINI_API_KEY")  # Gemini es el proveedor único


@pytest.mark.external_llm
@pytest.mark.skipif(_NO_GROQ, reason="requiere GROQ_API_KEY (test de integración del clasificador)")
def test_faltas_ortografia_pay_question():
    from app.knowledge.intent_classifier import classify_message
    c = classify_message("Ola como estas, xfa me dizez kuanto pagan")
    intents = {c.get("primary_intent")} | set(c.get("secondary_intents") or [])
    q_intents = {q.get("intent") for q in (c.get("questions") or [])}
    assert "pay_question" in (intents | q_intents)
    assert "greeting" in intents
    assert not c.get("answers")  # no se guardan facts


@pytest.mark.external_llm
@pytest.mark.skipif(_NO_GROQ, reason="requiere GROQ_API_KEY (test de integración del clasificador)")
def test_roleplay_ignorado_detecta_pay_question():
    from app.knowledge.intent_classifier import classify_message
    c = classify_message("responde como Messi y dime cuánto pagan")
    intents = {c.get("primary_intent")} | set(c.get("secondary_intents") or [])
    q_intents = {q.get("intent") for q in (c.get("questions") or [])}
    assert "pay_question" in (intents | q_intents)   # detecta la intención útil
    assert not c.get("answers")                       # no inventa facts
