# groq-key-fallback Specification

## Purpose

Garantizar que el sistema pueda completar llamadas a Groq aunque la clave primaria tenga la
cuota agotada, mediante reintento automático con una clave de respaldo configurada en
`GROQ_API_KEY_BACKUP`. El fallback es stateless, transparente para el caller y observable
en los logs.
## Requirements
### Requirement: Reintento automático con clave de respaldo en cuota agotada

El sistema SHALL reintentar automáticamente con `GROQ_API_KEY_BACKUP` cuando la clave primaria
devuelve `groq.RateLimitError` (cuota agotada), antes de propagar el error al caller. El sistema
SHALL emitir un log `[groq-fallback]` al activar este camino. Si la clave de respaldo también
falla, el error se propaga sin modificación.

#### Scenario: Fallback exitoso con clave de respaldo

- **WHEN** `call_groq_json` / `call_groq_llm` / `call_groq_with_system` recibe `RateLimitError`
  con la clave primaria Y `GROQ_API_KEY_BACKUP` está configurada
- **THEN** el sistema reintenta con la clave de respaldo y devuelve el resultado exitoso, sin
  que el caller observe el fallo intermedio

#### Scenario: Sin clave de respaldo configurada

- **WHEN** la clave primaria devuelve `RateLimitError` y `GROQ_API_KEY_BACKUP` no está en el
  entorno
- **THEN** el error se propaga al caller sin cambios (comportamiento idéntico al actual)

#### Scenario: Ambas claves agotadas

- **WHEN** la clave primaria devuelve `RateLimitError` y la clave de respaldo también devuelve
  `RateLimitError`
- **THEN** el error de la clave de respaldo se propaga al caller; el sistema SHALL registrar
  ambos fallos en el log

#### Scenario: Error no-cuota no activa el fallback

- **WHEN** la llamada a Groq falla con un error distinto a `RateLimitError` (timeout, 5xx,
  formato inválido)
- **THEN** el error se propaga directamente sin intentar la clave de respaldo

### Requirement: Observabilidad del fallback

El sistema SHALL emitir una línea de log con prefijo `[groq-fallback]` cada vez que una
llamada es reintentada con la clave de respaldo, indicando qué función originó el reintento.

#### Scenario: Log al activar fallback

- **WHEN** se activa la clave de respaldo en cualquiera de las tres funciones Groq
- **THEN** se imprime `[groq-fallback] cuota primaria agotada, usando BACKUP — <función>`
  antes de realizar el reintento


### Requirement: Presupuesto de historial en llamadas de respuesta conversacional

Para evitar que el costo por turno crezca con la longitud de la conversación, el sistema SHALL
limitar el historial de mensajes incluido en el prompt del comentario conversacional
(`_answer_friendly_message`) a los últimos 4 mensajes (candidato + asistente combinados),
descartando los más antiguos. El system prompt y el turno actual SHALL conservarse íntegros.
La persistencia de facts en Postgres NO se ve afectada por este truncado.

> Nota de implementación: el límite es fijo (`messages[-4:]`), no configurable por variable de
> entorno — una `GROQ_LLM_HISTORY_TURNS` configurable fue explorada pero no se implementó.

#### Scenario: Historial truncado a los últimos 4 mensajes
- **WHEN** la conversación tiene más de 4 mensajes previos
- **THEN** el prompt del comentario conversacional solo incluye los últimos 4
- **AND** los facts del candidato (persistidos en Postgres) no se modifican
