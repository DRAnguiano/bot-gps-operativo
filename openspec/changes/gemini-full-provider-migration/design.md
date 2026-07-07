## Context

Fase G1 (gemini-natural-recruiter) dejó Gemini en generación RAG y visión, pero el
corazón extractivo (12 call sites) seguía en Groq directo. El usuario decidió
(2026-07-07, reiterado 4 veces en sesión) que Groq queda **eliminado** del entorno:
ni camino primario, ni fallback, ni override de debug. Caso conv 166 demostró además
que los Terms Neo4j de alias exacto pierden intenciones conversacionales en mensajes
compuestos, y que el bot responde con texto fijo después de gastar tokens
clasificando. Ver memorias `project_gemini_flash_eval`,
`feedback_prompt_over_dictionary`, `feedback_llm_generated_variety`.

## Goals / Non-Goals

**Goals**: Gemini 2.5 Flash como único proveedor en TODOS los caminos LLM; config
propia GEMINI_* (nada reciclado de GROQ_*); finalidad conversacional extraída por
few-shot en la llamada única existente; respuestas generadas (no enlatadas) para
turnos conversacionales; audio nativo; retiro físico del código y env de Groq.

**Non-Goals**: tocar los guardrails de negocio (pago fail-closed, no-promesa,
léxico vigencia, edad); cambiar el funnel determinista (orden de preguntas, resumen
de confirmación); migrar embeddings (bge-m3 local, no es LLM).

## Decisions

**D1 — Gemini-único: sin proveedor alterno; degradación por contrato de error.**
Los dispatch (`dispatch_generation`, `dispatch_json`, `dispatch_vision`,
`dispatch_audio`) llaman SOLO a Gemini. Ante `GeminiError`, cada uno degrada con el
contrato que sus callers ya manejan:
- `dispatch_json` → `'{"error": "gemini_error"}'` (callers: señales neutras /
  extracción vacía — el turno sigue, sin facts nuevos).
- `dispatch_vision` → `""` (media guard acotado, sin encolar).
- `dispatch_generation` → propaga la excepción; cada caller tiene su texto
  determinista (acuse fijo, plantilla) y decide cómo degradar.
- `dispatch_audio` → `""` (mismo contrato que la transcripción fallida actual).
*Alternativa rechazada 3 veces por el usuario*: mantener Groq como fallback — "que
únicamente quede como camino para todas las respuestas gemini".

**D2 — Config propia de Gemini, sin reciclar constantes Groq.** `GEMINI_MODEL`
(default `gemini-2.5-flash`), `GEMINI_MAX_TOKENS` (default 500),
`GEMINI_TEMPERATURE` (default `TEMPERATURE` genérica o 0.0),
`GEMINI_TIMEOUT_SECONDS` (existente, 20). `call_gemini_llm` y todos los dispatch
usan estas; ninguna función nueva lee `GROQ_*`. thinkingBudget=0 en TODAS las
llamadas (texto y JSON — bug del truncamiento "El pago en Trans...").

**D3 — Migración por módulo con gate de calidad.** Orden: (1) señales/clasificadores
(turn_intent_classifier, business_route_classifier —shadow—, intent_classifier),
(2) generadores de copy (current_turn ack, expediente acuse, reencauce natural),
(3) turn_extractor + profile_extractor validados contra la matriz de 72 casos
(gate: igualar o superar el benchmark previo recall 0.84 / precisión 1.00 — absorbe
la Fase G3; los few-shots del prompt se adaptan si hace falta, p. ej. los 2 fallos
del eval: fulero crudo, caja seca). Cada módulo migrado corre su suite antes del
siguiente. La firma `model=` (selección de modelo Groq) se acepta-e-ignora durante
la transición y se retira al final.

