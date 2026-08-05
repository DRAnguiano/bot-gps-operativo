"""agent_decision_validator — frontera de autoridad EN CÓDIGO (controlled-agentic-
profiling, Bloque 2, design.md D2).

El modelo PROPONE (AgentDecision); este módulo CERTIFICA. Ningún proposed_fact
llega a persistencia sin pasar, en orden:
  1. Evidencia literal en el mensaje del turno.
  2. Confidence mínima (AGENT_FACT_MIN_CONFIDENCE).
  3. Capa 2 existente (`turn_extractor.validate_extraction`) — el MISMO camino de
     persistencia que usa el extractor determinista, nunca un bypass.
  4. Contradicción contra el fact previo sin marcador explícito de corrección.

Labels y `perfil_listo` NO se tocan aquí — siguen saliendo EXCLUSIVAMENTE de
`calculate_candidate_labels`/`profile_funnel_complete` sobre facts certificados.
`handoff_recommendation` es solo-activar: `resolve_handoff` nunca puede apagar un
`requires_human` ya decidido por overrides deterministas (B1, reingreso, edad).

Estado: SHADOW. Este módulo se invoca desde el hook de logging (Bloque 3), no
desde el camino de escritura real.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

from app.knowledge.agent_decision import AgentDecision, ProposedFact
from app.knowledge.text_normalizer import normalize_text

log = logging.getLogger(__name__)


def _min_confidence() -> float:
    try:
        return float(os.getenv("AGENT_FACT_MIN_CONFIDENCE", "0.7"))
    except ValueError:
        return 0.7


@dataclass
class RejectedFact:
    field: str
    value: str
    reason: str  # "no_evidence" | "low_confidence" | "capa2_invalid" | "contradiction"


@dataclass
class ValidatedAgentDecision:
    certified_facts: list[dict[str, Any]] = field(default_factory=list)
    rejected_facts: list[RejectedFact] = field(default_factory=list)
    uncertainty_flags: list[str] = field(default_factory=list)
    handoff_recommended: bool = False
    handoff_reason: str | None = None


def _has_literal_evidence(pf: ProposedFact, raw_message: str) -> bool:
    """D2.1: evidence debe ser substring (normalizado) del mensaje del turno."""
    if not pf.evidence:
        return False
    ev = normalize_text(pf.evidence)
    msg = normalize_text(raw_message)
    return bool(ev) and ev in msg


def _has_contradiction(pf: ProposedFact, known_facts: dict[str, Any]) -> bool:
    """D2.4: valor distinto al fact previo, sin marcador explícito de corrección.

    AgentDecision (Bloque 1) no emite un flag de corrección por proposed_fact —
    por diseño CONSERVADOR, toda discrepancia contra un fact previo se trata como
    NO corrección (no sobrescribe) hasta que el schema lo justifique.
    """
    prev = known_facts.get(pf.field)
    if prev in (None, ""):
        return False
    return normalize_text(str(prev)) != normalize_text(pf.value)


def _run_capa2(surviving: list[ProposedFact], known_facts: dict[str, Any]) -> tuple[list[dict[str, Any]], set[str]]:
    """Entrega los facts que pasaron evidencia+confidence al MISMO validate_extraction
    del extractor determinista — un solo camino de persistencia, nunca un bypass."""
    from app.knowledge.turn_extractor import FieldValue, TurnExtraction, validate_extraction

    if not surviving:
        return [], set()
    fields = {
        pf.field: FieldValue(value=pf.value, explicit_marker=True, answered_direct_question=False)
        for pf in surviving
    }
    synthetic = TurnExtraction(fields=fields)
    certified = validate_extraction(synthetic, known_facts)
    certified_keys = {f"{c['fact_group']}.{c['fact_key']}" for c in certified}
    return certified, certified_keys


def validate_agent_decision(
    decision: AgentDecision,
    *,
    raw_message: str,
    known_facts: dict[str, Any] | None = None,
    deterministic_requires_human: bool = False,
) -> ValidatedAgentDecision:
    known = known_facts or {}
    result = ValidatedAgentDecision(uncertainty_flags=list(decision.uncertainty_flags))

    # 1) Evidencia literal + 2) confidence mínima.
    min_conf = _min_confidence()
    survivors: list[ProposedFact] = []
    for pf in decision.proposed_facts:
        if not _has_literal_evidence(pf, raw_message):
            result.rejected_facts.append(RejectedFact(pf.field, pf.value, "no_evidence"))
            log.info("[AGENT_FACT_REJECTED] field=%s value=%r reason=no_evidence", pf.field, pf.value)
            continue
        if pf.confidence < min_conf:
            result.rejected_facts.append(RejectedFact(pf.field, pf.value, "low_confidence"))
            log.info("[AGENT_FACT_REJECTED] field=%s value=%r reason=low_confidence confidence=%.2f",
                      pf.field, pf.value, pf.confidence)
            continue
        survivors.append(pf)

    # 4) Contradicción — se separa ANTES de Capa 2 para no persistir un pisado silencioso.
    non_contradicting: list[ProposedFact] = []
    for pf in survivors:
        if _has_contradiction(pf, known):
            result.uncertainty_flags.append(
                f"{pf.field}: propuesto={pf.value!r} vs conocido={known.get(pf.field)!r}"
            )
            result.rejected_facts.append(RejectedFact(pf.field, pf.value, "contradiction"))
            log.info("[AGENT_FACT_REJECTED] field=%s value=%r reason=contradiction previo=%r",
                      pf.field, pf.value, known.get(pf.field))
            continue
        non_contradicting.append(pf)

    # 3) Capa 2 existente — único camino de persistencia.
    certified, certified_keys = _run_capa2(non_contradicting, known)
    result.certified_facts = certified
    for pf in non_contradicting:
        if pf.field not in certified_keys:
            result.rejected_facts.append(RejectedFact(pf.field, pf.value, "capa2_invalid"))
            log.info("[AGENT_FACT_REJECTED] field=%s value=%r reason=capa2_invalid", pf.field, pf.value)

    # Handoff: SOLO-ACTIVAR (D2). Nunca apaga un requires_human determinista.
    result.handoff_recommended = deterministic_requires_human or bool(decision.handoff_recommendation.recommended)
    result.handoff_reason = decision.handoff_recommendation.reason if decision.handoff_recommendation.recommended else None

    return result


def resolve_handoff(deterministic_requires_human: bool, decision: AgentDecision) -> bool:
    """Helper standalone (D2): OR puro — el agente solo puede ACTIVAR, nunca desactivar."""
    return deterministic_requires_human or bool(decision.handoff_recommendation.recommended)


def build_shadow_log(
    *,
    conversation_key: str,
    agent_decision: AgentDecision,
    validated: ValidatedAgentDecision,
    funnel_question: str,
    funnel_missing_labels: list[str],
    deterministic_fact_keys: set[str],
    deterministic_requires_human: bool,
) -> dict[str, Any]:
    """Payload puro (sin I/O) del log `[AGENTIC_SHADOW]` (Bloque 3, design.md D3).

    Extraído como función pura para poder testear la construcción del diff sin
    levantar `handle_message` completo (requiere DB real por diseño — ver su
    docstring). El hook en el orchestrator solo llama esto y hace `log.info`.
    """
    agent_keys = {f"{c['fact_group']}.{c['fact_key']}" for c in validated.certified_facts}
    agent_next_field = (
        agent_decision.next_action.split(":", 1)[1]
        if agent_decision.next_action and agent_decision.next_action.startswith("ask_field:")
        else None
    )
    return {
        "conversation_key": conversation_key,
        # La pregunta del funnel es TEXTO y el next_action del agente es un CAMPO
        # canónico — no son comparables por igualdad; se loguean ambos crudos para
        # revisión humana (gate 4.1 de tasks.md), no como un booleano "acertó".
        "funnel_question": funnel_question[:200],
        "agent_next_action": agent_decision.next_action,
        "agent_next_field": agent_next_field,
        "agent_public_reply": (agent_decision.public_reply or "")[:200],
        "facts_only_deterministic": sorted(deterministic_fact_keys - agent_keys),
        "facts_only_agent": sorted(agent_keys - deterministic_fact_keys),
        "facts_agreed": sorted(deterministic_fact_keys & agent_keys),
        "missing_diff": {
            "funnel_missing": funnel_missing_labels,
            "agent_missing": agent_decision.missing_fields,
        },
        "rejected_facts": [
            {"field": r.field, "value": r.value, "reason": r.reason} for r in validated.rejected_facts
        ],
        "uncertainty_flags": validated.uncertainty_flags,
        "handoff_deterministic": deterministic_requires_human,
        "handoff_agent_recommended": agent_decision.handoff_recommendation.recommended,
        "handoff_diff": validated.handoff_recommended != deterministic_requires_human,
        "crm_note": agent_decision.crm_private_note,
    }
