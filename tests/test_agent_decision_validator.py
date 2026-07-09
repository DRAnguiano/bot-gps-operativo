"""controlled-agentic-profiling Bloque 2 — frontera de autoridad (design.md D2).

Deterministas, sin LLM/DB. Cubre el pipeline completo: evidencia literal →
confidence mínima → contradicción → Capa 2 existente (validate_extraction) — y
que ningún camino del agente pueda escribir labels/perfil_listo directamente ni
desactivar un handoff determinista.
"""
from __future__ import annotations

from app.knowledge.agent_decision import AgentDecision, HandoffRecommendation, ProposedFact
from app.knowledge.agent_decision_validator import (
    resolve_handoff,
    validate_agent_decision,
)


def _decision(**facts_kwargs) -> AgentDecision:
    facts = [
        ProposedFact(field=f, value=v, evidence=e, confidence=c)
        for f, v, e, c in facts_kwargs.get("facts", [])
    ]
    return AgentDecision(proposed_facts=facts, **{k: v for k, v in facts_kwargs.items() if k != "facts"})


# ── D2.1: evidencia literal ────────────────────────────────────────────────────

def test_fact_with_literal_evidence_survives_to_capa2():
    d = _decision(facts=[("candidate.city", "Torreón", "soy de torreón", 0.9)])
    out = validate_agent_decision(d, raw_message="hola, soy de torreón y busco chamba")
    assert any(c["fact_key"] == "city" for c in out.certified_facts)
    assert out.rejected_facts == []


def test_fact_without_evidence_in_message_is_rejected():
    d = _decision(facts=[("candidate.city", "Torreón", "vivo en Torreón", 0.9)])
    out = validate_agent_decision(d, raw_message="mi nombre es Juan Pérez")
    assert out.certified_facts == []
    assert out.rejected_facts[0].reason == "no_evidence"


def test_evidence_check_is_accent_and_case_insensitive():
    d = _decision(facts=[("candidate.city", "Torreón", "SOY DE TORREON", 0.9)])
    out = validate_agent_decision(d, raw_message="soy de torreón, mucho gusto")
    assert any(c["fact_key"] == "city" for c in out.certified_facts)


def test_empty_evidence_always_rejected():
    d = _decision(facts=[("candidate.city", "Torreón", "", 0.95)])
    out = validate_agent_decision(d, raw_message="soy de torreón")
    assert out.rejected_facts[0].reason == "no_evidence"


# ── D2.2: confidence mínima ─────────────────────────────────────────────────────

def test_low_confidence_fact_is_rejected():
    d = _decision(facts=[("candidate.city", "Torreón", "soy de torreón", 0.5)])
    out = validate_agent_decision(d, raw_message="soy de torreón")
    assert out.certified_facts == []
    assert out.rejected_facts[0].reason == "low_confidence"


def test_confidence_at_threshold_survives():
    d = _decision(facts=[("candidate.city", "Torreón", "soy de torreón", 0.7)])
    out = validate_agent_decision(d, raw_message="soy de torreón")
    assert any(c["fact_key"] == "city" for c in out.certified_facts)


def test_custom_min_confidence_env(monkeypatch):
    monkeypatch.setenv("AGENT_FACT_MIN_CONFIDENCE", "0.95")
    d = _decision(facts=[("candidate.city", "Torreón", "soy de torreón", 0.8)])
    out = validate_agent_decision(d, raw_message="soy de torreón")
    assert out.rejected_facts[0].reason == "low_confidence"


# ── D2.3: Capa 2 existente — mismo camino, catálogos vigentes ──────────────────

def test_license_a_does_not_certify_same_as_deterministic_extractor():
    # Regla vigente: A no satisface license.category (queda como category_raw).
    d = _decision(facts=[("license.category", "A", "traigo la A", 0.95)])
    out = validate_agent_decision(d, raw_message="traigo la A")
    assert not any(c["fact_key"] == "category" and c["fact_group"] == "license" for c in out.certified_facts)


def test_license_e_certifies_via_capa2():
    d = _decision(facts=[("license.category", "E", "tengo la E", 0.9)])
    out = validate_agent_decision(d, raw_message="tengo la E")
    assert any(c["fact_group"] == "license" and c["fact_key"] == "category" and c["fact_value"] == "E"
               for c in out.certified_facts)


