# Design — fix-summary-verbatim-and-confirmation-detection

## Context

Evidencia en vivo (conv 176, 2026-07-13):

1. `[AGENTIC_SHADOW]` muestra el resumen determinista correcto ("¡Listo! Antes de continuar, le confirmo sus datos registrados: · Nombre: …"), pero `[TURN_DECISION_SHADOW]` muestra que se entregó una reescritura LLM de 117 chars **sin la lista** ("Muchas gracias por la información, Juan Raúl. ¿Me podría confirmar que los datos son correctos?"). La validación actual de `generate_funnel_transition_reply` (no vacío, contiene `?`, ≤500 chars) no protege el contenido estructurado — de hecho el resumen completo (>500 chars con datos) casi garantiza que una reescritura "válida" lo pierda.
2. El candidato preguntó "¿Cuales datos?" → RAG de requisitos re-preguntó datos ya capturados + resumen re-emitido al final (1027 chars).
3. "Si, todo bien, ¿Hacen dopong?" respondió el doping pero `funnel.summary_confirmed` no llegó a BD (verificado en `rh_lead_facts_v2`): `last_bot_message` se captura con `[:500]` (head) en `tasks_chatwoot.py:393`, y el resumen vivía en la cola del mensaje de 1027 chars → `_TOPIC_SUMMARY_CONFIRM` nunca lo vio. Además el patrón `r"es correcto"` no matchea "son correctos", la variante que el propio sistema acababa de emitir.
4. La coletilla "llámenos de 8:00 a 17:30 hrs para cualquier duda" viene literal de la respuesta sugerida en `data/03_seguridad_antidoping.md:54` — política de canalización horneada en el corpus RAG, contra la regla de que el seed/corpus es conocimiento y la canalización va en el flujo determinista de handoff.

## Goals / Non-Goals

**Goals:**

- El resumen de datos llega al candidato SIEMPRE completo y verbatim.
- La detección de confirmación de resumen ve el mensaje previo completo del bot y reconoce las variantes de confirmación que el propio sistema emite.
- El corpus RAG deja de inyectar derivación con horario en respuestas mid-funnel.

**Non-Goals:**

- No se añade routing nuevo para meta-preguntas ("¿Cuales datos?"): el disparador desaparece al corregir (A). Si reaparece con otro origen, será change propio.
- No se toca la política de handoff real (ahí el horario SÍ corresponde).
- No se rediseña `generate_funnel_transition_reply` — solo se acota su dominio de aplicación.

## Decisions

**D1 — Guard estructural dentro de `generate_funnel_transition_reply` (no en cada call-site).**
Si `question` porta contenido estructurado — contiene el encabezado de resumen ("le confirmo sus datos registrados") o viñetas de datos ("\n·") — la función regresa `fallback` directo, sin llamar al LLM. Ponerlo dentro de la función cubre los 3 puntos de unión del orquestador (`_fresh_now`, `_fresh_ack`, `_fresh_r1`) y cualquier call-site futuro; un guard por call-site se olvidaría en el siguiente join. Alternativa rechazada: instruir al LLM "copia la lista verbatim" + validar presencia de cada dato — más frágil y más caro que no llamar al LLM para algo que no debe reformularse.

**D2 — Captura completa de `last_bot_message`; truncado solo al alimentar prompts, preservando la COLA.**
En `tasks_chatwoot.py` se captura el mensaje del bot completo (cap defensivo 2000 chars conservando el final, donde vive la pregunta vigente). La detección de contexto (`_extract_context_confirmation_facts`) opera sobre esa versión completa. Donde el mensaje alimente un prompt LLM y se necesite acotar, se trunca conservando la cola (`[-500:]`), no la cabeza — el head-truncate actual conserva exactamente la parte inerte y descarta la pregunta activa.

**D3 — Marcador de resumen que cubre las variantes del propio sistema.**
`_TOPIC_SUMMARY_CONFIRM` pasa a reconocer: "es correcto", "son correctos" y "confirmo sus datos" (las tres formas emitidas hoy por funnel determinista, corrección de resumen y transición LLM). Se mantiene como regex simple sobre el mensaje del bot; no se infiere estado desde el mensaje del candidato.

**D4 — Higiene del corpus: canalización fuera de las respuestas sugeridas.**
Se elimina la coletilla de horario de `data/03_seguridad_antidoping.md` y de cualquier otro doc del corpus que la contenga (barrido por "8:00", "llámenos", "cualquier duda"). La respuesta sugerida termina en el contenido de negocio. Requiere reindexar ChromaDB tras editar los docs. La derivación con horario permanece únicamente en el flujo de handoff (código determinista).

## Risks / Trade-offs

- **D1**: si mañana se quiere un resumen "con voz", habrá que diseñarlo como plantilla determinista con slots, no como reescritura libre — aceptado explícitamente.
- **D2**: mensajes de bot >2000 chars perderían cabeza en la captura; hoy el mensaje más largo observado es ~1030 chars y la pregunta activa siempre va al final — riesgo teórico.
- **D3**: regex más amplio podría marcar como "pregunta de resumen" un mensaje que solo confirme UN dato ("¿es correcto?" tras corrección) — ese caso ya matchea hoy con el patrón actual y el flujo lo maneja; sin cambio de comportamiento.
- **D4**: reindexar el corpus cambia embeddings de esos chunks; riesgo bajo (mismo contenido menos una frase). Verificar con una consulta de doping post-reindex.
