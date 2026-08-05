"""controlled-agentic-profiling Bloque 2 — frontera de autoridad (design.md D2).

Deterministas, sin LLM/DB. Cubre el pipeline completo: evidencia literal →
confidence mínima → contradicción → Capa 2 existente (validate_extraction) — y
que ningún camino del agente pueda escribir labels/perfil_listo directamente ni
desactivar un handoff determinista.
"""
from __future__ import annotations

from app.knowledge.agent_decision import AgentDecision, HandoffRecommendation, ProposedFact
from app.knowledge.agent_decision_validator import (
    build_shadow_log,
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


# ── build_shadow_log (Bloque 3) — payload puro del [AGENTIC_SHADOW] ────────────

def test_shadow_log_reports_facts_agreement_and_diff():
    d = _decision(
        facts=[("candidate.city", "Torreón", "soy de torreón", 0.9)],
        next_action="ask_field:candidate.age",
        missing_fields=["candidate.age"],
    )
    validated = validate_agent_decision(d, raw_message="soy de torreón")
    out = build_shadow_log(
        conversation_key="chatwoot:1",
        agent_decision=d,
        validated=validated,
        funnel_question="¿Cuál es su edad?",
        funnel_missing_labels=["edad"],
        deterministic_fact_keys=set(),
        deterministic_requires_human=False,
    )
    assert out["conversation_key"] == "chatwoot:1"
    assert out["facts_only_agent"] == ["candidate.city"]
    assert out["facts_agreed"] == []
    assert out["agent_next_field"] == "candidate.age"
    assert out["funnel_question"] == "¿Cuál es su edad?"
    assert out["missing_diff"] == {"funnel_missing": ["edad"], "agent_missing": ["candidate.age"]}


def test_shadow_log_agent_next_field_none_for_non_ask_field_action():
    d = _decision(next_action="close_profile")
    validated = validate_agent_decision(d, raw_message="ok")
    out = build_shadow_log(
        conversation_key="chatwoot:1", agent_decision=d, validated=validated,
        funnel_question="", funnel_missing_labels=[], deterministic_fact_keys=set(),
        deterministic_requires_human=False,
    )
    assert out["agent_next_field"] is None
    assert out["agent_next_action"] == "close_profile"


def test_shadow_log_handoff_diff_true_when_agent_disagrees():
    d = _decision(handoff_recommendation=HandoffRecommendation(recommended=True, reason="duda"))
    validated = validate_agent_decision(d, raw_message="hola", deterministic_requires_human=False)
    out = build_shadow_log(
        conversation_key="chatwoot:1", agent_decision=d, validated=validated,
        funnel_question="", funnel_missing_labels=[], deterministic_fact_keys=set(),
        deterministic_requires_human=False,
    )
    assert out["handoff_deterministic"] is False
    assert out["handoff_agent_recommended"] is True
    assert out["handoff_diff"] is True


def test_shadow_log_includes_rejected_facts_and_uncertainty():
    d = _decision(facts=[("candidate.age", "15", "tengo 15 años", 0.9)])
    validated = validate_agent_decision(d, raw_message="tengo 15 años")
    out = build_shadow_log(
        conversation_key="chatwoot:1", agent_decision=d, validated=validated,
        funnel_question="", funnel_missing_labels=[], deterministic_fact_keys=set(),
        deterministic_requires_human=False,
    )
    assert out["rejected_facts"] == [{"field": "candidate.age", "value": "15", "reason": "capa2_invalid"}]


def test_shadow_hook_runs_after_reply_persisted_and_before_return():
    # Contrato estructural (D3): el hook AGENTIC_PROFILING_SHADOW debe vivir
    # DESPUÉS de save_message(..., "assistant", reply) — para no poder influir en
    # lo que ya se envió/persistió — y ANTES del return del payload. Read-only.
    import inspect
    from app.orchestrators import knowledge_orchestrator as KO

    src = inspect.getsource(KO.handle_message)
    save_idx = src.index('save_message(conversation_key, "assistant", reply)')
    shadow_idx = src.index('AGENTIC_PROFILING_SHADOW')
    return_idx = src.rindex("\n    return {")
    assert save_idx < shadow_idx < return_idx
    # El hook está envuelto en try/except (nunca puede romper el turno).
    shadow_block = src[shadow_idx:return_idx]
    assert "except Exception" in shadow_block


def test_shadow_log_truncates_long_text_fields():
    long_reply = "x" * 500
    d = _decision(public_reply=long_reply)
    validated = validate_agent_decision(d, raw_message="hola")
    out = build_shadow_log(
        conversation_key="chatwoot:1", agent_decision=d, validated=validated,
        funnel_question="y" * 500, funnel_missing_labels=[], deterministic_fact_keys=set(),
        deterministic_requires_human=False,
    )
    assert len(out["agent_public_reply"]) == 200
    assert len(out["funnel_question"]) == 200


def test_calculate_candidate_labels_has_zero_agent_coupling():
    # Contrato estructural (D2): calculate_candidate_labels es la ÚNICA fuente de
    # labels y no debe importar/mencionar nada del módulo agéntico — si un futuro
    # cambio introduce esa dependencia, este test lo detecta.
    import inspect
    from app import chatwoot_note_sync
    src = inspect.getsource(chatwoot_note_sync)
    assert "agent_decision" not in src
    assert "AgentDecision" not in src
