## Why

Revisión en vivo del 2026-07-10 (conv 175, lead chatwoot:174) tras la auditoría completa del proyecto. El flujo de perfilamiento completó bien hasta el resumen, pero se detectaron tres defectos de respuesta reales, verificados en logs y BD:

1. **La confirmación del resumen se pierde en turno compuesto.** El candidato respondió al resumen con "Si todo bien señor, me falto preguntarle hacen dopin?" — el sistema respondió la pregunta de antidoping (RAG) pero `funnel.summary_confirmed` NO se persistió (verificado en `rh_lead_facts_v2`: ausente). El guard que captura la confirmación (`build_current_turn_ack` vía CURRENT_TURN_GUARD) exige "sin pregunta de negocio", y la ruta del turno se fue a RAG. Consecuencia: el siguiente turno re-emite el resumen ya confirmado y el perfil nunca avanza al cierre. Es la clase del Bug #3 documentado en memoria (`project_multi_intent_compound_gap`), reproducido ahora en dirección inversa.

2. **El re-encauce natural (Bloque 3 de empathetic-funnel) está muerto en producción.** `handle_message` usa `active_facts` en la rama de re-encauce (knowledge_orchestrator.py:2217) pero esa variable solo existe en el scope de `_build_funnel_nudge` (línea 1744). El `NameError` lo traga el `except` genérico (línea 2226-2227: `[ROUTE1] omitido por error: name 'active_facts' is not defined` — observado en vivo 19:32:15). Efecto colateral: el contador de insistencia SÍ incrementa (quedó `funnel.insistence_count=1` en BD) sin que se emita el mensaje de re-encauce, así que el candidato puede llegar a la pausa de 1h sin haber recibido nunca los mensajes empáticos intermedios.

3. **Voz inconsistente en las transiciones generadas del funnel** ("¿Podría indicar**me**...?" en un turno, "¿Podría indicar**nos**...?" en el siguiente). El prompt de `generate_funnel_transition_reply` no fija persona gramatical.

## What Changes

- La confirmación del resumen se detecta y persiste de forma determinista, INDEPENDIENTE de la ruta del turno: si el último mensaje del bot fue el resumen de confirmación y el mensaje del candidato abre con afirmación, `funnel.summary_confirmed=true` se persiste aunque el turno se enrute a RAG por una pregunta embebida. La pregunta embebida se sigue respondiendo igual que hoy.
- Se corrige el `NameError` de la rama de re-encauce: los facts en scope (persistidos + validados del turno) se construyen localmente y se pasan a `_build_natural_reencauce`, devolviendo a la vida el Bloque 3. Test de regresión que falle si la rama vuelve a morir en silencio.
- El prompt de `generate_funnel_transition_reply` fija la voz: Mundo habla en primera persona del singular y trata de usted ("¿Me podría indicar...?"), nunca "indicarnos/nosotros".

## Capabilities

### New Capabilities
<!-- ninguna: los tres puntos corrigen requisitos ya existentes -->

### Modified Capabilities
- `funnel-summary-confirmation`: la confirmación sobrevive a turnos compuestos (afirmación + pregunta de negocio).
- `empathetic-funnel-reencauce`: el re-encauce natural vuelve a ejecutarse (fix de scope) y queda protegido por test de regresión.
- `funnel-llm-transitions`: voz gramatical única en las transiciones generadas.

## Impact

- **Código**: `app/orchestrators/knowledge_orchestrator.py` (detección determinista de confirmación previa al routing; fix de scope en rama re-encauce), `app/knowledge/current_turn.py` (línea de voz en el prompt de transición).
- **Tests**: nuevos tests del contrato de confirmación compuesta y regresión del re-encauce; suite completa debe seguir en verde.
- **Sin migraciones de BD, sin cambios de env, sin cambios de API.**
- **Riesgo**: bajo — cambios acotados a ramas ya existentes; la detección de confirmación reutiliza el regex `_TOPIC_SUMMARY_CONFIRM` ya validado.
