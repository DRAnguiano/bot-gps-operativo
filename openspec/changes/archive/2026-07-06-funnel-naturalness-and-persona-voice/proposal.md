## Why

El acuse del funnel y la voz de Mundo tienen tres asperezas de naturalidad observadas en producción que restan calidez y consistencia de marca: (1) el bot no aprovecha el nombre ya conocido para personalizar el acuse, (2) la pregunta de unidad repite "full o sencillo" dos veces (redundante), y (3) el LLM a veces se presenta como "Capital Humano", contradiciendo la regla de persona (Mundo habla como parte del equipo de Transmontes, nunca como un tercero). Son mejoras de copy/voz de bajo riesgo, independientes de la lógica del funnel.

## What Changes

- **Trato por nombre de pila**: cuando el nombre se conoce por primera vez en el turno (extraído de una INE por visión o respondido al funnel), el acuse saluda con "Gracias, <nombre>." una sola vez, sin repetir el vocativo en turnos posteriores. Si no hay nombre, se omite el vocativo (sin fallar).
- **Pregunta de unidad sin redundancia**: reemplazar "¿Su experiencia es en tracto full o en sencillo? Las vacantes disponibles son para operadores de tracto full o sencillo." por "Le comento, actualmente tenemos vacantes para operador de tracto full y de sencillo. ¿En cuál tiene experiencia?" (menciona la disponibilidad una sola vez).
- **Persona "no Capital Humano"**: el system message del LLM (`_llm_system_message`) instruye a Mundo a hablar como parte del equipo de reclutamiento de Transmontes y a NUNCA presentarse como "Capital Humano" (las notas internas "Para Capital Humano" no se tocan: son para el equipo, no para el candidato).

## Capabilities

### New Capabilities
- (Ninguna)

### Modified Capabilities
- `message-orchestration`: el acuse del turno personaliza con el nombre de pila la primera vez que se conoce; la pregunta de unidad usa el copy sin redundancia; el system message del LLM fija la voz de Mundo (no "Capital Humano").

## Impact

- **Código afectado**: `app/knowledge/current_turn.py` (`build_current_turn_ack` para el vocativo; texto de la pregunta de unidad), `app/knowledge/tasks_chatwoot.py`/`app/tasks_chatwoot.py` (señal `name_just_learned` calculada contra el snapshot pre-turno), `app/indexer.py` (`_llm_system_message`).
- **Relación con el stash**: el código de referencia ya existe en el stash de la sesión 2026-06-30; se reutiliza, no se reinventa.
- **Riesgo**: bajo; son cambios de copy y un vocativo condicionado. No tocan extracción, persistencia, enrutamiento ni multi-intención.
- **Sin cambio de modelo ni proveedor LLM.**
