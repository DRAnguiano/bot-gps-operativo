> Orden: glosario primero (arregla el bug vivo de conv 163 sin depender de Gemini),
> luego resumen de confirmación (red de seguridad), luego el adapter Gemini por fases
> (G1 generación+visión → G2 audio → G3 extracción), y el friendly-RAG al final (usa
> la generación ya migrada). Cada bloque con tests en el mismo PR. ROTAR la key del
> eval al arrancar.

## 1. Glosario ampliado (bug vivo, sin Gemini)

- [x] 1.1 `domain_catalog` (fuente única): `doble articulado`/`doble` → full CONFIRMED;
      `caja seca` → sencillo CONFIRMED (la validación con el candidato la da el resumen
      de confirmación del Bloque 2 — la "confianza 0.7" numérica no aplica con governed
      writes OFF; desviación documentada). Prompt del turn_extractor: jerga de unidades
      + regla "renovada NO es plazo" + few-shots de conv 163. Guard L2 determinista:
      expiration_text con "renovad" se descarta sin perder los demás campos del turno.
- [x] 1.2 Seed Neo4j: `doble` agregado a vehicle_full; nodo vehicle_sencillo NUEVO con
      `caja seca` (confianza 0.75). Aplicado al Neo4j vivo y verificado.
- [x] 1.3 Regresión conv 163 verde: "E doble articulado, recién renovada" → registra
      E + full, y el funnel pregunta SOLO el plazo (no re-pregunta tipo ni unidad).
      9 tests nuevos (test_glosario_unidades.py) + 41 de regresión sin romper.

## 2. Resumen de confirmación al cierre (D6)

- [x] 2.1 `build_funnel_summary` (determinista desde facts, 9 campos) sustituye al
      cierre hasta confirmar; estado `funnel.summary_confirmed` persiste vía guard
      (_PERSIST_KEYS + señal de perfil). `perfil_listo` NO se retrasa por el resumen.
- [x] 2.2 Afirmación → confirmación contextual (marker "es correcto") + cierre en el
      mismo turno; corrección tras el resumen → "Queda corregido — Ciudad: Lerdo.
      ¿Así es correcto?" (re-confirma SOLO el dato cambiado, re-preguntable). 9 tests
      nuevos + 79 de regresión (cierre/ack/funnel) verdes.
- [ ] 2.3 Verificación en vivo del flujo completo con corrección (pendiente prueba
      real del usuario o smoke con conversación completa).

## 3. Adapter Gemini — base (D1/D2)

- [x] 3.1 `app/gemini_client.py`: generate_text/generate_json/generate_vision/
      transcribe_audio vía REST (httpx), thinkingBudget=0 en JSON/vision-json,
      GeminiError tipado (missing_key/timeout/http_error/rate_limited/empty_response).
      17 tests con mocks (sin red real).
- [x] 3.2 `dispatch_generation`/`dispatch_vision`: cutover por función
      (`LLM_GENERATION_PROVIDER`/`LLM_VISION_PROVIDER`, default groq) + fallback
      automático a Groq con log `[gemini_fallback]`. Tests: default sin llamar a
      Gemini, cutover activo sin llamar a Groq, fallback en timeout/429.
- [x] 3.3 Decisión del usuario (2026-07-07): seguir con la key del eval por ahora
      (ya está solo en `.env` gitignored); rotar antes de exponer a producción real.
      Open question 1 (tier) queda abierta para cuando se decida el corte a prod.

## 4. Fase G1 — generación RAG y visión a Gemini

- [x] 4.1 `call_llm` (entrada real de generación RAG): cutover vía
      `LLM_GENERATION_PROVIDER=gemini` con fallback interno (call_gemini_llm →
      dispatch_generation). Smoke contra el pipeline vivo (hr_worker, sin tocar
      .env de prod): Infonavit fiel (1.2s) + anti-alucinación de pago (2.9s) ambos
      OK. Tests de cutover con mocks (3 nuevos, camino default sin llamar a Gemini).
- [x] 4.2 Visión: rama de `app.py` usa `dispatch_vision` con el prompt de producción
      (`_VISION_PROMPT_IMAGE`/`_VISION_PROMPT_STICKER`); fallback a call_groq_vision
      vía `groq_fallback_kwargs`. Smoke con licencia sintética (2.7s): clasificó
      licencia_federal + legible=si, parseado correcto por
      `parse_vision_classification` (compatibilidad confirmada con el Bloque 3 del
      expediente v2).
- [ ] 4.3 Ventana de observación en prod (24-48h) — BLOQUEADA: requiere activar
      `LLM_GENERATION_PROVIDER`/`LLM_VISION_PROVIDER=gemini` en `.env` real (candidatos
      reales), decisión del usuario. Criterio de rollback: apagar la env var (revierte
      al default groq de inmediato, sin redeploy de código).

## 5. Fase G2 — audio nativo (D3)

- [ ] 5.1 Rama audio → Gemini inlineData + glosario trailero en prompt; Whisper
      fallback.
- [ ] 5.2 Eval con ≥5 notas de voz reales del usuario con jerga (fulero, doble, caja
      seca): criterio 0 destrozos de términos del glosario. NO cortar sin pasar.
- [ ] 5.3 Regresión del caso conv 163: "fulero" en audio → full extraído.

## 6. Fase G3 — extracción (solo si iguala benchmark)

- [ ] 6.1 Few-shots Gemini adaptados al glosario completo (los 2 fallos del eval:
      fulero→full crudo, caja seca).
- [ ] 6.2 Shadow contra la matriz de 72 casos (log-only); comparar vs qwen
      (recall 0.84 / precisión 1.00). Migrar SOLO si iguala o supera.

## 7. Friendly aterrizado en RAG (D5)

- [ ] 7.1 Ruta friendly: comentario lateral de negocio → recupera RAG del tema y
      responde cálido con el dato real + nudge. Guardrails: no pregunta, fail-closed
      pago, léxico vigencia. Tests.
- [ ] 7.2 Verificación en vivo: "está chida la paga?" → respuesta con rango real.

## 8. Cierre

- [ ] 8.1 Suite completa en verde; `openspec validate gemini-natural-recruiter`.
- [ ] 8.2 Actualizar memoria del proyecto (config de proveedores por función).
