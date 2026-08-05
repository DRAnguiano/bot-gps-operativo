## MODIFIED Requirements

### Requirement: Reintento automático con clave de respaldo en cuota agotada

El sistema SHALL reintentar automáticamente con `GROQ_API_KEY_BACKUP` cuando la clave primaria
devuelve `groq.RateLimitError` (cuota agotada), antes de propagar el error al caller. El sistema
SHALL emitir un log `[groq-fallback]` al activar este camino. Si la clave de respaldo también
falla Y `GROQ_API_KEY_ORG2` está configurada, el sistema SHALL reintentar con esa tercera clave
(perteneciente a una organización Groq distinta con cuota independiente) antes de propagar el error.
Si las tres claves fallan, el error se propaga sin modificación.

#### Scenario: Fallback exitoso con clave de respaldo (sin cambio)

- **WHEN** `call_groq_json` / `call_groq_llm` / `call_groq_with_system` recibe `RateLimitError`
  con la clave primaria Y `GROQ_API_KEY_BACKUP` está configurada
- **THEN** el sistema reintenta con la clave de respaldo y devuelve el resultado exitoso, sin
  que el caller observe el fallo intermedio

#### Scenario: Fallback exitoso con clave de org independiente

- **WHEN** la clave primaria y la clave de respaldo devuelven `RateLimitError` Y
  `GROQ_API_KEY_ORG2` está configurada en el entorno
- **THEN** el sistema reintenta con `GROQ_API_KEY_ORG2` y devuelve el resultado exitoso
- **AND** emite log `[groq-fallback] usando ORG2 — <función>` antes del reintento

#### Scenario: Sin clave de respaldo configurada (sin cambio)

- **WHEN** la clave primaria devuelve `RateLimitError` y `GROQ_API_KEY_BACKUP` no está en el
  entorno
- **THEN** el error se propaga al caller sin cambios

#### Scenario: Todas las claves agotadas

- **WHEN** la clave primaria, la clave de respaldo y `GROQ_API_KEY_ORG2` (si está configurada)
  devuelven `RateLimitError`
- **THEN** el error de la última clave intentada se propaga al caller; el sistema SHALL haber
  registrado cada fallo en el log con su prefijo correspondiente

#### Scenario: Error no-cuota no activa el fallback (sin cambio)

- **WHEN** la llamada a Groq falla con un error distinto a `RateLimitError`
- **THEN** el error se propaga directamente sin intentar claves adicionales

## ADDED Requirements

### Requirement: Presupuesto de historial en llamadas de respuesta conversacional

Para evitar que el costo por turno crezca con la longitud de la conversación, el sistema SHALL
limitar el número de turnos de historial incluidos en el prompt enviado a `call_groq_llm`.
El límite SHALL ser configurable via `GROQ_LLM_HISTORY_TURNS` (default: 6 turnos = 12
mensajes, contando usuario + asistente). Si la conversación tiene más turnos de historial, se
descartan los más antiguos, conservando siempre el system prompt completo y el turno actual.
La persistencia de facts en Postgres NO se ve afectada por el truncado.

#### Scenario: Historial dentro del límite — sin truncado

- **WHEN** el prompt de `call_groq_llm` contiene 6 o menos turnos de historial de conversación
- **THEN** el mensaje se envía sin modificación

#### Scenario: Historial supera el límite — truncado de turnos antiguos

- **WHEN** el prompt contiene más de `GROQ_LLM_HISTORY_TURNS` turnos de historial
- **THEN** se descartan los turnos más antiguos hasta que el historial tenga exactamente
  `GROQ_LLM_HISTORY_TURNS` turnos
- **AND** el system prompt y el turno actual se conservan íntegros
- **AND** los facts del candidato (persistidos en Postgres) no se modifican

#### Scenario: Variable no configurada usa el default

- **WHEN** `GROQ_LLM_HISTORY_TURNS` no está en el entorno
- **THEN** el sistema usa 6 como límite de turnos de historial
