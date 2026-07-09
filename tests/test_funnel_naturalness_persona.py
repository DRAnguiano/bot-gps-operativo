"""Tests de naturalidad del funnel y voz de persona (funnel-naturalness-and-persona-voice).

Cubre: vocativo por nombre de pila la primera vez (y NO en turnos posteriores),
copy de unidad sin redundancia, y persona del LLM sin "Capital Humano".
"""
from __future__ import annotations

from app.knowledge.current_turn import (
    build_current_turn_ack,
    next_question_from_missing_facts,
)
from app.indexer import _llm_system_message


# ── Vocativo por nombre de pila ─────────────────────────────────────────────

def test_vocativo_primera_vez():
    facts = {"candidate.name": "David Ramos Anguiano", "candidate.city": "Gómez Palacio",
             "candidate.age": "29"}
    out = build_current_turn_ack("x", merged_facts=facts, pre_current_facts={},
                                 name_just_learned=True)
    assert out.startswith("Gracias, David.")
    # Solo el vocativo + siguiente pregunta; no enumera los demás datos del turno
    assert "Anotado, Gómez Palacio" not in out


def test_sin_vocativo_si_nombre_ya_conocido():
    facts = {"candidate.name": "David Ramos Anguiano"}
    out = build_current_turn_ack("x", merged_facts=facts,
                                 pre_current_facts={"license.category": "E"},
                                 name_just_learned=False)
    assert "Gracias, David." not in out


def test_sin_nombre_omite_vocativo_sin_fallar():
    out = build_current_turn_ack("x", merged_facts={}, pre_current_facts={},
                                 name_just_learned=True)
    assert "Gracias, ." not in out  # no vocativo vacío
    assert isinstance(out, str) and out


# ── Copy de unidad sin redundancia ──────────────────────────────────────────

def test_copy_unidad_sin_redundancia():
    # Copy consolidada (gemini-full-provider-migration B1-B3, dedup de
    # vehicle_vacancy_question entre current_turn/intent_orchestrator/orchestrator).
    facts = {"candidate.name": "David", "candidate.city": "Gómez Palacio",
             "candidate.age": "29"}
    q = next_question_from_missing_facts(facts)
    assert "Le comento, actualmente tenemos vacantes para operador sencillo y para tracto full" in q
    assert "¿En cuál tiene experiencia?" in q
    # No repite "full" dos veces
    assert q.count("full") == 1
    assert "Las vacantes disponibles son para" not in q


# ── Persona del LLM ─────────────────────────────────────────────────────────

def test_persona_no_capital_humano():
    s = _llm_system_message()
    assert "asistente de Capital Humano" not in s
    assert "Mundo" in s and "Transmontes" in s