def test_age_out_of_range_rejected_by_capa2():
    d = _decision(facts=[("candidate.age", "15", "tengo 15 años", 0.9)])
    out = validate_agent_decision(d, raw_message="tengo 15 años")
    assert out.certified_facts == []
    assert any(r.reason == "capa2_invalid" for r in out.rejected_facts)


def test_doble_articulado_maps_to_full_via_catalog():
    d = _decision(facts=[("experience.vehicle_type", "doble articulado", "manejo doble articulado", 0.9)])
    out = validate_agent_decision(d, raw_message="manejo doble articulado")
    assert any(c["fact_value"] == "full" for c in out.certified_facts)


# ── D2.4: contradicción sin corrección explícita ────────────────────────────────

def test_contradicting_fact_does_not_overwrite_and_flags_uncertainty():
    d = _decision(facts=[("experience.vehicle_type", "sencillo", "manejo sencillo", 0.9)])
    out = validate_agent_decision(
        d, raw_message="manejo sencillo", known_facts={"experience.vehicle_type": "full"}
    )
    assert out.certified_facts == []
    assert any(r.reason == "contradiction" for r in out.rejected_facts)
    assert any("experience.vehicle_type" in f for f in out.uncertainty_flags)


def test_same_value_as_known_is_not_a_contradiction():
    d = _decision(facts=[("candidate.city", "Torreón", "soy de torreón", 0.9)])
    out = validate_agent_decision(
        d, raw_message="soy de torreón", known_facts={"candidate.city": "Torreón"}
    )
    assert any(c["fact_key"] == "city" for c in out.certified_facts)


def test_no_prior_fact_is_not_a_contradiction():
    d = _decision(facts=[("candidate.city", "Torreón", "soy de torreón", 0.9)])
    out = validate_agent_decision(d, raw_message="soy de torreón", known_facts={})
    assert any(c["fact_key"] == "city" for c in out.certified_facts)


# ── Frontera dura: labels/perfil_listo nunca vienen de aquí ────────────────────

def test_validator_output_never_contains_label_or_stage_keys():
    # ValidatedAgentDecision no expone ningún campo de labels/perfil_listo — la
    # única salida persistible es certified_facts, en el mismo formato de
    # validate_extraction (fact_group/fact_key/fact_value/confidence).
    d = _decision(facts=[("candidate.city", "Torreón", "soy de torreón", 0.9)])
    out = validate_agent_decision(d, raw_message="soy de torreón")
    assert not hasattr(out, "labels")
    assert not hasattr(out, "perfil_listo")
    for c in out.certified_facts:
        assert set(c.keys()) <= {"fact_group", "fact_key", "fact_value", "confidence", "is_explicit_correction"}


# ── Handoff solo-activar ────────────────────────────────────────────────────────

def test_handoff_cannot_deactivate_deterministic_requires_human():
    d = AgentDecision(handoff_recommendation=HandoffRecommendation(recommended=False))
    assert resolve_handoff(deterministic_requires_human=True, decision=d) is True


def test_handoff_can_activate_when_deterministic_is_false():
    d = AgentDecision(handoff_recommendation=HandoffRecommendation(recommended=True, reason="duda seria"))
    assert resolve_handoff(deterministic_requires_human=False, decision=d) is True


def test_handoff_stays_false_when_neither_side_flags():
    d = AgentDecision(handoff_recommendation=HandoffRecommendation(recommended=False))
    assert resolve_handoff(deterministic_requires_human=False, decision=d) is False


def test_validate_agent_decision_reflects_deterministic_override_in_result():
    d = _decision(handoff_recommendation=HandoffRecommendation(recommended=False))
    out = validate_agent_decision(d, raw_message="hola", deterministic_requires_human=True)
    assert out.handoff_recommended is True


def test_calculate_candidate_labels_has_zero_agent_coupling():
    # Contrato estructural (D2): calculate_candidate_labels es la ÚNICA fuente de
    # labels y no debe importar/mencionar nada del módulo agéntico — si un futuro
    # cambio introduce esa dependencia, este test lo detecta.
    import inspect
    from app import chatwoot_note_sync
    src = inspect.getsource(chatwoot_note_sync)
    assert "agent_decision" not in src
    assert "AgentDecision" not in src
