## Why

El sistema agota el límite de 100 000 tokens/día (TPD) de Groq en ~20-33 turnos de
conversación durante pruebas, lo que deja el bot sin respuesta el resto del día. El
diagnóstico de logs confirma que **no es un problema de ventana de contexto** (los
~1 648 tokens por solicitud están muy por debajo del límite de 128k): el error es
exclusivamente `rate_limit_exceeded` de tipo `tokens` (TPD). Las tres causas son:

1. El extractor unificado (`turn_extractor`) usa el mismo modelo 70B
   (`llama-3.3-70b-versatile`) que el LLM de respuesta conversacional, siendo que hace
   una tarea de extracción JSON T=0 que el modelo 8B (`llama-3.1-8b-instant`) maneja
   igual de bien a una fracción del costo en tokens.
2. Ambas claves (`GROQ_API_KEY` y `GROQ_API_KEY_BACKUP`) pertenecen a la misma
   organización Groq y comparten el mismo límite TPD; no hay redundancia real de cuota.
3. El historial de conversación enviado a `call_groq_llm` no tiene tope explícito,
   por lo que crece turno a turno y encarece cada solicitud a medida que avanza la
   conversación.

## What Changes

- **Extractor a 8B**: `UNIFIED_EXTRACTOR_MODEL` cambia de `llama-3.3-70b-versatile` a
  `llama-3.1-8b-instant` por defecto. El cambio es configurable via variable de entorno
  sin modificar código. Reducción estimada: ~60-70 % del costo de extracción por turno.
- **Tercera clave de org independiente**: `_groq_with_fallback` acepta una tercera clave
  opcional `GROQ_API_KEY_ORG2` que actúa como fallback real de cuota (organización
  diferente, TPD independiente). Si primaria y backup están agotadas pero hay clave ORG2
  disponible, el turno se procesa en lugar de disparar el gate silencioso.
- **Límite de historial en `call_groq_llm`**: el historial de mensajes enviado al LLM
  de respuesta se recorta a los últimos `GROQ_LLM_HISTORY_TURNS` turnos (default 6,
  configurable). Turnos más antiguos se descartan del prompt sin afectar los facts
  persistidos en Postgres.

## Capabilities

### New Capabilities

*(ninguna — todos los cambios son de implementación o configuración)*

### Modified Capabilities

- `groq-key-fallback`: El requirement de disponibilidad del LLM ahora incluye un tercer
  nivel de fallback (clave de org independiente) antes de disparar el abort silencioso.

## Impact

- `.env` / `docker-compose.yml`: nueva variable `GROQ_API_KEY_ORG2` (opcional) y
  `GROQ_LLM_HISTORY_TURNS` (opcional, default 6).
- `app/indexer.py`: `_groq_with_fallback` acepta `org2_key`; `call_groq_llm` y
  `call_groq_json` lo pasan cuando está disponible; historial de mensajes en
  `call_groq_llm` se trunca.
- `app/knowledge/turn_extractor.py` / `.env`: `UNIFIED_EXTRACTOR_MODEL` apunta a
  `llama-3.1-8b-instant`.
- Tests: unitario de fallback org2, unitario de truncado de historial, integración
  de que el extractor responde correctamente con el modelo 8B.
- `docker compose build worker && docker compose up -d worker`: rebuild necesario para
  hornar el cambio de modelo en la imagen del worker.
