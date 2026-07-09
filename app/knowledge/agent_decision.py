"""AgentDecision — conducción agéntica controlada del turno (controlled-agentic-
profiling, Bloque 1).

Principio (design.md D1): el modelo conduce la conversación; el sistema certifica
el perfil. AgentDecision es la salida estructurada de UNA llamada LLM — la MISMA
del extractor unificado (`turn_extractor.extract_turn`), sin costo extra de cuota.
Este módulo SOLO define el schema y el parsing tolerante; la validación de
autoridad (evidencia, confidence, Capa 2, contradicciones) vive en
`agent_decision_validator.py` (Bloque 2) — AgentDecision por sí solo NO tiene
permiso de escribir nada.

Estado: SHADOW. Nada de este módulo está wireado al reply/labels/Nota IA vivos
todavía (ver tasks.md Bloque 3).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Catálogo cerrado de next_action — cualquier valor fuera de este set se trata
# como ausente (D5: el turno degrada al funnel determinista, nunca se inventa
# una acción nueva desde el JSON del LLM).
_NEXT_ACTIONS = {
    "ask_field", "answer_question", "acknowledge", "close_profile", "handoff", "wait",
}


@dataclass
class ProposedFact:
    """Un dato que el agente CREE haber visto en el turno — no certificado.

    ``evidence`` debe ser, en teoría, un substring literal del mensaje del turno;
    la verificación real (D2.1) vive en agent_decision_validator, no aquí.
    """
    field: str
    value: str
    evidence: str = ""
    confidence: float = 0.0


@dataclass
class HandoffRecommendation:
    recommended: bool = False
    reason: str | None = None


@dataclass
class AgentDecision:
    """Salida estructurada del turno agéntico (design.md D1)."""
    public_reply: str = ""
    proposed_facts: list[ProposedFact] = field(default_factory=list)
    next_action: str | None = None
    missing_fields: list[str] = field(default_factory=list)
    uncertainty_flags: list[str] = field(default_factory=list)
    crm_private_note: str | None = None
    handoff_recommendation: HandoffRecommendation = field(default_factory=HandoffRecommendation)


def _parse_proposed_fact(raw: Any) -> ProposedFact | None:
    if not isinstance(raw, dict):
        return None
    fname = raw.get("field")
    fvalue = raw.get("value")
    if not fname or fvalue in (None, "", "null"):
        return None
    try:
        confidence = float(raw.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    return ProposedFact(
        field=str(fname).strip(),
        value=str(fvalue).strip(),
        evidence=str(raw.get("evidence") or "").strip(),
        confidence=confidence,
    )


def _parse_handoff(raw: Any) -> HandoffRecommendation:
    if not isinstance(raw, dict):
        return HandoffRecommendation()
    return HandoffRecommendation(
        recommended=bool(raw.get("recommended", False)),
        reason=(str(raw["reason"]).strip() if raw.get("reason") else None),
    )


def parse_agent_decision(raw: Any) -> AgentDecision:
    """Parsing tolerante: cualquier campo ausente o malformado cae a su default
    neutro — un AgentDecision incompleto/vacío NUNCA lanza, solo aporta menos.
    Consistente con el fail-safe del extractor unificado (D-degradación)."""
    if not isinstance(raw, dict):
        return AgentDecision()

    facts_raw = raw.get("proposed_facts")
    proposed_facts: list[ProposedFact] = []
    if isinstance(facts_raw, list):
        for item in facts_raw:
            parsed = _parse_proposed_fact(item)
            if parsed is not None:
                proposed_facts.append(parsed)

    next_action = raw.get("next_action")
    next_action = str(next_action).strip() if next_action else None
    if next_action:
        # "ask_field:candidate.city" → catálogo valida solo el prefijo.
        _base = next_action.split(":", 1)[0]
        if _base not in _NEXT_ACTIONS:
            next_action = None

    missing_fields = raw.get("missing_fields")
    missing_fields = (
        [str(m).strip() for m in missing_fields if m]
        if isinstance(missing_fields, list) else []
    )

    uncertainty_flags = raw.get("uncertainty_flags")
    uncertainty_flags = (
        [str(u).strip() for u in uncertainty_flags if u]
        if isinstance(uncertainty_flags, list) else []
    )

    crm_note = raw.get("crm_private_note")
    crm_note = str(crm_note).strip() if crm_note not in (None, "", "null") else None

    public_reply = raw.get("public_reply")
    public_reply = str(public_reply).strip() if public_reply else ""

    return AgentDecision(
        public_reply=public_reply,
        proposed_facts=proposed_facts,
        next_action=next_action,
        missing_fields=missing_fields,
        uncertainty_flags=uncertainty_flags,
        crm_private_note=crm_note,
        handoff_recommendation=_parse_handoff(raw.get("handoff_recommendation")),
    )
