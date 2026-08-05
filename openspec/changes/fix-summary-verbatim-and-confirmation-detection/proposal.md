# Proposal — fix-summary-verbatim-and-confirmation-detection

## Why

Verificación en vivo (conv 176, 2026-07-13) del fix de confirmación compuesta reveló una cadena de 3 defectos que degradó toda la recta final del funnel: el candidato entregó su perfil completo en un mensaje, el sistema construyó el resumen correcto, pero **entregó una pregunta de confirmación sin los datos** ("¿Me podría confirmar que los datos son correctos?" — 117 chars, evidencia en `[TURN_DECISION_SHADOW]`). El candidato respondió "¿Cuales datos?", eso se enrutó a RAG de requisitos (re-preguntó datos ya capturados + coletilla enlatada de horario desde el doc RAG), y cuando finalmente confirmó con "Si, todo bien, ¿Hacen dopong?", `funnel.summary_confirmed` volvió a NO persistirse — por una causa distinta a la ya corregida.

## What Changes

- **(A) Resumen verbatim**: la pregunta de resumen (y cualquier pregunta de funnel que porte contenido estructurado, p. ej. lista de datos) NUNCA pasa por `generate_funnel_transition_reply`. La reformulación LLM aplica solo a preguntas atómicas de un dato; el resumen se entrega tal cual lo construyó el funnel determinista.
- **(C1) Ventana de detección**: `last_bot_message` se trunca a 500 chars en `tasks_chatwoot.py:393`; el resumen re-emitido al final de una respuesta larga (1027 chars) queda fuera y el detector de confirmación queda ciego. Se amplía la ventana para que la detección de contexto vea el mensaje completo del bot (o al menos su cola, donde vive la pregunta vigente).
- **(C2) Marcador de resumen robusto**: `_TOPIC_SUMMARY_CONFIRM = r"es correcto"` no matchea variantes reales ya observadas ("son correctos", "confirmo sus datos registrados"). Se amplía el marcador a las formas del propio sistema.
- **(B) Coletilla de horario fuera de los docs RAG**: `data/03_seguridad_antidoping.md` (y docs hermanos) hornean "llámenos de 8:00 a 17:30 hrs para cualquier duda" dentro de la respuesta sugerida; mid-funnel esa coletilla rompe la persona (Mundo ES el canal — no deriva a otro canal salvo handoff real). Se limpia la coletilla de los docs; la derivación con horario queda solo en el flujo de handoff.

Nota: la meta-pregunta "¿Cuales datos?" enrutada a RAG es consecuencia directa de (A) — con el resumen entregado verbatim, ese turno no ocurre. No se añade capa de routing nueva.

## Capabilities

### New Capabilities

(ninguna)

### Modified Capabilities

- `funnel-llm-transitions` (delta del change anterior, aún sin sync): la transición generada aplica SOLO a preguntas atómicas; preguntas con contenido estructurado (resumen de datos) se entregan verbatim.
- `funnel-summary-confirmation` (delta del change anterior, aún sin sync): la detección de confirmación debe operar sobre el mensaje completo del bot y reconocer todas las variantes de pregunta de confirmación que el propio sistema emite.
- `knowledge-source-hygiene`: los documentos RAG no incluyen instrucciones de canalización/horario en las respuestas sugeridas; la derivación es responsabilidad del flujo de handoff.

## Impact

- `app/orchestrators/knowledge_orchestrator.py` — puntos de unión que llaman `generate_funnel_transition_reply` (guard de pregunta estructurada).
- `app/knowledge/current_turn.py` — `generate_funnel_transition_reply` (guard interno de resumen), `_TOPIC_SUMMARY_CONFIRM`.
- `app/tasks_chatwoot.py:393` — truncado de `last_bot_message`.
- `data/03_seguridad_antidoping.md` y docs RAG con coletilla de horario.
- Tests: `tests/test_funnel_llm_transitions.py`, `tests/test_compound_summary_confirmation.py` (nuevos casos), posible test de higiene de corpus.
