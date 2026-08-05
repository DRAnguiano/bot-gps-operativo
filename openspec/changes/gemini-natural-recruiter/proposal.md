## Why

Prueba en producción (conv 163, 2026-07-07, verificada en logs) + eval de factibilidad de
Gemini 2.5 Flash (21 llamadas controladas con prompts reales) revelaron 4 problemas:

1. **El audio destroza la jerga**: Whisper transcribió "fulero" como **"futbol"**
   (log: *"Ya le había comentado que tengo experiencia en futbol"*) — sin vocabulario
   del dominio, los audios de traileros pierden los datos clave. El eval mostró que
   Gemini entiende mejor el contexto y además escucha audio NATIVO (sin paso Whisper).
2. **Vocabulario de dominio incompleto**: *"E doble articulado, recién renovada"* →
   el bot **re-preguntó la licencia** que el candidato acababa de dar. "doble
   articulado"/"doble" = full; "caja seca" suele referir a sencillo; "recién renovada"
   = vigencia implícita. Nada de esto está en el glosario/extractores.
3. **Friendly plano ante comentarios laterales**: "¿está chida la paga?", "¿qué rollo?"
   reciben re-encauce seco en vez de una respuesta cálida CON datos reales del RAG
   ("¡Claro! El rango semanal observado es $X–$Y…") antes de seguir el funnel.
4. **Sin confirmación final de datos**: el funnel cierra sin mostrar el resumen al
   candidato — errores de extracción (como el "futbol") quedan registrados sin que el
   candidato pueda corregirlos.

Eval Gemini (2026-07-07): generación RAG **superior** (fidelidad perfecta en el caso
Infonavit que qwen alucinó, 1.1-1.4s vs 2-6s, sin 429), visión **superior** (clasificó
licencia + extrajo categoría/vigencia/nombre en una llamada), extracción **4/6 sin
adaptar few-shots** (falló fulero→full y caja seca — por eso esta propuesta incluye la
adaptación). Gotcha: `thinkingBudget: 0` obligatorio o trunca JSON. Free tier ~250
req/día → suficiente para validar; producción requiere tier pago (~$0.30/M tokens de entrada).

## What Changes

- **Adapter multi-proveedor + migración por fases a Gemini 2.5 Flash**:
  - Cliente `gemini_client` (REST vía httpx, sin dependencia nueva; `thinkingBudget: 0`
    en JSON; fallback automático a Groq si Gemini falla/agota cuota).
  - **Fase G1 — generación RAG y visión** a Gemini (ya probadas superiores). Groq queda
    de fallback. Mata los 429/latencia y potencia el expediente v2.
  - **Fase G2 — audio nativo**: los audios de Chatwoot van directo a Gemini con el
    glosario trailero en el prompt ("fulero=full, doble articulado=full, caja seca…") —
    se elimina el paso Whisper y el destrozo de jerga. Eval con notas de voz reales
    antes del corte.
  - **Fase G3 — extracción**: few-shots adaptados a Gemini (fulero→full, caja seca,
    doble, vigencias implícitas) y corrida SHADOW contra la matriz de 72 casos; se
    migra SOLO si iguala o supera a qwen (recall 0.84 / precisión 1.00).
- **Glosario de dominio ampliado** (aplica a extractores y seed, HOY, sin esperar a
  Gemini): `doble articulado`/`doble` → full; `caja seca` → sencillo (confianza media,
  se valida en el resumen final); `recién renovada/renovada` → vigencia implícita
  (dispara la pregunta de "¿cuándo vence?" solo si falta el plazo, sin re-preguntar el
  tipo).
- **Friendly aterrizado en RAG**: un comentario lateral de negocio ("está chida la
  paga", "qué rollo con las rutas") recibe respuesta cálida CON el dato real del corpus
  (rango semanal, rutas) + el nudge del funnel — en vez del re-encauce seco. El friendly
  sigue sin preguntar (regla vigente); la pregunta la pone el sistema.
- **Resumen de confirmación al cierre del funnel**: al completar los datos, el bot
  muestra el resumen ("Entonces sus datos quedan: ciudad X, unidad full, licencia E
  vence…, ¿Es correcto?"). "Sí" → cierre normal; corrección → actualiza el fact
  señalado y re-confirma. Es también la red de seguridad contra errores de
  transcripción/extracción.

## Capabilities

### New Capabilities
- `gemini-provider-adapter`: cliente multi-proveedor con fallback, fases de cutover por
  función (generación/visión/audio/extracción), thinkingBudget=0, shadow para extracción.
- `funnel-summary-confirmation`: resumen de datos + "¿Es correcto?" al cierre, con
  corrección de facts.

### Modified Capabilities
- `unified-turn-extraction` / `candidate-profile-extraction`: glosario ampliado (doble
  articulado→full, caja seca→sencillo confianza media, renovada→vigencia implícita).
- `audio-transcription`: audio nativo con glosario de dominio (Fase G2); Whisper queda
  de fallback.
- `message-orchestration`: friendly lateral con dato real del RAG en vez de re-encauce
  seco.

## Impact

- **Código**: `app/gemini_client.py` (nuevo), `app/indexer.py` (dispatch por proveedor),
  `app/app.py` (rama audio), `app/knowledge/turn_extractor.py` + seed (glosario),
  `app/orchestrators/knowledge_orchestrator.py` (friendly RAG + resumen confirmación).
- **Config**: `GEMINI_API_KEY` (ROTAR la key del eval), `LLM_GENERATION_PROVIDER`,
  `LLM_VISION_PROVIDER`, `LLM_AUDIO_PROVIDER` (cutover independiente por función).
- **Riesgo**: medio — proveedor nuevo en el camino vivo. Mitigación: fallback automático
  a Groq, cutover por función con flags, shadow para extracción, y el free tier solo
  para validación (producción = tier pago o volumen limitado).
