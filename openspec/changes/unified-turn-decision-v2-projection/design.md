## Context

Un turno del candidato hoy fluye por: webhook → `tasks_chatwoot` (debounce, guard, extracción pre) → `run_hr_graph_message`/`knowledge_orchestrator` (clasifica, arma reply, persiste facts, decide stage) → sync a Chatwoot (reply + nota + labels). En el camino, **la respuesta pública se compone/reemplaza en varias capas** (guard ack, funnel nudge, answer_primary_question, composer shadow), los facts se escriben con **claves incompatibles**, el **stage/labels/nota** se calculan por rutas paralelas, y **legacy DB y V2** no siempre coinciden. No hay un único objeto que represente "lo que se decidió este turno".

## Auditoría de conceptos sin atención (2026-07-01)

Verificado en código (no intuido). Documenta qué hace cada parte y por qué, para no perder contexto:

**`app.py` (1636 líneas — "god file")** mezcla 4 responsabilidades:
1. **App FastAPI + endpoints**: `/health`, `/reindex`, `/ask`, `/orchestrate/message`, `/classify`, `/admin/release-human-review`, `/chatwoot/webhook`.
2. **Hogar de la proyección a Chatwoot** (helpers): `_send_chatwoot_message`, `_set_chatwoot_labels`, `_send_chatwoot_private_note`, `_build_chatwoot_internal_note`, `_normalize/_fallback_chatwoot_labels`, formatters `_human_*`, `_get_rh_work_queue_metadata`. **El worker (`tasks_chatwoot`) IMPORTA estos helpers desde `app.py`** (no duplica la lógica) — por eso `app.py` es una dependencia del worker pese a ser el server web.
3. **Flujo síncrono de orquestación+proyección** (webhook, líneas ~1442-1563): SOLO se usa cuando `INBOUND_DEBOUNCE_ENABLED=false` (diagnóstico). En producción (default true) el webhook **encola** (`enqueue_chatwoot_message`) y el **worker** hace todo. → **Dos flujos de call que se mantienen en sync a mano** (webhook-sync vs worker); duplicación de flujo, no de helpers.
4. `_clean_llm_answer` **ya está consolidado**: delega en `reply_cleaner.clean_reply` (buen precedente de cómo unificar sin divergencia).

**`beat` (hr_beat)**: servicio VIVO (agenda `seguimiento.programar_tareas`/`enviar_pendientes` cada ~5 min), pero **quedó corriendo imagen del 29-jun** — los deploys de la sesión fueron `up -d api worker` sin beat (omisión, no deprecación). Ejecuta en el worker; su `tasks_seguimiento.py` coincide, pero sus `tasks_chatwoot`/`orchestrator` importados están stale. Acción: incluir `beat` en los deploys.

**`/admin/release-human-review`** (app.py): escribe el release; es lo que D7 migra a V2.

**Cómo lo resuelve este cambio**: `TurnDecision` (D1) + entrega única (D2) + outbox (D8) eliminan los dos flujos de proyección (webhook-sync y worker entregan la MISMA decisión por el MISMO outbox); `funnel_state_planner` (D3) elimina los funnels paralelos; V2 (D7) elimina la divergencia legacy/V2. Los helpers de `app.py` se moverían a un módulo de proyección dedicado (fuera del server web) consumido por el outbox.

## Goals / Non-Goals

**Goals:**
- Un único `TurnDecision` inmutable por turno; el worker solo entrega.
- Una sola autoridad de funnel (`funnel_state_planner`).
- Namespace de facts canónico y explícito, sin mapeos implícitos.
- Preguntas laterales que no rompen el pendiente del funnel.
- Handoff con semántica explícita (no booleana) y ack gobernado por `delivery_policy`.
- V2 como única verdad; Chatwoot proyectado desde V2 vía outbox idempotente.

**Non-Goals:**
- NO rediseñar el corpus RAG ni los prompts de generación (solo de dónde/cómo se decide y entrega).
- NO cambiar modelos LLM (ver [[project_model_config_split]]).
- NO tocar la lógica de negocio de dominio (edad, B1, escuelita/cecati) salvo su semántica de handoff.

## Decisions

**D1 — `TurnDecision` puro e inmutable.** `dataclass(frozen=True)` con: `reply: str`, `delivery_policy: Literal["send","suppress","ack_then_handoff"]`, `funnel_state`, `facts_to_write: list[CanonicalFact]`, `asked_field_keys: list[str]`, `requires_human: bool`, `handoff_reason: str|None`, `next_question: str|None`, `should_continue_profile: bool`. La orquestación la construye una sola vez; el worker la **entrega** (persistir facts + memoria assistant + proyección Chatwoot) sin recomponer `reply`. *Alternativa descartada*: seguir componiendo reply en el worker — es la causa raíz de la divergencia mensaje-visto vs memoria.

**D2 — Memoria assistant == texto entregado; un solo assistant por turno.** El worker guarda en V2 el `reply` EXACTO que envía a Chatwoot, una sola vez. Se eliminan los puntos donde se prepende/reemplaza (intro de primer reply, doble ack, composer) fuera del `TurnDecision`. Los prefijos (intro de Mundo, vocativo) se resuelven DENTRO de la construcción del `TurnDecision`.

