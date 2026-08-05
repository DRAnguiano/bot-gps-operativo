"""controlled-agentic-profiling Bloque 1 — schema y parsing de AgentDecision.

Deterministas, sin LLM/DB. La validación de AUTORIDAD (evidencia, confidence,
Capa 2, contradicciones) es el Bloque 2 (agent_decision_validator) — aquí solo se
prueba que el parsing es tolerante y nunca lanza.
"""
from __future__ import annotations

from app.knowledge.agent_decision import (
    AgentDecision,
    HandoffRecommendation,
    ProposedFact,
    parse_agent_decision,
)


def test_full_decision_parses_all_fields():
    raw = {
        "public_reply": "Va, ¿en qué ciudad se encuentra?",
        "proposed_facts": [
            {"field": "candidate.city", "value": "Torreón", "evidence": "soy de Torreón", "confidence": 0.9},
        ],
        "next_action": "ask_field:candidate.age",
        "missing_fields": ["candidate.age", "license.category"],
        "uncertainty_flags": ["ciudad ambigua"],
        "crm_private_note": "candidato con buena disposición",
        "handoff_recommendation": {"recommended": False, "reason": None},
    }
    d = parse_agent_decision(raw)
    assert d.public_reply == "Va, ¿en qué ciudad se encuentra?"
    assert d.proposed_facts == [
        ProposedFact(field="candidate.city", value="Torreón", evidence="soy de Torreón", confidence=0.9)
    ]
    assert d.next_action == "ask_field:candidate.age"
    assert d.missing_fields == ["candidate.age", "license.category"]
    assert d.uncertainty_flags == ["ciudad ambigua"]
    assert d.crm_private_note == "candidato con buena disposición"
    assert d.handoff_recommendation == HandoffRecommendation(recommended=False, reason=None)


def test_empty_dict_returns_neutral_defaults():
    d = parse_agent_decision({})
    assert d.public_reply == ""
    assert d.proposed_facts == []
    assert d.next_action is None
    assert d.missing_fields == []
    assert d.uncertainty_flags == []
    assert d.crm_private_note is None
    assert d.handoff_recommendation.recommended is False


def test_non_dict_input_never_raises():
    for bad in (None, "no es json", 42, ["lista"]):
        d = parse_agent_decision(bad)
        assert isinstance(d, AgentDecision)


def test_malformed_proposed_fact_is_dropped_not_crashed():
    raw = {"proposed_facts": [
        {"field": "candidate.city"},  # sin value → se descarta
        {"value": "Torreón"},         # sin field → se descarta
        "no es un dict",              # tipo incorrecto → se descarta
        {"field": "candidate.age", "value": "30"},  # válido, confidence default 0.0
    ]}
    d = parse_agent_decision(raw)
    assert len(d.proposed_facts) == 1
    assert d.proposed_facts[0].field == "candidate.age"
    assert d.proposed_facts[0].confidence == 0.0


def test_confidence_non_numeric_defaults_to_zero():
    raw = {"proposed_facts": [{"field": "candidate.city", "value": "Torreón", "confidence": "alta"}]}
    d = parse_agent_decision(raw)
    assert d.proposed_facts[0].confidence == 0.0


def test_next_action_outside_catalog_becomes_none():
    # D5: un next_action inventado por el LLM no debe convertirse en una acción
    # nueva del sistema — el turno degrada al funnel determinista.
    raw = {"next_action": "aprobar_candidato"}
    d = parse_agent_decision(raw)
    assert d.next_action is None


def test_next_action_with_field_suffix_validates_prefix():
    raw = {"next_action": "ask_field:license.category"}
    d = parse_agent_decision(raw)
    assert d.next_action == "ask_field:license.category"


def test_next_action_close_profile_valid():
    raw = {"next_action": "close_profile"}
    d = parse_agent_decision(raw)
    assert d.next_action == "close_profile"


def test_handoff_missing_defaults_to_not_recommended():
    d = parse_agent_decision({"handoff_recommendation": "no es un dict"})
    assert d.handoff_recommendation == HandoffRecommendation(recommended=False, reason=None)


def test_handoff_recommended_with_reason():
    raw = {"handoff_recommendation": {"recommended": True, "reason": "mencionó B1"}}
    d = parse_agent_decision(raw)
    assert d.handoff_recommendation.recommended is True
    assert d.handoff_recommendation.reason == "mencionó B1"


def test_crm_note_null_string_becomes_none():
    for empty in (None, "", "null"):
        d = parse_agent_decision({"crm_private_note": empty})
        assert d.crm_private_note is None


def test_missing_fields_filters_falsy_entries():
    raw = {"missing_fields": ["candidate.age", "", None, "license.category"]}
    d = parse_agent_decision(raw)
    assert d.missing_fields == ["candidate.age", "license.category"]
