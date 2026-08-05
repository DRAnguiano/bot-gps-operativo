"""B8 — correcciones explícitas en el camino vivo (Fase 2, deterministas, sin Groq/DB).

Fija el contrato de `live-reply-grounding-and-quality` B8 al nivel en que el camino
vivo decide (guards deterministas de `knowledge_orchestrator` + extractor único), SIN
duplicar la maquinaria LLM de `fact_corrections.py` (shadow/multi-intent 7.2/7.4).

Escenarios B8.3:
  (a) "en realidad es sencillo" tras "full" → sencillo, sin escuelita.
  (b) "10 años" tras escuelita → no escuelita.

Hechos verificados del camino vivo (no se re-prueban aquí, se asumen):
  - `upsert_lead_fact` (repository) hace ON CONFLICT DO UPDATE SET fact_value=EXCLUDED →
    el valor corregido pisa al previo a nivel BD.
  - La señal escuelita se recalcula por turno desde el texto actual (no es sticky en la
    señal); el gap es el LABEL previo que no se limpia al confirmar un objetivo.
"""
from __future__ import annotations

import pytest

import app.orchestrators.knowledge_orchestrator as KO
import app.lead_memory.profile_extractor as PE
from app.knowledge.current_turn import next_question_from_missing_facts


def _baseline_contract() -> dict:
    return {
        "route": "profile",
        "intent": "candidate_profile_signal",
        "risk_level": "low",
        "requires_human": False,
        "requires_rag": False,
    }


# ---------------------------------------------------------------------------
# B8.1/B8.3a — la corrección con el valor nuevo presente se extrae como vehicle_type.
# (lock-in: el overwrite a BD lo hace el upsert; aquí fijamos que el extractor saca
#  el valor corregido del mensaje.)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("message,expected", [
    ("en realidad es sencillo", "sencillo"),
    ("no, mejor dicho manejo full", "full"),
    ("me equivoqué, es sencillo", "sencillo"),
])
def test_correction_extracts_new_vehicle_type(message, expected):
    facts = PE.extract_profile_facts_as_dict(message)
    assert facts.get("experience.vehicle_type") == expected


# ---------------------------------------------------------------------------
# B8.3a — un objetivo válido (full/sencillo) NUNCA dispara escuelita.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("message", [
    "en realidad es sencillo",
    "no, manejo full",
])
def test_target_vehicle_does_not_emit_escuelita(message):
    out = KO._apply_business_rule_overrides(message, _baseline_contract())
    assert "considerar_escuelita_transmontes" not in (out.get("business_signals") or [])


# ---------------------------------------------------------------------------
# B8.3b — un turno de experiencia ("10 años") tras escuelita no re-emite la señal.
# ---------------------------------------------------------------------------

def test_experience_years_turn_does_not_emit_escuelita():
    out = KO._apply_business_rule_overrides("ya tengo 10 años manejando", _baseline_contract())
    assert "considerar_escuelita_transmontes" not in (out.get("business_signals") or [])


# ---------------------------------------------------------------------------
# B8.1/B8.3 (GAP / RED) — al confirmar un objetivo claro, la escuelita PREVIA debe
# limpiarse. Hoy el guard solo AÑADE la señal en términos no-objetivo; no la retira
# cuando un turno posterior corrige a full/sencillo → el label queda pegado.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("message", [
    "en realidad es full",
    "no, manejo sencillo",
])
def test_target_vehicle_clears_prior_escuelita(message):
    contract = _baseline_contract()
    contract["business_signals"] = ["considerar_escuelita_transmontes"]
    out = KO._apply_business_rule_overrides(message, contract)
    assert "considerar_escuelita_transmontes" not in (out.get("business_signals") or [])


# ---------------------------------------------------------------------------
# B8.1 — "persistir las preguntas sin hostigar": tras corregir el vehicle_type, el slot
# sigue lleno (con el valor corregido) → el funnel NO re-pregunta la unidad, avanza.
# ---------------------------------------------------------------------------

def test_corrected_vehicle_type_is_not_reasked():
    facts = {
        "candidate.name": "Juan Pérez",
        "candidate.city": "Torreón",
        "candidate.age": "35",
        "experience.vehicle_type": "sencillo",  # valor corregido (antes "full")
    }
    q = next_question_from_missing_facts(facts)
    assert "tracto full o en sencillo" not in q  # no re-pregunta la unidad ya respondida
    assert "licencia" in q.lower()               # avanza al siguiente campo pendiente
