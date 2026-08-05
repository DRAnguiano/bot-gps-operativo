## 1. TurnDecision + FunnelState (puros, sin BD)

- [ ] 1.1 Definir `TurnDecision` (`dataclass frozen`) con los 9 campos; `delivery_policy: Literal["send","suppress","ack_then_handoff"]`.
- [ ] 1.2 Definir `FunnelState` y `funnel_state_planner.plan(facts) -> FunnelState` (`profile_ready`, `missing_fields`, `conflicts`, `next_question`, `asked_field_keys`).
- [ ] 1.3 Tests puros de `plan()` por estado de facts (golden), incluidos conflictos.

## 2. Autoridad única de funnel

- [ ] 2.1 Migrar los consumidores (ack del guard, nudge, Nota IA, labels) a `funnel_state_planner.plan()`.
- [ ] 2.2 Eliminar `current_turn._next_funnel_question_or_none`, `_FUNNEL_STEPS`, lista de `intent_orchestrator`.
- [ ] 2.3 Resolver prefijos (intro Mundo, vocativo) DENTRO del `TurnDecision`, no en el worker.

## 3. Namespace canónico + adapter

- [ ] 3.1 Adapter único legacy→canónico según la matriz (design D4): `license.category→license.type`, `apto_status`/`apto_expiration_text`, `documents.proof`, `experience.vehicle_type`.
- [ ] 3.2 Eliminar mapeos implícitos dispersos; toda lectura de facts pasa por el adapter/planner.
- [ ] 3.3 Tratar `license.type=A` como no apta (solo B/E) en el planner.

## 4. Preguntas laterales y handoff

- [ ] 4.1 Pregunta lateral: `TurnDecision` responde la pregunta, `next_question=None`, preserva el pendiente, cierre suave opcional.
- [ ] 4.2 `pre_handoff_verification`: `route != human_handoff`, `requires_human=False`.
- [ ] 4.3 Handoff final explícito (`handoff_reason` + `requires_human=True`); ack gobernado por `delivery_policy` (`ack_then_handoff`).

## 5. V2 única verdad + outbox

- [ ] 5.1 Migrar `release_human_review` a `rh_leads_v2`; legacy read-only detrás de flag.
- [ ] 5.2 Proyección de nota/labels/stage DESDE V2.
- [ ] 5.3 Tabla `rh_outbox` con único `(lead_key, turn_id, kind)`; entrega chequea/inserta antes del POST a Chatwoot.
- [ ] 5.4 Reemplazo de labels declarativo/idempotente; retry lee el outbox y no reenvía.
- [ ] 5.5 Memoria assistant = texto exacto entregado; un solo assistant por turno.
- [ ] 5.6 Extraer los helpers de proyección de `app.py` (`_send_chatwoot_message`, `_set_chatwoot_labels`, `_send_chatwoot_private_note`, `_build_chatwoot_internal_note`, `_human_*`, work_queue) a un módulo dedicado (`chatwoot_projection`) consumido por el outbox; webhook y worker dejan de duplicar el flujo — ambos entregan el `TurnDecision` por el outbox. Mantener `_clean_llm_answer` como precedente (ya delega en `reply_cleaner`).

## 6. Shadow, cutover y limpieza

- [ ] 6.1 Shadow `[TURN_DECISION_SHADOW]`: comparar `TurnDecision.reply`/funnel_state contra el legacy sin gobernar.
- [ ] 6.2 Cutover por consumidor detrás de flags (reply → memoria → nota/labels → handoff → followup).
- [ ] 6.3 Retirar puntos de reemplazo de reply y funnels duplicados una vez deferidos.
- [ ] 6.4 Incluir `beat` en los deploys (rebuild/restart junto con api/worker) para que no quede con imagen/código stale; verificar hashes de código iguales en los 3 contenedores.

## 7. Matriz de regresión (obligatoria — cada caso es un test)

- [ ] 7.1 Pago mientras falta licencia → responde pago, NO avanza funnel; licencia sigue pendiente.
- [ ] 7.2 "Soy de Monterrey" → persiste `candidate.city`; NO se clasifica como pregunta de rutas.
- [ ] 7.3 B1 incompleto → pre-verificación con `requires_human=False`; NO human handoff.
- [ ] 7.4 B1 completo → handoff explícito + `delivery_policy=ack_then_handoff`.
- [ ] 7.5 Reingreso → conserva estado V2 y proyecta labels correctos.
- [ ] 7.6 Primer contacto → assistant almacenado == assistant enviado (incluye intro).
- [ ] 7.7 Current-turn guard → cero mensajes assistant fantasma (un solo assistant/turno).
- [ ] 7.8 `perfil_listo` → stage V2, labels y nota coinciden.
- [ ] 7.9 Release humano → modifica V2 y la siguiente proyección elimina el estado de revisión.
- [ ] 7.10 Retry de outbox → no duplica mensajes ni notas.

## 8. Validación

- [ ] 8.1 `openspec validate unified-turn-decision-v2-projection` sin errores.
- [ ] 8.2 Matriz 7.x en verde en contenedor antes de cada corte de cutover.
- [ ] 8.3 Verificar conteos legacy vs V2 (`release_human_review`) antes de retirar legacy.
