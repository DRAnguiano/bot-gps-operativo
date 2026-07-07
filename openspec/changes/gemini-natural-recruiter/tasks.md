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

- [ ] 2.1 Generador determinista del resumen desde facts + estado
      `funnel.summary_confirmed`; hook al completar el último dato (antes del cierre).
- [ ] 2.2 Afirmación → cierre normal; corrección → actualiza fact (pipeline de
      correcciones) y re-confirma solo el dato cambiado. Tests de ambos caminos.
- [ ] 2.3 Verificación en vivo del flujo completo con corrección.

## 3. Adapter Gemini — base (D1/D2)

- [ ] 3.1 `app/gemini_client.py`: generate/vision/json/audio vía REST (httpx),
      thinkingBudget=0 en JSON, timeouts, errores tipados. Tests con mocks.
- [ ] 3.2 Dispatch por función (`LLM_*_PROVIDER`) + fallback automático a Groq con log.
      Tests: cutover reversible, fallback en 429/timeout.
- [ ] 3.3 ROTAR la GEMINI_API_KEY del eval; decidir free-limitado vs tier pago (open
      question 1 con el usuario).

## 4. Fase G1 — generación RAG y visión a Gemini

- [ ] 4.1 Generación RAG vía adapter (`LLM_GENERATION_PROVIDER=gemini`); smoke del caso
      Infonavit + anti-alucinación de pago + latencia comparada.
- [ ] 4.2 Visión del expediente vía adapter (clasificación+extracción en una llamada —
      conecta con Bloques 3-4 de document-expediente-vision-v2).
- [ ] 4.3 Ventana de observación en prod (24-48h) con fallback activo; criterio de
      rollback documentado (env var).

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
