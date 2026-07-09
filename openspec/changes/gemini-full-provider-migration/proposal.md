## Why

Dos decisiones del usuario (2026-07-07, tras la Fase G1 de gemini-natural-recruiter):

1. **Groq y Cohere quedan ELIMINADOS del entorno.** No deprecados-con-fallback:
   eliminados. Gemini 2.5 Flash es el ÚNICO proveedor LLM en todos los caminos
   (generación, extracción/clasificación JSON, visión, audio). Cohere hoy solo
   existe como rama nunca-usada de `call_llm` (`LLM_PROVIDER=cohere`) — se retira
   junto con Groq (código, dependencia `cohere` y env `COHERE_*`). Hoy Gemini solo cubre generación RAG y visión;
   TODA la clasificación/extracción (el corazón del sistema) sigue llamando
   `call_groq_json`/`call_groq_with_system` directo. Inventario verificado:
   - `call_groq_json` (9 sitios): turn_intent_classifier:99, turn_extractor:233,
     intent_classifier:294, business_route_classifier:250, profile_extractor
     (119, 216, 270, 420, 528, 552).
   - `call_groq_with_system` (3 sitios): current_turn:129, expediente:398,
     knowledge_orchestrator:1455 (reencauce natural).
   - `call_groq_transcribe` (audio, app.py:1168) — Whisper, que destrozó jerga en
     vivo ("fulero"→"futbol", conv 163).
   - app.py:29 importa `call_groq_vision` ya sin uso en esa rama.
   Ante fallo de Gemini el sistema DEGRADA con sus contratos de error existentes
   (JSON de error → señales neutras, string vacío → media guard, excepción → texto
   determinista del caller) — NUNCA llamando a Groq. Las constantes/config `GROQ_*`
   no se reciclan: la config es propia de Gemini (`GEMINI_MODEL=gemini-2.5-flash`,
   `GEMINI_MAX_TOKENS`, `GEMINI_TEMPERATURE`, `GEMINI_TIMEOUT_SECONDS`).

