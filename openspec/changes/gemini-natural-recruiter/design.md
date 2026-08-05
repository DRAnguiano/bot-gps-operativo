## Context

Logs de conv 163 (2026-07-07): Whisper transcribió "fulero"→"futbol"; "E doble
articulado, recién renovada" re-preguntó licencia; comentarios laterales reciben
re-encauce seco; el funnel cierra sin confirmar los datos con el candidato. Eval de
Gemini 2.5 Flash (21 llamadas, prompts reales): RAG y visión superiores; extracción 4/6
sin adaptar; audio nativo sin probar. Ver memoria `project_gemini_flash_eval`.

## Decisions

**D1 — Adapter por FUNCIÓN, no big-bang.** `app/gemini_client.py` expone las mismas
firmas que las funciones Groq equivalentes (generate, vision, audio, json). Un dispatch
por env decide el proveedor POR FUNCIÓN (`LLM_GENERATION_PROVIDER`/`LLM_VISION_PROVIDER`
/etc., valores `gemini`|`groq`). Cada corte es independiente y reversible con una env
var. Fallback automático: excepción/429/timeout de Gemini → misma llamada vía Groq
(patrón `_groq_with_fallback` existente, extendido a proveedor). *Alternativa
descartada*: migrar todo de golpe — sin fallback probado sería apostar el camino vivo a
un proveedor recién evaluado.

**D1b — Groq deprecado como default (decisión del usuario, 2026-07-07).** Tras
verificar generación/visión en vivo (Bloque 4), el usuario decidió que Gemini sea el
camino PRINCIPAL, no solo una opción activable: `_provider()` en gemini_client.py
default cambió de `"groq"` a `"gemini"` — sin fijar ninguna env var, el sistema ya usa
Gemini. Groq sigue vivo únicamente como fallback automático (D1) y como override
explícito (`LLM_*_PROVIDER=groq`, útil para debug/comparación). No se eliminó código
Groq — sigue siendo la red de seguridad.

**D2 — `thinkingBudget: 0` SIEMPRE, en TODAS las llamadas Gemini (JSON y texto).**
Hallazgo del eval: el thinking por default consume `maxOutputTokens` y trunca el JSON
(0/6 → 4/6 al apagarlo). Ampliado 2026-07-07 (bug en vivo, Fase G1): la generación
conversacional (`generate_text`, sin thinkingBudget) también se truncaba a media
palabra ("El pago en Trans...") — el thinking invisible consumía el presupuesto antes
de terminar el texto visible. Se revierte la idea original de "thinking bajo si
mejora calidad" — la fiabilidad de una respuesta completa a un candidato real pesa
más que el margen de pulido que daría el razonamiento.

**D3 — Audio nativo con glosario en el prompt (Fase G2).** El audio de Chatwoot se envía
a Gemini como `inlineData` con instrucción de transcripción + el glosario trailero
("fulero/fulera=operador de tracto full; doble articulado/doble=full; caja seca=remolque
seco, suele implicar sencillo; sencillo; apto médico; R-Control…") y ejemplos de las
confusiones conocidas (futbol/culero ≠ fulero). Se pide SOLO la transcripción fiel (el
análisis de tono queda para después — no es requisito hoy). Whisper queda de fallback.
Eval previo al corte: notas de voz reales del usuario con jerga (mínimo 5), criterio:
0 destrozos de términos del glosario.

**D4 — Glosario ampliado HOY, agnóstico del proveedor.** Reglas de negocio confirmadas
por el usuario (2026-07-07):
- `doble articulado` / `doble` (contexto unidad) → `experience.vehicle_type=full`.
- `caja seca` → `experience.vehicle_type=sencillo` con confianza MEDIA (0.7): se
  registra pero el resumen de confirmación (D6) lo valida — corrige la regla previa
  que lo trataba como solo-remolque/ambiguo.
- `recién renovada` / `renovada` (licencia/apto) → estado vigente implícito; el funnel
  pregunta SOLO el plazo ("¿cuándo vence?") sin re-preguntar el tipo ya dado.
Aplica a: prompt del turn_extractor (few-shots), profile_extractor, seed Neo4j
(vocabulario), y a los few-shots de la Fase G3 de Gemini.

**D5 — Friendly lateral aterrizado en RAG.** Cuando el turno es un comentario/las
pregunta lateral de negocio en tono casual ("está chida la paga", "qué rollo con las
rutas"), la ruta friendly consulta el RAG del tema y responde cálido CON el dato real
("¡Claro! El rango semanal observado va de $X a $Y, y suele salir mejor al publicado…")
+ el nudge del sistema. Guardrails vigentes intactos: el friendly NO pregunta (la
pregunta la pone el nudge), fail-closed de pago sin fuente autorizada (deriva, no
inventa), léxico de vigencia.

**D6 — Resumen de confirmación al cierre.** Al completarse el último dato del funnel,
ANTES del cierre actual: "Entonces sus datos quedan así: 📋 ciudad X · edad N · unidad
full · licencia E vence… · experiencia N años · comprobante laboral: cartas. ¿Es
correcto?" — datos deterministas de los facts (no LLM). "Sí" → cierre normal
(documentos). Corrección ("la ciudad es Lerdo") → actualiza el fact vía el pipeline de
correcciones existente y re-confirma solo el dato cambiado. Estado del resumen en
`funnel.summary_confirmed` para no repetirlo. Es la red de seguridad contra errores de
transcripción/extracción (el caso "futbol").

**D7 — Free tier solo para validación.** ~250 req/día alcanza para shadow/eval, no para
producción abierta. El corte a producción de cada fase asume tier pago de Gemini o
límite de volumen explícito. La key del eval se ROTA al empezar la implementación.

## Risks / Trade-offs

- **Proveedor nuevo en el camino vivo** → fallback Groq automático + cutover por
  función + shadow para extracción.
- **caja seca→sencillo puede equivocarse** → confianza media + resumen de confirmación
  lo corrige con el candidato; nunca decide elegibilidad.
- **Audio nativo puede alucinar transcripción** → eval con notas reales antes del corte;
  Whisper fallback; el resumen de confirmación es la última red.
- **Resumen añade un turno al funnel** → aceptado: el costo de un turno < el costo de
  datos erróneos en el expediente (decisión de negocio del usuario).
- **Doble dependencia de cuota (Groq+Gemini)** → mejor que hoy: dos pools independientes.

## Open Questions

1. ¿Tier pago de Gemini desde el arranque de la Fase G1, o validar 1-2 semanas en free
   con volumen limitado?
2. Análisis de tono en audio (molesto/tranquilo) — ¿se quiere como señal para la Nota
   IA en una fase posterior? (Hoy: NO, solo transcripción fiel.)