**D4 — Audio nativo (absorbe G2).** `dispatch_audio(audio_bytes, mime_type)` →
`transcribe_audio` de Gemini con el glosario trailero en el prompt (fulero=full,
doble articulado=full, caja seca, apto, R-Control) pidiendo transcripción FIEL.
Gate para el corte: eval con ≥5 notas de voz reales del usuario, 0 destrozos de
términos del glosario. Whisper se elimina junto con el resto de Groq en D7.

**D5 — Finalidad conversacional en el clasificador unificado.** `TurnIntentSignals`
gana `conversational_purpose: str` ("smalltalk" | "queja" | "agradecimiento" |
"despedida" | "animo" | "none") con few-shots en `_TURN_INTENT_SYSTEM` — MISMA
llamada LLM, cero costo extra (patrón validado con `is_joke_request`). El
orchestrator consume la señal: purpose ≠ none y turno seguro → respuesta GENERADA
por el friendly LLM (persona Mundo, contexto del lead, dato determinista del turno
si lo hay) + nudge del funnel. *Alternativa rechazada*: llamada LLM dedicada por
intención — duplica costo/latencia.

**D6 — Terms Neo4j solo para vocabulario de negocio.** Auditoría de overlap: listar
Terms cuyos aliases compiten entre categorías (caso "licencia" → documentos ganó al
chiste) y RETIRAR de los Terms las intenciones conversacionales (smalltalk_joke y
similares), que pasan al extractor few-shot. El seed conserva lenguaje→concepto de
negocio (unidades, geografía, faltas de ortografía) conforme a
`reference_seed_vocabulary_only`.

**D7 — Retiro físico de Groq al FINAL, tras verificación en vivo.** Secuencia:
migrar call sites → suite verde → verificación en vivo de cada camino (texto,
JSON, visión, audio) → entonces eliminar `call_groq_*`, `_groq_with_fallback`, el
cliente `groq` de requirements, las env `GROQ_*` de `.env`, y reescribir los tests
que mockeaban Groq. Eliminar primero dejaría al sistema sin degradación conocida si
un camino quedó sin migrar.

**D8 — Texto fijo = fallback, nunca primario.** CONTROLLED_FALLBACK_REPLY,
CONTROLLED_CLARIFICATION_REPLY, _FRIENDLY_NEUTRAL_REPLY, _FRIENDLY_NO_ANSWER_REPLY,
DOCUMENT_ACK_REPLY: cada uno se convierte en el `except`/vacío de una generación
LLM con prompt específico de su situación. El candidato solo ve texto enlatado si
el LLM falló (degradación, no diseño). Guardrails que NO cambian: requires_human,
risk high, DISALLOWED_FREE_CHAT_TERMS, fail-closed de pago, no-promesa (policy en
prompt), léxico de vigencia (validador regex post-generación se mantiene).

## Risks / Trade-offs

- **Proveedor único sin red alterna** → degradación por contrato de error en cada
  camino (el sistema nunca crashea por fallo LLM; a lo sumo un turno degrada a
  texto determinista o señales neutras); retiro físico de Groq solo al final (D7).
- **5 RPM free tier con TODA la carga en Gemini** → cadencia obligatoria en pruebas
  (30-40s entre mensajes); tier pago ANTES del corte final a producción.
- **Extractor migrado regresiona jerga** → gate matriz 72 casos antes del corte.
- **Respuesta generada puede violar tono** → validadores post-generación existentes
  (vigencia, banned terms) + fallback determinista.

## Open Questions

1. ¿Cuándo se contrata el tier pago de Gemini? (Bloquea el retiro físico D7 para
   producción real; en staging se puede completar todo con free tier + cadencia.)
2. ~~¿business_route_classifier se migra o se elimina?~~ **RESUELTA (usuario,
   2026-07-07): se RETIRA.** Era código huérfano (ningún caller vivo) y su contrato
   lo definía como shadow, no canal principal. El extractor unificado manda. Su
   capability se marca REMOVED (delta en este change); `business_route_schema` se
   conserva (catálogo usado por chatwoot_note_sync); el harness QA de la matriz de
   72 casos se repunta al extractor unificado en el gate 4.2.
