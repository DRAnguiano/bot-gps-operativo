## ADDED Requirements

### Requirement: Gemini como único proveedor LLM
El sistema SHALL enrutar toda llamada LLM (generación, JSON/extracción/clasificación,
visión, audio) exclusivamente por Gemini 2.5 Flash vía los dispatch de
`gemini_client`. Ningún módulo SHALL importar ni invocar funciones de Groq (ni como
camino primario, ni como fallback, ni como override); la config SHALL ser propia de
Gemini (`GEMINI_MODEL`, `GEMINI_MAX_TOKENS`, `GEMINI_TEMPERATURE`,
`GEMINI_TIMEOUT_SECONDS`) sin reciclar constantes `GROQ_*`.

#### Scenario: Extracción va solo por Gemini
- **WHEN** el clasificador unificado procesa un turno
- **THEN** la llamada JSON va a Gemini con thinkingBudget=0 y ninguna función Groq
  se invoca

#### Scenario: Retiro físico de los proveedores anteriores
- **WHEN** la migración se completa y verifica en vivo
- **THEN** `call_groq_*`/`call_cohere_llm`, los clientes groq/cohere y las env
  `GROQ_*`/`COHERE_*` ya no existen en el código ni en `.env`

### Requirement: Degradación por contrato de error, sin proveedor alterno
Ante fallo de Gemini (429/timeout/HTTP/vacío), cada dispatch SHALL degradar con el
contrato de error que sus callers ya manejan — JSON de error (señales neutras /
extracción vacía), string vacío (media guard / transcripción fallida), o excepción
que el caller resuelve con su texto determinista — y el turno SHALL completarse sin
crash y sin invocar otro proveedor.

#### Scenario: Fallo en extracción no tira el turno
- **WHEN** Gemini devuelve 429 durante la extracción de un turno
- **THEN** el dispatch devuelve el JSON de error, el pipeline sigue con señales
  neutras y el candidato recibe respuesta (sin facts nuevos ese turno)

#### Scenario: Fallo en generación degrada a texto determinista
- **WHEN** Gemini falla al generar un acuse/reencauce
- **THEN** el caller usa su fallback determinista y el mensaje sale completo

### Requirement: Supresión de thinking en toda llamada
Toda llamada a Gemini SHALL fijar `thinkingConfig.thinkingBudget: 0` (texto y JSON)
para evitar que el razonamiento consuma `maxOutputTokens` y trunque la respuesta.

#### Scenario: Respuesta conversacional completa
- **WHEN** se genera una respuesta de texto
- **THEN** la petición lleva thinkingBudget=0 y el texto no corta a media palabra

### Requirement: Audio nativo con glosario trailero
Cuando llega una nota de voz, el sistema SHALL transcribirla con Gemini nativo
incluyendo el glosario trailero en el prompt (transcripción fiel de jerga: fulero,
doble articulado, caja seca, apto). El corte SHALL validarse con notas de voz reales
sin destrozos de términos del glosario antes de retirar Whisper.

#### Scenario: Jerga sobrevive la transcripción
- **WHEN** el candidato dice "soy fulero" en una nota de voz
- **THEN** la transcripción conserva el término (no "futbol"/"culero") y la
  extracción registra full
