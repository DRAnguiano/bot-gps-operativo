## Why

Auditoría read-only **verificada contra el código** (no intuida; archivo:línea) confirma divergencia estructural entre lo que el candidato recibe y lo que el sistema persiste/decide:

- **P0 — Fantasmas + doble/triple assistant por turno**: `run_hr_graph_message` persiste el reply a V2 (`knowledge_orchestrator.py:1207`) y legacy (`:2189`); si el guard del worker dispara, sobreescribe el reply y persiste OTRA fila a V2 (`tasks_chatwoot.py:595`). Ninguna coincide con el texto entregado.
- **P0 — Reply mutado post-persistencia**: `_maybe_prepend_first_reply_intro` (`tasks_chatwoot.py:647`) cambia el texto DESPUÉS de guardarlo → la memoria assistant "miente" sobre lo que dijo el bot.
- **P1 — Handoff partido legacy/V2**: `release_human_review` escribe `rh_conversations` legacy (`db.py:367`); V2 tiene su propio `human_review` (`repository.py:20/421`).
- **P1 — Namespace de facts incompatible**: el funnel lee `medical.apto_expiration_text` (`current_turn.py:569`) pero se escribe también `medical.apto_status` (`profile_extractor.py:337`) y hasta `document.apto_status` (singular, `:373`)/`documents.general_status`; el canónico propuesto `license.type` **no lo escribe ningún path vivo** (vivo = `license.category`).
- **P1 — Bug #3 (compuesto) es de DETECCIÓN, no de composición**: el path vivo YA antepone la respuesta embebida (`knowledge_orchestrator.py:1972-1976`), pero `_resolve_embedded_question` (`:287-322`) la descarta si fallan sus dos gates, y el worker usa un detector **distinto y en desacuerdo** (`signals.has_embedded_question`, `tasks_chatwoot.py:503`).

Absorbe/supersede `unify-profiling-state-contract` y `fix-license-key-and-a-validity`, y **corrige** el diagnóstico previo de este mismo cambio con los tres defectos que la auditoría encontró (ver "What Changes").

## What Changes

- **NUEVO `TurnDecision` puro e inmutable** como única salida de la orquestación de un turno: `reply`, `delivery_policy` (`send | suppress | ack_then_handoff`), `funnel_state`, `facts_to_write`, `asked_field_keys`, `requires_human`, `handoff_reason`, `next_question`, `should_continue_profile`. **BREAKING**: ninguna capa posterior puede modificar `TurnDecision.reply`; el worker solo **entrega** la decisión.
- **Un solo assistant message por turno candidato**, y la memoria assistant registra **exactamente** el texto entregado (sin reemplazos post-persistencia, sin mensajes fantasma).
- **Detector ÚNICO de pregunta embebida** (nueva capability): un solo detector consumido por el guard del worker Y el orquestador, eliminando el desacuerdo actual (`signals.has_embedded_question` vs `_looks_like_question`). Cubre el caso "compuesto sin `?` ni término de negocio conocido". **Esta es la corrección de raíz del bug #3** (la auditoría probó que #3 es de detección, no de composición).
- **`funnel_state_planner` como ÚNICA autoridad** de `profile_ready`, campos completos/faltantes, conflictos, `next_question` y `asked_field_keys`. **CORRECCIÓN de auditoría**: hoy `plan()` NO está cableado en vivo y su `CORE_FIELDS` **omite `candidate.name` y `candidate.age`** que los funnels vivos sí piden; cablearlo requiere **incorporar name/age** (o justificar su exclusión) para NO regresar el funnel. Se eliminan los funnels vivos duplicados (`current_turn._next_funnel_question_or_none`, `_FUNNEL_STEPS`) DESPUÉS de cablear el planner.
- **Namespace canónico + matriz de compatibilidad AMPLIADA**: incluye `medical.apto_status`↔`medical.apto_expiration_text` **y** `document.apto_status` (singular) **y** `documents.general_status` (las 3 variantes vivas). `license.category → license.type` vía **adapter de lectura en un solo punto, aplicado ANTES de tocar los escritores** (es rename en código 100% vivo).
- **Preguntas laterales** (el candidato pregunta algo mientras hay un campo pendiente): responder con RAG/policy/clarificación, **preservar el campo pendiente**, **no** emitir la siguiente pregunta del funnel, cierre suave opcional. Depende del detector único (arriba).
- **Handoff con semántica explícita**: `pre_handoff_verification` NO usa `route=human_handoff`; el escalamiento final es explícito; `delivery_policy` decide si hay ack público; se elimina el booleano como única semántica.
- **V2 (`rh_leads_v2`) como única verdad operacional**: migrar `release_human_review` a V2; legacy read-only durante la transición (o retiro); **Chatwoot se proyecta desde V2**.
- **Outbox idempotente** para mensaje público, nota privada y reemplazo de labels: soporta retry **sin duplicar** reply ni nota.

## Capabilities

### New Capabilities
- `turn-decision-contract`: el objeto puro inmutable `TurnDecision` y la regla de que es la única salida de un turno; el worker solo entrega.
- `embedded-question-detection`: un único detector de pregunta embebida compartido por guard y orquestador, con el caso "compuesto sin marcador". (Corrige la raíz del bug #3.)
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
