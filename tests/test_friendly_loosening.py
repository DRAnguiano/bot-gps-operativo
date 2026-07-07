"""Aflojar respuestas enlatadas (bug en vivo conv 166, 2026-07-07).

Cubre:
- El chiste se detecta por la señal `is_joke_request` del extractor unificado
  (misma llamada LLM del turno — sin llamada dedicada ni substring rígido) y tiene
  prioridad sobre un requires_rag mal clasificado por overlap de aliases.
- _should_use_friendly_llm ampliado: catch-all va a LLM cálido, no a texto enlatado,
  salvo greeting/candidate_profile_signal/requires_clarification (ramas dedicadas).
- Los guardrails de seguridad siguen intactos.
"""
from __future__ import annotations

from app.knowledge.turn_intent_classifier import TurnIntentSignals
from app.orchestrators import knowledge_orchestrator as KO


# ── señal is_joke_request del extractor (no substring, no Term Neo4j) ──────────

def test_joke_signal_lives_in_unified_extractor():
    # La señal existe en el dataclass y default False — el LLM la decide por
    # few-shot en la MISMA llamada del clasificador (cero costo extra).
    s = TurnIntentSignals()
    assert s.is_joke_request is False
    s2 = TurnIntentSignals(is_joke_request=True)
    assert s2.is_joke_request is True


def test_safety_gate_blocks_joke_on_risky_turn():
    # Aunque el extractor marque chiste, un turno de riesgo no va al humor.
    contract = {"requires_human": True, "risk_level": "high"}
    assert KO._is_safe_for_friendly_llm("cuéntame un chiste", contract) is False


# ── _should_use_friendly_llm ampliado ──────────────────────────────────────────

def _contract(**over):
    base = {"route": "info", "intent": "some_faq_intent", "risk_level": "low",
            "requires_human": False, "requires_clarification": False}
    base.update(over)
    return base


def test_widened_catchall_goes_friendly():
    assert KO._should_use_friendly_llm("algo ambiguo", _contract()) is True


def test_greeting_still_excluded_from_widened_catchall():
    assert KO._should_use_friendly_llm("hola", _contract(intent="greeting")) is False


def test_profile_signal_still_excluded_from_widened_catchall():
    assert KO._should_use_friendly_llm(
        "full", _contract(intent="candidate_profile_signal")
    ) is False


def test_requires_clarification_still_excluded():
    assert KO._should_use_friendly_llm(
        "?", _contract(requires_clarification=True)
    ) is False


def test_requires_human_still_blocked_by_safety_gate():
    assert KO._should_use_friendly_llm(
        "algo delicado", _contract(requires_human=True)
    ) is False


def test_high_risk_still_blocked_by_safety_gate():
    assert KO._should_use_friendly_llm(
        "algo riesgoso", _contract(risk_level="high")
    ) is False
