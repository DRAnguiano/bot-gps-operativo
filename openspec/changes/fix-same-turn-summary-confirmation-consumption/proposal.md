# Proposal — fix-same-turn-summary-confirmation-consumption

## Why

Verificación en vivo (conv 177, 2026-07-13): el candidato confirmó el resumen y preguntó por antidoping en el MISMO mensaje ("Si, todo bien, ¿Hacen dopong?"). El sistema respondió el doping y persistió `funnel.summary_confirmed` (fix anterior), pero la respuesta entregada **volvió a pegar el resumen completo que el candidato acababa de confirmar** — redundante y desorientador. Causa: la persistencia ocurre en el worker DESPUÉS de que el orquestador compuso la respuesta; el nudge de funnel se arma con los facts pre-turno, donde el resumen aún no estaba confirmado, así que `next_question_from_missing_facts` re-emite el resumen. La detección de la confirmación es determinista y ya ocurre dentro del turno — solo que la composición de la respuesta no la consume.

## What Changes

- El merge de facts que alimenta la composición del nudge (`_build_funnel_nudge`) incorpora la confirmación de resumen detectada en el turno actual: si el mensaje del candidato confirma el resumen vigente (misma detección determinista que ya dispara la persistencia), `funnel.summary_confirmed=true` entra a `active_facts` ANTES de calcular la siguiente pregunta.
- Con eso, el turno compuesto (afirmación + pregunta de negocio) responde la pregunta y avanza al cierre (subir documentos) en lugar de re-emitir el resumen.
- La negación/corrección no cambia de comportamiento: el detector no marca confirmación y el flujo de corrección sigue igual.

## Capabilities

### New Capabilities

(ninguna)

### Modified Capabilities

- `funnel-summary-confirmation` (delta sobre los deltas previos sin sync): la confirmación detectada en el turno SHALL consumirse en la composición de la respuesta del MISMO turno, no solo persistirse para turnos futuros.

## Impact

- `app/orchestrators/knowledge_orchestrator.py` — `_build_funnel_nudge` (merge de `active_facts`).
- `app/knowledge/current_turn.py` — sin cambios de lógica (se reutiliza `_extract_context_confirmation_facts`).
- Tests: `tests/test_compound_summary_confirmation.py` (caso de composición mismo-turno).
