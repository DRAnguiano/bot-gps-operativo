## ADDED Requirements

### Requirement: Adapter multi-proveedor con cutover por función
El sistema SHALL soportar Gemini 2.5 Flash como proveedor alterno con selección POR
FUNCIÓN vía configuración (`LLM_GENERATION_PROVIDER`, `LLM_VISION_PROVIDER`,
`LLM_AUDIO_PROVIDER`, `LLM_EXTRACTOR_PROVIDER`), de modo que cada corte sea
independiente y reversible con una variable. Ante fallo/429/timeout de Gemini, el
sistema SHALL reintentar la misma operación vía Groq (fallback automático), y SHALL
registrar el fallback en el log.

#### Scenario: Cutover reversible por función
- **WHEN** `LLM_GENERATION_PROVIDER=gemini` y las demás funciones siguen en groq
- **THEN** solo la generación usa Gemini; visión/audio/extracción no cambian

#### Scenario: Fallback automático a Groq
- **WHEN** Gemini devuelve error o agota cuota en una llamada
- **THEN** la operación se reintenta vía Groq y el turno se completa sin perderse

### Requirement: Supresión de thinking en toda llamada Gemini
El sistema SHALL fijar `thinkingConfig.thinkingBudget: 0` en TODA llamada a Gemini
(JSON y texto conversacional), para evitar que el thinking consuma `maxOutputTokens`
y trunque la respuesta visible antes de terminar.

#### Scenario: Extracción sin truncar
- **WHEN** se pide extracción JSON a Gemini
- **THEN** la petición lleva thinkingBudget=0 y la respuesta es JSON parseable completo

#### Scenario: Generación conversacional sin truncar
- **WHEN** se pide una respuesta de texto (RAG, funnel) a Gemini
- **THEN** la petición lleva thinkingBudget=0 y el texto visible no corta a media
  palabra (bug en vivo 2026-07-07: "El pago en Trans...")

### Requirement: Extracción migra solo tras igualar el benchmark en shadow
La extracción de facts SHALL permanecer en el proveedor actual hasta que Gemini, con
few-shots adaptados al glosario, iguale o supere el benchmark vigente (recall 0.84 /
precisión 1.00 sobre la matriz de 72 casos) corriendo en modo SHADOW (log-only).

#### Scenario: Shadow no afecta el reply
- **WHEN** la extracción Gemini corre en shadow
- **THEN** se loggean divergencias contra el extractor vivo sin afectar respuesta ni
  persistencia

### Requirement: Audio nativo con glosario de dominio
Cuando `LLM_AUDIO_PROVIDER=gemini`, los audios SHALL enviarse a Gemini con el glosario
trailero en el prompt (fulero=full, doble articulado=full, caja seca, apto médico,
R-Control) pidiendo transcripción fiel; Whisper SHALL quedar de fallback. El corte
SHALL requerir un eval previo con notas de voz reales sin destrozos de términos del
glosario.

#### Scenario: Jerga transcrita fiel
- **WHEN** el candidato dice "soy fulero" en una nota de voz
- **THEN** la transcripción conserva el término del dominio (no "futbol"/"culero") y la
  extracción registra full
