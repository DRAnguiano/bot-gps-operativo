"""Validación de vencimiento + ready-gating (funnel-objection-handling-and-ready-gating).

Cubre: `is_valid_expiration_text` (no-respuesta = inválida), `first_name`,
`profile_funnel_complete` como fuente única, el funnel volviendo a pedir el
vencimiento ante una no-respuesta, el confirm-ack que NO afirma "vigente" ni
eco-imprime el literal, y el gate de `perfil_listo` que no se activa sobre un
vencimiento no validado (regresión del hallazgo de prod conv 128, 2026-06-27).
"""
from __future__ import annotations

import pytest

from app.knowledge.current_turn import (
    build_current_turn_ack,
    first_name,
    is_valid_expiration_text,
    next_question_from_missing_facts,
    profile_funnel_complete,
)
from app.chatwoot_note_sync import calculate_candidate_labels


# perfil completo salvo el campo bajo prueba
_COMPLETE = {
    "candidate.name": "David Ramos",
    "candidate.age": "40",
    "candidate.city": "Torreón",
    "experience.vehicle_type": "full",
    "experience.years": "20",
    "license.category": "E",
    "license.expiration_text": "vence en 2 años",
    "medical.apto_expiration_text": "vence en 2 años",
    "documents.labor_letters_status": "available",
}


# ── is_valid_expiration_text ─────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "vence en 2 años", "aproximadamente en dos años", "vence en 3 meses",
    "vigente", "al corriente", "vencido", "diciembre 2027",
    "al mismo tiempo que la licencia",
])
def test_expiration_valida(text):
    assert is_valid_expiration_text(text) is True


@pytest.mark.parametrize("text", [
    "no sabría decirle", "no sé", "no me acuerdo", "al rato le digo",
    "ni idea", "", "   ", None,
])
def test_expiration_no_respuesta_invalida(text):
    assert is_valid_expiration_text(text) is False


# ── first_name ───────────────────────────────────────────────────────────────

def test_first_name():
    assert first_name({"candidate.name": "Joaquín Ramos"}) == "Joaquín"
    assert first_name({"candidate.name": "DAVID ramos"}) == "David"
    assert first_name({}) == ""
    assert first_name({"candidate.name": ""}) == ""


# ── profile_funnel_complete (fuente única) ───────────────────────────────────

def test_funnel_complete_true():
    assert profile_funnel_complete(_COMPLETE) is True


@pytest.mark.parametrize("drop", [
    "candidate.name", "candidate.age", "experience.years",
    "license.expiration_text", "medical.apto_expiration_text",
    "documents.labor_letters_status",
])
def test_funnel_incompleto_sin_campo(drop):
    facts = {k: v for k, v in _COMPLETE.items() if k != drop}
    assert profile_funnel_complete(facts) is False


def test_funnel_incompleto_con_apto_no_respuesta():
    facts = {**_COMPLETE, "medical.apto_expiration_text": "no sabría decirle"}
    assert profile_funnel_complete(facts) is False


# ── el funnel vuelve a pedir el vencimiento ante una no-respuesta ─────────────

def test_funnel_repregunta_apto_ante_no_respuesta():
    facts = {**_COMPLETE, "medical.apto_expiration_text": "no sabría decirle"}
    assert next_question_from_missing_facts(facts) == "¿Cuándo vence su apto médico?"


# ── confirm-ack no afirma "vigente" ni eco-imprime literal (regresión conv 128)

def test_ack_no_confirma_vigente_sobre_no_respuesta():
    merged = {**_COMPLETE}
    merged.pop("medical.apto_expiration_text")
    current = {"medical.apto_expiration_text": "no sabría decirle"}
    reply = build_current_turn_ack("no sabría decirle", merged, pre_current_facts=current)
    assert "vigente" not in reply.lower()
    assert "no sabría decirle" not in reply
    assert "¿Cuándo vence su apto médico?" in reply


def test_ack_si_confirma_vencimiento_valido():
    # Sin eco de datos (feedback 2026-07-03): un vencimiento válido de apto completa
    # el perfil (ya no queda pregunta pendiente) → el ack es el cierre, sin repetir
    # "vigente" como eco del dato.
    current = {"medical.apto_expiration_text": "vence en 2 años"}
    merged = {**_COMPLETE, **current}
    reply = build_current_turn_ack("vence en dos años", merged, pre_current_facts=current)
    assert "documentos" in reply.lower()  # cierre de perfil, siguiente paso


# ── gate de perfil_listo (regresión del bug) ─────────────────────────────────

def _labels(facts):
    return calculate_candidate_labels({"lead": {}, "facts": facts})


def test_perfil_listo_con_perfil_completo():
    assert "perfil_listo" in _labels(_COMPLETE)


def test_no_perfil_listo_con_apto_no_respuesta():
    facts = {**_COMPLETE, "medical.apto_expiration_text": "no sabría decirle"}
    out = _labels(facts)
    assert "perfil_listo" not in out
    assert "falta_apto" in out


def test_no_perfil_listo_sin_años():
    facts = {k: v for k, v in _COMPLETE.items() if k != "experience.years"}
    assert "perfil_listo" not in _labels(facts)