2. **El extractor debe entender la FINALIDAD del mensaje; las respuestas enlatadas
   se eliminan como camino primario.** Caso vivo (conv 166): "Oye usted no cuenta
   chistes" se perdió porque el Term Neo4j `smalltalk_joke` matchea aliases EXACTOS
   ("chistes" plural no matchea "chiste") y el alias "licencia" de otro Term ganó el
   turno completo → respuesta genérica de requisitos. El JSON real de clasificación
   (`all_matches`) lo confirma: smalltalk_joke nunca compitió. El patrón correcto ya
   se validó con `is_joke_request`: la señal vive en el extractor unificado (misma
   llamada LLM que ya corre cada turno, cero costo extra) y el LLM distingue por
   few-shot la petición real ("cuéntame un chiste") del uso idiomático ("así que
   chiste" = queja). Hoy el bot es "una contestadora que se puede hacer sin LLM":
   gasta tokens clasificando para luego responder con texto fijo
   (CONTROLLED_FALLBACK_REPLY, CONTROLLED_CLARIFICATION_REPLY, _FRIENDLY_NEUTRAL_REPLY,
   DOCUMENT_ACK_REPLY…). La finalidad detectada debe alimentar una respuesta
   GENERADA (persona Mundo, con los datos deterministas del turno), y el texto fijo
   queda solo como degradación ante fallo del LLM.

## What Changes

- **Dispatch Gemini-único en `gemini_client.py`**: `dispatch_generation`,
  `dispatch_json` (nuevo, drop-in de call_groq_json), `dispatch_vision`,
  `dispatch_audio` (nuevo). Ninguno importa ni llama a Groq — ni como fallback ni
  como override. Config propia: `GEMINI_MODEL`/`GEMINI_MAX_TOKENS`/
  `GEMINI_TEMPERATURE`/`GEMINI_TIMEOUT_SECONDS`; thinkingBudget=0 en TODAS las
  llamadas.
- **Migración de los 12 call sites** de clasificación/extracción/generación a los
  dispatch; el parámetro `model` (selección de modelo Groq) se acepta y se ignora
  durante la transición, luego se retira de las firmas.
- **Audio a Gemini nativo** (`dispatch_audio`): transcripción con el glosario
  trailero en el prompt (absorbe la Fase G2 de gemini-natural-recruiter). Whisper
  queda eliminado con el resto de Groq. Cierra el bug "fulero"→"futbol".
- **Limpieza de entorno Groq**: `call_groq_*`/`_groq_with_fallback`/cliente Groq y
  las env `GROQ_API_KEY*`, `GROQ_MODEL`, `UNIFIED_EXTRACTOR_MODEL`,
  `GROQ_CLASSIFIER_MODEL`, `GROQ_WHISPER_MODEL`, `GROQ_VISION_MODEL` se retiran de
  código y `.env` (al final, tras verificar todos los caminos en vivo); los tests
  que mockeaban Groq se reescriben contra los dispatch de Gemini.
- **Extractor de finalidad conversacional**: `TurnIntentSignals` gana
  `conversational_purpose` (valores: `smalltalk`, `queja`, `agradecimiento`,
  `despedida`, `animo`, `none`) además del `is_joke_request` ya agregado — todo por
  few-shot en la MISMA llamada del clasificador unificado.
- **Auditoría de overlap de Terms Neo4j**: detectar aliases que compiten entre
  categorías (el caso "licencia" ganándole al chiste) y mover la detección de
  intención CONVERSACIONAL al extractor few-shot; los Terms quedan solo para
  vocabulario de negocio (lenguaje→concepto), no para intenciones de conversación.
- **Respuestas enlatadas → generadas**: los turnos con finalidad conversacional van
  al LLM friendly (persona Mundo, contexto del lead, datos deterministas del turno);
  cada texto fijo actual se degrada a fallback ante excepción/vacío del LLM.
  Guardrails INTACTOS: fail-closed de pago sin fuente, no-promesa de contratación,
  léxico de vigencia, requires_human/high risk nunca van al friendly.
- **Absorbe el trabajo en curso sin commitear**: `is_joke_request` (señal + prompt +
  consumo en orchestrator + tests), `_should_use_friendly_llm` ampliado, fix del
  resumen de confirmación en `_build_funnel_nudge`, aliases plurales del seed.

## Capabilities

### New Capabilities
- `gemini-only-llm-routing`: Gemini 2.5 Flash como ÚNICO proveedor en todos los
  caminos; degradación por contrato de error propio (sin proveedor alterno);
  config propia GEMINI_*; thinkingBudget=0 siempre.
- `conversational-purpose-extraction`: finalidad del turno por few-shot en el
  clasificador unificado (una sola llamada); respuestas generadas por persona Mundo
  con fallback determinista.

### Modified Capabilities
- `unified-turn-extraction`: nueva señal `conversational_purpose` + `is_joke_request`.
- `message-orchestration`: dispatch de respuesta usa finalidad extraída; textos fijos
  degradados a fallback; guardrails de seguridad sin cambio.
- `audio-transcription`: Gemini nativo con glosario; Whisper eliminado.

## Impact

- **Código**: `app/gemini_client.py`, `app/indexer.py` (retiro de funciones Groq),
  `app/knowledge/{turn_intent_classifier,turn_extractor,intent_classifier,
  business_route_classifier,current_turn}.py`, `app/lead_memory/{profile_extractor,
  expediente}.py`, `app/orchestrators/knowledge_orchestrator.py`, `app/app.py`
  (audio + imports), seed Neo4j, `.env`, y todos los tests que mockeaban Groq.
- **Config**: nuevas `GEMINI_MODEL` (default `gemini-2.5-flash`),
  `GEMINI_MAX_TOKENS`, `GEMINI_TEMPERATURE`;
  retiro de todas las `GROQ_*`. La key del eval se ROTA antes de producción real.
- **Cuota**: TODA la carga LLM pasa a Gemini sin colchón → Gemini 2.5 Flash es el
  default y el protocolo de cadencia en pruebas es OBLIGATORIO (3 RPM / 20s entre
  mensajes);
  producción requiere tier pago ANTES del corte final (sin Groq no hay red).
- **Riesgo**: alto — proveedor único sin red alterna. Mitigación: degradación por
  contrato de error en cada camino (el sistema nunca crashea por fallo LLM),
  migración por módulo con la suite completa (1010 tests) en verde por bloque, y la
  matriz de 72 casos como gate del extractor; la eliminación física del código/env
  Groq es el ÚLTIMO paso, tras verificación en vivo de todos los caminos.
- **Relación con gemini-natural-recruiter**: absorbe sus fases G2 (audio) y G3
  (extracción); ese change se archiva con nota al completar este.
