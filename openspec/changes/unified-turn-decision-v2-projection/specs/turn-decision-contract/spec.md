## ADDED Requirements

### Requirement: TurnDecision es la única salida inmutable de un turno
La orquestación de un turno del candidato SHALL producir un único objeto `TurnDecision` inmutable con: `reply`, `delivery_policy` (`send | suppress | ack_then_handoff`), `funnel_state`, `facts_to_write`, `asked_field_keys`, `requires_human`, `handoff_reason`, `next_question`, `should_continue_profile`. Ninguna capa posterior SHALL modificar `TurnDecision.reply`; el worker solo entrega la decisión.

#### Scenario: El worker no recompone el reply
- **WHEN** la orquestación devuelve un `TurnDecision`
- **THEN** el worker entrega ese `reply` tal cual (persistencia + Chatwoot) sin componer ni reemplazar texto

#### Scenario: Decisión inmutable
- **WHEN** cualquier capa intenta mutar `TurnDecision.reply` u otro campo
- **THEN** la operación falla (objeto frozen) — el contrato es inmutable

### Requirement: Un solo assistant message por turno candidato
Por cada turno del candidato SHALL emitirse a lo sumo UN mensaje assistant. NO SHALL haber mensajes assistant fantasma (persistidos pero no entregados, o entregados sin persistir).

#### Scenario: Sin doble assistant
- **WHEN** se procesa un turno del candidato
- **THEN** se registra exactamente un mensaje assistant, igual al entregado

#### Scenario: Current-turn guard sin fantasmas
- **WHEN** el guard de current-turn produce un ack
- **THEN** ese ack es el `reply` del `TurnDecision` entregado y persistido, sin generar un assistant adicional