**D3 — `funnel_state_planner` autoridad única.** Expone `plan(facts) -> FunnelState` con `profile_ready`, `missing_fields`, `conflicts`, `next_question`, `asked_field_keys`. `current_turn._next_funnel_question_or_none`, `_FUNNEL_STEPS` (nudge) y la lista de `intent_orchestrator` se **eliminan** y delegan aquí. La Nota IA y los labels leen de aquí.

**D4 — Namespace canónico explícito (matriz de compatibilidad).**

| Concepto | Canónico (autoridad) | Claves legacy que se mapean | Regla |
|---|---|---|---|
| Tipo de licencia | `license.type` (B/E/A) | `license.category` | Migrar category→type; A = no apta (solo B/E) |
| Vigencia licencia | `license.expiration_text` | — | Texto de vencimiento; validez por `is_valid_expiration_text` |
| Estado apto | `medical.apto_status` (`vigente|vencido|tramite`) | inferido de expiración | `apto_status` = estado; distinto de la vigencia |
| Vigencia apto | `medical.apto_expiration_text` | — | Fecha/plazo; `apto_status=vigente` requiere vigencia válida >3m |
| Comprobante laboral | `documents.proof` (`cartas|semanas_imss|ninguno`) | `documents.labor_letters*` | Condicional por residencia (RD1) |
| Unidad | `experience.vehicle_type` (`full|sencillo`) | `vehicle_type_raw` (jerga) | full/sencillo confirmado; jerga no fija tipo |

Se **elimina todo mapeo implícito ambiguo**; cualquier lectura pasa por `funnel_state_planner`/adapter explícito.

**D5 — Preguntas laterales.** Si el turno trae una pregunta (RAG/policy) y hay un campo del funnel pendiente: `TurnDecision.reply` = respuesta a la pregunta; `next_question=None`; `should_continue_profile=True`; el pendiente se preserva (no se marca como preguntado ni respondido); cierre suave opcional ("cuando guste seguimos"). NO se anexa la siguiente pregunta del funnel el mismo turno.

**D6 — Handoff explícito.** `pre_handoff_verification` es un estado de VERIFICACIÓN (pregunta el dato mínimo B1/escuelita/cecati) con `route != human_handoff` y `requires_human=False`. El escalamiento final es un evento explícito (`handoff_reason` seteado + `requires_human=True`), y `delivery_policy` decide el ack: `ack_then_handoff` (acuse específico por motivo + escala) o `send` normal. Se elimina el booleano suelto como única semántica.

**D7 — V2 única verdad; Chatwoot proyectado.** `rh_leads_v2` es la fuente operacional (facts, stage, human_review). `release_human_review` se migra a V2. Legacy queda read-only durante la transición (flag) y luego se retira. La nota, labels y stage en Chatwoot se **derivan de V2** (proyección), no se calculan aparte.

**D8 — Outbox idempotente.** Tabla `rh_outbox` con `(lead_key, turn_id, kind)` único (`kind ∈ {public_reply, private_note, labels}`). Cada entrega chequea/inserta antes de llamar a Chatwoot; retry lee el outbox y NO reenvía lo ya entregado. Reemplazo de labels es una operación declarativa (set target labels) idempotente.

## Risks / Trade-offs

- **Cutover en ruta viva de reclutamiento** → Mitigación: `TurnDecision` y V2 en paralelo (shadow) antes del corte; cutover por consumidor detrás de flags; matriz de regresión obligatoria.
- **Migración de datos legacy→V2 (`release_human_review`)** → Mitigación: legacy read-only + backfill idempotente + verificación de conteos antes de retirar.
- **Inversión de dirección de claves (`category`→`type`)** → Mitigación: matriz de compatibilidad + adapter de lectura; el extractor sigue en 70b y su salida se normaliza al canónico en un solo punto.
- **Outbox agrega latencia/escritura** → Mitigación: una fila por kind por turno; índice único; escritura local antes del POST.

## Migration Plan

1. Definir `TurnDecision` + `FunnelState` (puros, sin BD) y `funnel_state_planner.plan()`.
2. Construir `TurnDecision` en la orquestación reproduciendo el comportamiento actual (shadow: log `[TURN_DECISION_SHADOW]` divergencias vs el reply legacy).
3. Namespace canónico + adapter de lectura; matriz de compatibilidad aplicada en el límite de persistencia.
4. Outbox idempotente + proyección desde V2 (nota/labels/reply) en shadow.
5. Migrar `release_human_review` a V2; legacy read-only.
6. Cutover por consumidor detrás de flags: entrega de reply → memoria assistant → nota/labels → handoff → followup.
7. Retirar los funnels duplicados y los puntos de reemplazo de reply.
8. Suite de regresión (ver tasks) en verde antes de cada corte.

## Open Questions

- ¿`release_human_review` legacy se retira o se conserva read-only indefinidamente? (propuesta: read-only 1 release, luego retiro tras verificar V2).
- ¿`turn_id` para el outbox se deriva del `message_id` de Chatwoot debounced o de un uuid del turno? (propuesta: uuid del turno persistido en V2).
