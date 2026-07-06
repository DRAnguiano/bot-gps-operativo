## Why

En producción (conversación 139, tras activar el extractor `llama-3.1-8b-instant`)
aparecieron dos defectos que rompen la experiencia del candidato:

1. **Repetición acumulativa del acuse**: en cada turno el bot re-confirma TODOS los
   datos previos ("Anotado, Francisco I. Madero. Edad anotada... Entendido, operador
   de tracto full. Queda anotado: licencia tipo E...") en lugar de acusar solo el dato
   nuevo. El extractor 8b re-emite los "DATOS YA CONOCIDOS" del prompt como si fueran
   del turno actual (parroteo conocido del 8b), y el acuse no filtra contra lo ya sabido.
2. **No detecta la respuesta a la pregunta de comprobante de renovación**: cuando la
   licencia vence en <3 meses el sistema pregunta "¿Ya tiene el papel o comprobante de
   renovación?"; el candidato responde "Ya tengo comprobante de renovación" / "Si", pero
   el fact `documents.renewal_proof` nunca se persiste y el bot re-pregunta lo mismo en
   bucle infinito.

Ambos bloquean el avance del funnel y dañan la percepción de inteligencia del bot, justo
en la etapa de cierre de perfilamiento.

## What Changes

- **Acuse solo de datos nuevos**: `build_current_turn_ack` SHALL construir el prefijo de
  confirmación únicamente con los facts que son nuevos en el turno actual (ausentes en la
  memoria del lead), no con todo lo que el extractor reporte. Robusto ante el parroteo del
  extractor sin importar el modelo. (Corrige regresión introducida por el change
  `groq-tpd-exhaustion-and-token-budget`.)
- **Propagación de la señal `renewal_proof` en el path activo**: `validate_extraction`
  SHALL emitir un fact `documents.renewal_proof` cuando la extracción del turno trae la
  señal `signals.renewal_proof` (`"si"`/`"no"`). Hoy esa señal se descarta porque solo se
  procesan `extraction.fields`.
- **Confirmación contextual de comprobante de renovación**: `_extract_context_confirmation_facts`
  SHALL mapear una confirmación corta ("Si", "ya tengo") a `documents.renewal_proof="si"`
  (y una negación a `"no"`) cuando la última pregunta del bot fue la de comprobante de
  renovación, igual que ya hace con apto/licencia/cartas.

## Capabilities

### New Capabilities
<!-- Ninguna: ambos defectos son correcciones de comportamiento sobre capabilities existentes. -->

### Modified Capabilities
- `message-orchestration`: el acuse de turno (current-turn guard) SHALL confirmar solo los
  facts nuevos del turno; y la confirmación contextual corta SHALL resolver
  `documents.renewal_proof` según la última pregunta del bot.
- `unified-turn-extraction`: `validate_extraction` SHALL surface la señal
  `signals.renewal_proof` como un fact `documents.renewal_proof` canónico para el path activo
  (tasks_chatwoot → guard → persistencia).

## Impact

- **Código**:
  - `app/knowledge/current_turn.py` — `build_current_turn_ack` (filtrar a facts nuevos) y
    `_extract_context_confirmation_facts` (mapear renewal_proof por contexto).
  - `app/knowledge/turn_extractor.py` — `validate_extraction` (emitir `documents.renewal_proof`
    desde `signals.renewal_proof`).
  - `app/tasks_chatwoot.py` — verificar que `documents.renewal_proof` fluye a `_current_turn_facts`
    y persiste (ya está en `_PERSIST_KEYS`).
- **Tests**: nuevos tests unitarios para acuse-solo-nuevos y para detección de renovación
  por señal y por confirmación contextual; regresión del bucle del funnel.
- **Datos/Servicios**: sin migraciones. Afecta worker (Celery) y el flujo Chatwoot.
  Verificación final en conversación real de Chatwoot.
- **Riesgo**: bajo. Cambios deterministas y acotados; el consumidor
  `_renewal_question_for_short_expiry` ya lee `documents.renewal_proof`.
