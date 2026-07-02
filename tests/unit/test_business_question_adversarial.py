"""Matriz adversarial — detección de pregunta de negocio (Fase 2 / D5).

Demuestra, de forma DETERMINISTA (sin LLM real), que la detección de los casos
`llm_only_required` NO depende de `?` ni de `BUSINESS_QUESTION_TERMS`, sino
EXCLUSIVAMENTE de la señal estructurada del extractor (`has_embedded_question`).

Cada turno expone tres señales (`_trace`):
  - is_question              (signo `?`/`¿` o apertura interrogativa)
  - business_term_regex_hit  (BUSINESS_QUESTION_TERMS tras el normalizador real)
  - has_embedded_question    (señal semántica del extractor — aquí, fixture)

Preflight (regla 2): cada caso `llm_only_required` se valida contra el normalizador
y el regex REALES; si coincidiera, el test falla en el preflight (no se debilita el
assert). Las 2 reformulaciones (BQ-L11/BQ-L18) ya pasaron ese preflight.

NOTA DE ALCANCE: la capa `decision` (intent_family / action / response_priority /
facts) NO se asere aquí porque hoy el detector devuelve un bool; esos asserts viven
en la eval `external_llm` y crecerán con los Bloques 3–6 (TurnDecision + autoridad
de funnel). Aquí se prueba SOLO la causalidad de detección (criterio de aceptación #1).
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.knowledge.current_turn import (
    BUSINESS_QUESTION_TERMS,
    has_business_question,
    is_question,
    _message_has_any,
)


@dataclass
class _Signals:
    """Fixture determinista de la salida estructurada del extractor."""
    has_embedded_question: bool = False


def _trace(message: str, signals: _Signals) -> dict:
    return {
        "is_question": is_question(message),
        "business_term_regex_hit": _message_has_any(message, BUSINESS_QUESTION_TERMS),
        "has_embedded_question": signals.has_embedded_question,
    }


# ── Casos llm_only_required (BQ-L11/BQ-L18 ya reformulados por preflight) ──────
# (id, message, intent_family)  — intent_family es metadata para la eval external_llm.
LLM_ONLY = [
    ("BQ-L01", "d a komo da el km jaja k bonito ta el klima", "pay"),
    ("BQ-L02", "x kilometro kuanto kae masomenos", "pay"),
    ("BQ-L03", "una vuelta d esas k tanto deja pa uno", "pay"),
    ("BQ-L04", "pa k lado se rueda mas seguido", "routes"),
    ("BQ-L05", "ai jalones pa arriba o puro cerka", "routes"),
    ("BQ-L06", "uno anda mucho fuera o regresa rapido", "travel_conditions"),
    ("BQ-L07", "q ocupa uno pa entrar yo ya kiero jalar", "requirements"),
    ("BQ-L08", "pa apuntarme k es lo primero k tengo k soltar", "onboarding_process"),
    ("BQ-L09", "la oja medika esa komo ba o kien la da", "medical_document"),
    ("BQ-L10", "lo d la pipi antes d entrar komo sta", "drug_test"),
    # BQ-L11 reformulado: sin "orina" (regex hit). Significado preservado (examen antidoping).
    ("BQ-L11", "el examen ese d la pipi se ase ai o asta despues", "drug_test"),
    ("BQ-L12", "a q ora se reporta uno aka", "schedule_or_callback"),
    ("BQ-L13", "ya no ay chans pa meterse o todabia", "vacancy_availability"),
    ("BQ-L14", "andan agarrando gente aun o ya se lleno", "vacancy_availability"),
    ("BQ-L15", "ya andube con ustedes antes ai modo d bolber", "reingreso"),
    ("BQ-L16", "nunk e jalado trailer aun asi se puede", "training_or_no_experience"),
    ("BQ-L17", "es caja normal o d las dobles lo k mueven", "vehicle_operation"),
    # BQ-L18 reformulado: sin "donde" inicial (is_question). Significado preservado (no ubica oficina).
    ("BQ-L18", "no ubico la oficina pa firmar aonde kae uno", "onboarding_process"),
]


@pytest.mark.parametrize("cid,message,intent_family", LLM_ONLY, ids=[c[0] for c in LLM_ONLY])
def test_llm_only_preflight_no_cheap_signal(cid, message, intent_family):
    """Regla 1+2: el caso NO debe activar señal barata (ni `?` ni término regex)."""
    tr = _trace(message, _Signals(has_embedded_question=False))
    assert tr["is_question"] is False, f"{cid}: viola is_question==false"
    assert tr["business_term_regex_hit"] is False, f"{cid}: viola business_term_regex_hit==false"


@pytest.mark.parametrize("cid,message,intent_family", LLM_ONLY, ids=[c[0] for c in LLM_ONLY])
def test_llm_only_causality_is_llm_signal(cid, message, intent_family):
    """Regla 3: dos corridas. Control (señal=false) NO detecta; objetivo (señal=true)
    detecta. El cambio proviene EXCLUSIVAMENTE de has_embedded_question."""
    control = has_business_question(message, _Signals(has_embedded_question=False))
    target = has_business_question(message, _Signals(has_embedded_question=True))
    assert control is False, f"{cid}: control detectó sin señal LLM (fuga de regex/?)"
    assert target is True, f"{cid}: objetivo no detectó con señal LLM"
