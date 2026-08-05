## Why

El sistema tiene **múltiples fuentes de verdad divergentes** para un mismo turno del candidato: `knowledge_orchestrator`, `tasks_chatwoot`, `current_turn` y `funnel_state_planner` deciden por separado la respuesta, el estado del funnel y los facts; capas posteriores **reemplazan la respuesta pública después de persistirla**; conviven **varios funnels** y **contratos de facts incompatibles** (`license.category` vs `license.type`, `medical.apto_status` vs `medical.apto_expiration_text`). Resultado observado: la memoria V2, el mensaje que vio el candidato, el `stage`, los labels y el handoff **pueden divergir**; se emiten mensajes assistant fantasma; el pago no se responde a media marcha del funnel; el handoff usa un booleano como única semántica; y legacy DB vs V2 no coinciden. Esto es la deuda estructural que motivó la sesión de 2026-06/07 (ver los cambios `unify-profiling-state-contract` y `fix-license-key-and-a-validity`, que este cambio **absorbe y amplía**).

## What Changes

- **NUEVO `TurnDecision` puro e inmutable** como única salida de la orquestación de un turno: `reply`, `delivery_policy` (`send | suppress | ack_then_handoff`), `funnel_state`, `facts_to_write`, `asked_field_keys`, `requires_human`, `handoff_reason`, `next_question`, `should_continue_profile`. **BREAKING**: ninguna capa posterior puede modificar `TurnDecision.reply`; el worker solo **entrega** la decisión.
- **Un solo assistant message por turno candidato**, y la memoria assistant registra **exactamente** el texto entregado (sin reemplazos post-persistencia, sin mensajes fantasma).
- **`funnel_state_planner` como ÚNICA autoridad** de `profile_ready`, campos completos/faltantes, conflictos, `next_question` y `asked_field_keys`. Se eliminan los otros funnels (`current_turn._next_funnel_question_or_none`, `_FUNNEL_STEPS` del nudge, la lista de `intent_orchestrator`).
- **Namespace canónico de facts unificado y explícito** (autoridad = `funnel_state_planner`): `license.type`, la relación `medical.apto_status`↔`medical.apto_expiration_text`, `documents.proof`, `experience.vehicle_type`. Se **elimina todo mapeo implícito ambiguo**; la migración legacy→canónico se documenta en una matriz de compatibilidad.
- **Preguntas laterales** (el candidato pregunta algo mientras hay un campo pendiente): responder con RAG/policy/clarificación, **preservar el campo pendiente**, **no** emitir la siguiente pregunta del funnel, cierre suave opcional.
- **Handoff con semántica explícita**: `pre_handoff_verification` NO usa `route=human_handoff`; el escalamiento final es explícito; `delivery_policy` decide si hay ack público; se elimina el booleano como única semántica.
- **V2 (`rh_leads_v2`) como única verdad operacional**: migrar `release_human_review` a V2; legacy read-only durante la transición (o retiro); **Chatwoot se proyecta desde V2**.
- **Outbox idempotente** para mensaje público, nota privada y reemplazo de labels: soporta retry **sin duplicar** reply ni nota.

## Capabilities

### New Capabilities
- `turn-decision-contract`: el objeto puro inmutable `TurnDecision` y la regla de que es la única salida de un turno; el worker solo entrega.
- `chatwoot-outbox`: entrega idempotente (mensaje público, nota, labels) con retry sin duplicados, proyectada desde V2.

### Modified Capabilities
- `message-orchestration`: la orquestación produce un `TurnDecision` inmutable; `funnel_state_planner` es la única autoridad de funnel; preguntas laterales preservan el pendiente sin avanzar; no hay mensajes assistant fantasma ni doble assistant por turno.
- `lead-memory`: V2 es la única verdad operacional; la memoria assistant guarda el texto exacto entregado; `release_human_review` vive en V2.
- `chatwoot-sync`: la proyección a Chatwoot (reply, nota, labels) se deriva de V2 vía el outbox idempotente; reemplazo de labels sin duplicar.
- `unified-turn-extraction`: los facts se emiten en el namespace canónico único (`license.type`, etc.), sin mapeos implícitos ambiguos.
- `recruiting-business-route-classification`: `pre_handoff_verification` no usa `route=human_handoff`; el handoff final es explícito y su ack lo decide `delivery_policy`.
- `chatwoot-ai-note` y `chatwoot-label-taxonomy`: nota y labels se proyectan desde V2 y coinciden con el stage.

## Impact

- **Código**: `app/orchestrators/knowledge_orchestrator.py`, `app/tasks_chatwoot.py`, `app/knowledge/current_turn.py`, `app/knowledge/funnel_state_planner.py`, `app/lead_memory/*` (repository, V2), `app/chatwoot_note_sync.py`, `app/followup/*`, `app/db.py`.
- **Datos**: migración `release_human_review` legacy→`rh_leads_v2`; legacy read-only o retirado; matriz de compatibilidad de facts.
- **Contratos/specs**: nuevas `turn-decision-contract`, `chatwoot-outbox`; deltas en `message-orchestration`, `lead-memory`, `chatwoot-sync`, `unified-turn-extraction`, `recruiting-business-route-classification`, `chatwoot-ai-note`, `chatwoot-label-taxonomy`.
- **Absorbe** los cambios propuestos `unify-profiling-state-contract` y `fix-license-key-and-a-validity` (quedan supersedidos por este).
- **Riesgo**: alto (ruta viva + datos); mitigado con cutover por consumidor detrás de flags, V2 en paralelo antes del corte, y la matriz de regresión.
- **Nota de dirección de claves**: este cambio fija el canónico en **`license.type`** (autoridad `funnel_state_planner`), invirtiendo la dirección tentativa de `fix-license-key-and-a-validity` (que iba a `license.category`). La migración se documenta explícitamente.
