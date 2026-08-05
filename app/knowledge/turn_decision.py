"""TurnDecision — única salida inmutable de un turno del candidato
(unified-turn-decision-v2-projection, Fase 1 / D1).

Objeto PURO (sin BD/LLM/red). La orquestación construye UNA sola instancia por turno;
el worker solo la ENTREGA (persistir facts + memoria assistant == texto entregado +
proyección a Chatwoot). Ninguna capa posterior puede recomponer `reply` — es la raíz
de los P0 verificados por auditoría (fantasmas + memoria≠entregado).

Reusa `FunnelState` de `funnel_state_planner` (no se duplica el estado del funnel).
Las colecciones son tuplas para garantizar inmutabilidad real (no solo del atributo).
"""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any, Literal

from app.knowledge.funnel_state_planner import FunnelState

DeliveryPolicy = Literal["send", "suppress", "ack_then_handoff"]


@dataclass(frozen=True)
class TurnDecision:
    """Decisión inmutable de un turno. `frozen=True`: reasignar cualquier campo falla."""

    reply: str
    delivery_policy: DeliveryPolicy = "send"
    funnel_state: FunnelState | None = None
    facts_to_write: tuple[Any, ...] = ()
    asked_field_keys: tuple[str, ...] = ()
    requires_human: bool = False
    handoff_reason: str | None = None
    next_question: str | None = None
    should_continue_profile: bool = True

    def __post_init__(self) -> None:
        # Normaliza colecciones a tupla si el caller pasó lista (inmutabilidad real).
        object.__setattr__(self, "facts_to_write", tuple(self.facts_to_write))
        object.__setattr__(self, "asked_field_keys", tuple(self.asked_field_keys))

    @property
    def is_deliverable(self) -> bool:
        """True si hay algo público que entregar al candidato este turno."""
        return self.delivery_policy != "suppress" and bool((self.reply or "").strip())
