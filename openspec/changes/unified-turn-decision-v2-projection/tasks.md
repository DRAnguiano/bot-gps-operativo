> Orden corregido por auditoría: bloques pequeños; **D1/D2 primero en shadow** (los 2 P0,
> mejor fundamentados). Principio: no intuir — cada bloque se justifica con pruebas antes de
> gobernar; cutover por consumidor detrás de flags; adapter antes de escritores.

## 1. TurnDecision + FunnelState (puros, sin BD/LLM) — FASE 1 (D1)

- [x] 1.1 Definir `TurnDecision` (`dataclass frozen`) con los 9 campos; `delivery_policy: Literal["send","suppress","ack_then_handoff"]`.
- [x] 1.2 `FunnelState` + `compute_funnel_state()` YA EXISTEN en `funnel_state_planner.py` (puros, no cableados) — se REUSAN, no se duplica un `plan()`. `TurnDecision` embebe `FunnelState`.
- [x] 1.3 Shadow `[TURN_DECISION_SHADOW]`: construir el `TurnDecision` en paralelo y loggear divergencia vs el reply legacy — SIN gobernar. Confirmar paridad antes de cortar.
- [x] 1.4 Tests puros de `TurnDecision` (inmutabilidad) + planner existente por estado de facts (golden), incluidos conflictos.

## 2. Detector único de pregunta embebida (raíz del bug #3)

- [x] 2.1 Unificar en un solo detector lo que hoy hacen `signals.has_embedded_question` (`tasks_chatwoot.py:503`) y `_looks_like_question` (`knowledge_orchestrator.py:282`); consumido por guard Y orquestador.
- [x] 2.2 Cubrir el caso "compuesto sin `?` ni término de negocio conocido".
- [x] 2.3 Tests: guard y orquestador coinciden; compuesto sin marcador se responde; el 2º clasificador no puede descartar en silencio.

## 3. Entrega única: texto entregado == memoria (D1/D2, los 2 P0)

- [ ] 3.1 Mover la intro (`_maybe_prepend_first_reply_intro`, `tasks_chatwoot.py:647`) DENTRO del `TurnDecision` (antes de persistir).
- [ ] 3.2 Una sola persistencia assistant = el texto exacto entregado; eliminar las persistencias duplicadas (`knowledge_orchestrator.py:1207` V2, `:2189` legacy, `tasks_chatwoot.py:595` V2-guard).
- [ ] 3.3 El worker solo entrega el `TurnDecision`; ninguna capa recompone `reply`.
- [ ] 3.4 Tests H1/H2: un solo assistant/turno; memoria == entregado (incluye primer contacto con intro).

## 4. funnel_state_planner autoridad (cableado nuevo) + name/age

- [ ] 4.1 Incorporar `candidate.name` y `candidate.age` a `CORE_FIELDS` (`funnel_state_planner.py:29`) — hoy los omite y los funnels vivos sí los piden (evitar regresión).
- [ ] 4.2 Cablear `plan()` en vivo; Nota IA y labels leen de aquí.
- [ ] 4.3 Retirar los funnels vivos duplicados (`current_turn._next_funnel_question_or_none`, `_FUNNEL_STEPS`) DESPUÉS de verificar paridad.

## 5. Namespace canónico + adapter (antes de escritores)

- [ ] 5.1 Adapter de lectura `license.category→license.type` en un solo punto; verificar con regresión ANTES de tocar escritores.
- [ ] 5.2 Matriz de compatibilidad AMPLIADA: `apto_status` + `document.apto_status` (singular, `profile_extractor.py:373`) + `documents.general_status` → canónico; reconciliar funnel (lee `apto_expiration_text`) vs nota (lee `apto_status`).
- [ ] 5.3 `license.type=A` = no apta (solo B/E) en el planner.

## 6. V2 única verdad + outbox + handoff

- [ ] 6.1 Migrar `release_human_review` (`db.py:367`, `rh_conversations` legacy) a V2 (`rh_leads_v2`); legacy read-only detrás de flag.
- [ ] 6.2 `pre_handoff_verification`: `route != human_handoff`, `requires_human=False`; handoff final explícito (`handoff_reason` + `requires_human=True`); ack por `delivery_policy`.
- [ ] 6.3 Outbox `rh_outbox` único `(lead_key, turn_id, kind)`; entrega chequea/inserta antes del POST; retry no reenvía; labels declarativos/idempotentes; proyección desde V2.
- [ ] 6.4 Extraer helpers de proyección de `app.py` a módulo `chatwoot_projection` consumido por el outbox; webhook y worker dejan de duplicar el flujo.
- [ ] 6.5 Incluir `beat` en los deploys (rebuild/restart con api/worker); verificar hashes iguales en los 3 contenedores.

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
- [x] 7.11 Compuesto sin marcador (`?`/término) → el detector único lo responde.
- [ ] 7.12 apto_status=vigente sin expiration_text → funnel y nota coinciden (no re-pregunta).

## 8. Validación

- [ ] 8.1 `openspec validate unified-turn-decision-v2-projection` sin errores.
- [ ] 8.2 Matriz 7.x en verde en contenedor antes de cada corte de cutover.
- [ ] 8.3 Verificar conteos legacy vs V2 (`release_human_review`) antes de retirar legacy.
