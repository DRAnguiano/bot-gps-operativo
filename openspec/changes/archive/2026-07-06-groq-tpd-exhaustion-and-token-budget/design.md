## Context

El sistema usa Groq Free Tier con límite de 100 000 tokens/día (TPD) compartido por
organización. En producción/testing se agotan en ~20-33 turnos porque:

- El extractor unificado (`UNIFIED_EXTRACTOR_MODEL=llama-3.3-70b-versatile`) consume
  ~1 600 tokens/llamada en el modelo más caro del catálogo.
- Ambas claves comparten la misma org → el backup no aporta cuota adicional ante TPD.
- El historial de `call_groq_llm` crece turno a turno sin cota.

Estado actual de `_groq_with_fallback`: acepta `primary_key` y `backup_key`; si ambas
devuelven `GroqRateLimitError`, relanza la excepción. `call_groq_llm` construye
`messages = [system, user_prompt]` sin truncar historial previo (el `prompt` ya viene
ensamblado por el orquestador, que sí incluye historial).

## Goals / Non-Goals

**Goals:**
- Reducir el consumo TPD por turno ~60-70 % cambiando el extractor a 8B.
- Añadir un tercer nivel de fallback con cuota independiente (distinta org Groq).
- Cotar el historial de mensajes enviado al LLM de respuesta a un máximo configurable.
- Todos los cambios son opt-in via variables de entorno; sin vars → comportamiento
  actual sin cambio.

**Non-Goals:**
- No se cambia el modelo del LLM de respuesta (70B conserva calidad conversacional).
- No se implementa monitoreo de cuota en tiempo real ni alertas automáticas.
- No se sube a Dev Tier de Groq (decisión operativa fuera del alcance del código).

## Decisions

### D1 — Extractor a 8B-instant por defecto en `.env`

El cambio más impactante y de menor riesgo. El extractor hace extracción JSON T=0
(structured output): tarea determinista que no requiere capacidad de razonamiento del
70B. Los clasificadores ya usan 8B-instant satisfactoriamente. El cambio es solo en
`.env` (`UNIFIED_EXTRACTOR_MODEL=llama-3.1-8b-instant`), sin tocar código; el código
ya lee la variable. **No requiere cambio de código**, solo de configuración.

Riesgo: el 8B podría perder matices en textos ambiguos largos. Mitigación: el extractor
tiene un fail-safe (`LLMUnavailableError` / `TurnExtraction` vacía) y el sistema ya
funciona con extracción parcial; si se detecta regresión, revertir la variable.

### D2 — Tercer nivel de fallback `GROQ_API_KEY_ORG2` en `_groq_with_fallback`

Se añade un tercer intento con `org2_key` después de que backup falla. `call_groq_llm`
y `call_groq_json` leen `GROQ_API_KEY_ORG2` y lo pasan a `_groq_with_fallback`.
Si la variable no está configurada, el comportamiento es idéntico al actual.

```python
# Pseudocódigo del nuevo _groq_with_fallback
try: return _groq_call(primary, ...)
except GroqRateLimitError:
    try: return _groq_call(backup, ...)
    except GroqRateLimitError:
        if org2_key:
            print("[groq-fallback] usando ORG2")
            return _groq_call(org2_key, ...)  # puede también fallar → raise
        raise
```

El gate de `LLMUnavailableError` en `turn_extractor` sigue siendo la red de seguridad
si las tres claves fallan.

### D3 — Truncado de historial configurable en `call_groq_llm`

El historial de conversación llega a `call_groq_llm` como parte del `prompt` string
(ensamblado en el orquestador). Para cotar el crecimiento, se introduce
`GROQ_LLM_HISTORY_TURNS` (default 6): si el orquestador pasa un prompt con más de N
pares de turnos, se recortan los más antiguos manteniendo el contexto reciente.

**Alternativa considerada**: truncar en el orquestador (más preciso). **Elegida**: en
`call_groq_llm` con regex de historial porque es más simple y no requiere cambiar la
interfaz del orquestador. Si el formato del prompt cambia, el truncado falla silencioso
(no trunca) y se aplica un fallback de recuento de caracteres.

### D4 — No cambiar firma pública de `_groq_with_fallback`

Para no romper todos los callers, `org2_key` se lee internamente dentro de cada función
caller (`call_groq_llm`, `call_groq_json`, `call_groq_with_system`) en lugar de
añadirse como parámetro. Esto minimiza el diff y el riesgo de regresión.

## Risks / Trade-offs

[Riesgo] 8B-instant extrae peor campos ambiguos (e.g., ciudad con jerga, unidad
vehicular inusual) → Mitigación: fail-safe ya existe; en producción el funnel re-pregunta
si no extrae; monitorear nota privada de Chatwoot en las primeras sesiones post-deploy.

[Riesgo] Truncado de historial elimina contexto relevante de turnos anteriores →
Mitigación: los facts ya están persistidos en Postgres/lead_memory; el historial solo
aporta tono conversacional, no datos. Default de 6 turnos cubre conversaciones normales
(el funnel promedio tiene 8-12 preguntas, pero cada turno tiene su contexto en facts).

[Riesgo] ORG2 también en free tier → mismo límite TPD → Mitigación: la intención es
que ORG2 sea una segunda cuenta Groq distinta; la variable es opcional y el operador
decide. Si no se configura, el comportamiento es el actual.

## Migration Plan

1. Cambiar `.env`: `UNIFIED_EXTRACTOR_MODEL=llama-3.1-8b-instant`.
2. Añadir en `.env` (opcional): `GROQ_API_KEY_ORG2=<clave de segunda org>` y
   `GROQ_LLM_HISTORY_TURNS=6`.
3. Modificar `app/indexer.py`: fallback ORG2 en `call_groq_llm` y `call_groq_json`;
   truncado de historial.
4. Tests unitarios.
5. `docker compose build worker && docker compose up -d worker api`.
6. Verificar en logs: `[groq-fallback] usando ORG2` cuando primaria y backup agotan.
7. Monitorear notas privadas de Chatwoot para calidad de extracción con 8B.
