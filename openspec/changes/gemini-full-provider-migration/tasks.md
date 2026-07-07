> Orden: dispatch Gemini-único primero (base de todo), luego migración por módulo
> (señales → copy → extractor con gate), audio, finalidad conversacional, y el
> retiro FÍSICO de Groq al final (D7: solo tras verificar todos los caminos en
> vivo). Suite por bloque; cadencia 30-40s en pruebas vivas (5 RPM free tier).

## 1. Base: dispatch Gemini-único + config propia

- [ ] 1.1 `gemini_client.py`: `dispatch_generation`/`dispatch_json`(nuevo)/
      `dispatch_vision`/`dispatch_audio`(nuevo) SIN imports ni llamadas a Groq;
      degradación por contrato de error (D1: json-error / "" / excepción al caller).
      Config propia `GEMINI_MODEL`/`GEMINI_MAX_TOKENS`/`GEMINI_TEMPERATURE` (D2);
      thinkingBudget=0 en texto y JSON. Tests con mocks (sin red).
- [ ] 1.2 `call_gemini_llm` (indexer): usa config GEMINI_*, captura GeminiError →
      mensaje de disculpa estándar (contrato del caller); `call_llm` enruta siempre
      a Gemini. Tests.
- [ ] 1.3 Reescribir tests existentes de fallback-a-Groq (test_gemini_client) al
      contrato Gemini-único; corregir test_friendly_loosening (referencia a
      `_has_joke_request` eliminado).

## 2. Migración de call sites — señales y clasificadores

- [ ] 2.1 `turn_intent_classifier:99` → dispatch_json. Suite del clasificador.
- [ ] 2.2 `intent_classifier:294` y `business_route_classifier:250` (shadow) →
      dispatch_json. Suites.
- [ ] 2.3 Smoke vivo (cadencia): un turno real por Telegram → extracción y señales
      correctas vía Gemini, `[gemini_json]` sin errores en logs.

## 3. Migración de call sites — generación de copy

- [ ] 3.1 `current_turn:129` (ack LLM), `expediente:398` (acuse),
      `knowledge_orchestrator:1455` (reencauce natural) → dispatch_generation.
      Verificar que cada caller conserva su fallback determinista ante excepción.
- [ ] 3.2 Suites de acuse/reencauce/expediente en verde.

## 4. Migración del extractor (gate de calidad — absorbe G3)

- [ ] 4.1 `turn_extractor:233` y `profile_extractor` (6 sitios) → dispatch_json.
- [ ] 4.2 Matriz de 72 casos contra Gemini: gate igualar/superar benchmark previo
      (recall 0.84 / precisión 1.00). Adaptar few-shots del prompt si hace falta
      (fallos conocidos del eval: fulero crudo, caja seca). NO avanzar sin pasar.
- [ ] 4.3 Retirar el parámetro `model=` de las firmas migradas (era selección de
      modelo Groq).

## 5. Audio nativo (absorbe G2)

- [ ] 5.1 `dispatch_audio` + rama de audio en app.py → Gemini inlineData con
      glosario trailero; contrato de fallo "" (media guard).
- [ ] 5.2 Eval con ≥5 notas de voz reales del usuario (fulero, doble, caja seca):
      criterio 0 destrozos. Regresión del caso conv 163 ("fulero"→"futbol").

## 6. Finalidad conversacional (D5/D8)

- [ ] 6.1 `conversational_purpose` en TurnIntentSignals + few-shots en
      _TURN_INTENT_SYSTEM (incluye consolidar `is_joke_request` ya agregado en
      curso). Tests de parsing + casos idiomáticos ("así que chiste" = queja).
- [ ] 6.2 Orchestrator consume purpose: turno conversacional seguro → respuesta
      generada (persona Mundo + dato del turno) + nudge; textos fijos
      (CONTROLLED_FALLBACK_REPLY, CLARIFICATION, _FRIENDLY_NEUTRAL, DOCUMENT_ACK)
      degradados a fallback de excepción. Guardrails intactos (tests: pago
      fail-closed, requires_human, no-pregunta del friendly).
- [ ] 6.3 Consolidar trabajo en curso: rama del chiste vía turn_signals,
      `_should_use_friendly_llm` ampliado, fix del resumen en `_build_funnel_nudge`
      (usa next_question_from_missing_facts), aliases plurales del seed aplicados
      al Neo4j vivo.
- [ ] 6.4 Auditoría de overlap de Terms (D6): listar aliases que compiten entre
      categorías; retirar Terms conversacionales cuando el extractor los cubra
      (verificado con casos reales). Seed re-aplicado.

## 7. Retiro físico de Groq (D7 — SOLO al final)

- [ ] 7.1 Verificación en vivo de los 4 caminos (texto, JSON, visión, audio) vía
      Gemini con cadencia; logs sin `call_groq`.
- [ ] 7.2 Eliminar `call_groq_*`, `_groq_with_fallback`, `GroqRateLimitError` y el
      import del cliente groq; retirar `groq` de requirements.
- [ ] 7.3 Retirar env `GROQ_*` de `.env` y documentación; actualizar memoria del
      proyecto (config de modelos). ROTAR la GEMINI_API_KEY del eval.
- [ ] 7.4 Suite completa (≈1010 tests) en verde; `openspec validate
      gemini-full-provider-migration`; archivar gemini-natural-recruiter con nota
      de absorción (G2/G3).

## 8. Bloqueos externos

- [ ] 8.1 Decisión de tier pago de Gemini (bloquea 7.x para producción real; en
      staging todo puede completarse con free tier + cadencia).
