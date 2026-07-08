> Orden: dispatch Gemini-único primero (base de todo), luego migración por módulo
> (señales → copy → extractor con gate), audio, finalidad conversacional, y el
> retiro FÍSICO de Groq al final (D7: solo tras verificar todos los caminos en
> vivo). Suite por bloque; cadencia 30-40s en pruebas vivas (5 RPM free tier).

## 1. Base: dispatch Gemini-único + config propia

- [x] 1.1 `gemini_client.py`: `dispatch_generation`/`dispatch_json`(nuevo)/
      `dispatch_vision`/`dispatch_audio`(nuevo) SIN imports ni llamadas a Groq;
      degradación por contrato de error (D1: json-error / "" / excepción al caller).
      Config propia `GEMINI_MODEL`/`GEMINI_MAX_TOKENS`/`GEMINI_TEMPERATURE` (D2);
      thinkingBudget=0 en texto y JSON. Tests con mocks (sin red).
- [x] 1.2 `call_gemini_llm` (indexer): usa config GEMINI_*, captura GeminiError →
      mensaje de disculpa estándar (contrato del caller); `call_llm` enruta siempre
      a Gemini. Tests.
- [x] 1.3 Reescribir tests existentes de fallback-a-Groq (test_gemini_client) al
      contrato Gemini-único; corregir test_friendly_loosening (referencia a
      `_has_joke_request` eliminado).

## 2. Migración de call sites — señales y clasificadores

- [x] 2.1 `turn_intent_classifier:99` → dispatch_json. Suite del clasificador.
- [x] 2.2 `intent_classifier:294` → dispatch_json. `business_route_classifier`:
      RETIRADO en lugar de migrado (decisión del usuario — código huérfano, contrato
      shadow; capability REMOVED vía delta, schema conservado, harness QA degradado
      a ERROR trazable hasta el repunte en 4.2). Suites.
- [ ] 2.3 Smoke vivo (cadencia): un turno real por Telegram → extracción y señales
      correctas vía Gemini, `[gemini_json]` sin errores en logs.

## 3. Migración de call sites — generación de copy

- [x] 3.1 `current_turn:129` (ack LLM), `expediente:398` (acuse),
      `knowledge_orchestrator:1455` (reencauce natural) → dispatch_generation.
      Verificar que cada caller conserva su fallback determinista ante excepción.
- [x] 3.2 Suites de acuse/reencauce/expediente en verde.

## 4. Migración del extractor (gate de calidad — absorbe G3)

- [x] 4.1 `turn_extractor:233` y `profile_extractor` (6 sitios) → dispatch_json.
- [ ] 4.2 Repuntar `scripts/qa_response_matrix.py` al extractor unificado (el
      harness usaba el classifier retirado) y correr la matriz de 72 casos contra
      Gemini: gate igualar/superar benchmark previo (recall 0.84 / precisión 1.00).
      Adaptar few-shots del prompt si hace falta (fallos conocidos del eval: fulero
      crudo, caja seca). NO avanzar sin pasar.
- [ ] 4.3 Retirar el parámetro `model=` de las firmas migradas (era selección de
      modelo Groq).

## 5. Audio nativo (absorbe G2)

- [x] 5.1 `dispatch_audio` + rama de audio en app.py → Gemini inlineData con
      glosario trailero; contrato de fallo "" (media guard).
- [ ] 5.2 Eval con ≥5 notas de voz reales del usuario (fulero, doble, caja seca):
      criterio 0 destrozos. Regresión del caso conv 163 ("fulero"→"futbol").

## 6. Finalidad conversacional (D5/D8)

- [x] 6.1 `conversational_purpose` (smalltalk|queja|agradecimiento|despedida|
      animo|none) en TurnIntentSignals + few-shots en _TURN_INTENT_SYSTEM (10
      campos, misma llamada); validación de dominio en el parsing (valor fuera del
      catálogo → none). Tests de parsing con mocks.
- [x] 6.2 Orchestrator consume purpose: `_PURPOSE_GUIDANCE` inyecta la instrucción
      situacional (queja→empatía, despedida→cierre cálido, animo→sin promesas) al
      prompt del friendly; `_generate_situated_reply` (D8) convierte DOCUMENT_ACK a
      generado-con-fallback (mismo patrón que el chiste). _FRIENDLY_NEUTRAL ya era
      fallback del friendly; CONTROLLED_FALLBACK casi inalcanzable con el catch-all
      ampliado; CLARIFICATION queda determinista (rama dedicada, decisión previa).
      Guardrails verificados por tests (requires_human/high risk bloquean friendly).
- [x] 6.3 Consolidado: rama del chiste vía turn_signals, `_should_use_friendly_llm`
      ampliado, fix del resumen en `_build_funnel_nudge`, seed hr_rules re-aplicado
      al Neo4j vivo (aliases plurales del chiste verificados en la BD).
- [x] 6.4 Auditoría de overlap ejecutada contra el Neo4j vivo: 43 aliases
      compartidos entre Terms. Mayoría benignos (pares duplicados del MISMO intent:
      hola/greeting_basic, pago/payment_question, documentos_requisitos/
      documents_question — candidatos a fusión, no a bug). PELIGROSOS los
      cross-categoría: "cachimba" (rutas_bases vs ambiguous_slang), "siguiente paso"
      (documentos vs process_location), y la clase conv-166: aliases de una palabra
      ("licencia","documentos","pago") que secuestran mensajes compuestos con
      intención conversacional. RETIRO de smalltalk_joke DIFERIDO a 7.1: requiere
      verificar en vivo que is_joke_request lo cubre (bloqueado por cuota 20 RPD).

## 7. Retiro físico de Groq (D7 — SOLO al final)

- [ ] 7.1 Verificación en vivo de los 4 caminos (texto, JSON, visión, audio) vía
      Gemini con cadencia; logs sin `call_groq`.
- [ ] 7.2 Eliminar `call_groq_*`, `_groq_with_fallback`, `GroqRateLimitError`,
      `call_cohere_llm` y los imports de los clientes groq/cohere; retirar `groq` y
      `cohere` de requirements (Cohere también fuera del ecosistema — decisión
      2026-07-07).
- [ ] 7.3 Retirar env `GROQ_*` y `COHERE_*` de `.env` y documentación; actualizar
      memoria del proyecto (config de modelos). ROTAR la GEMINI_API_KEY del eval.
- [ ] 7.4 Suite completa (≈1010 tests) en verde; `openspec validate
      gemini-full-provider-migration`; archivar gemini-natural-recruiter con nota
      de absorción (G2/G3).

## 8. Bloqueos externos

- [ ] 8.1 Decisión de tier pago de Gemini — URGENTE, bloquea TODO el testing:
      verificado contra la API 2026-07-07, la cuota diaria del free tier es de solo
      20 requests/día (GenerateRequestsPerDayPerProjectPerModel-FreeTier: 20), no
      ~250 como se estimó. Con Gemini como proveedor único, 20 RPD ≈ 3-4 turnos de
      conversación al día: no alcanza ni para staging. Opciones: activar billing en
      el proyecto Google (pay-as-you-go, ~$0.30/M tokens de entrada) o el sistema queda degradado (extractor aborta turnos, generación en
      texto de disculpa) hasta el reset diario.
