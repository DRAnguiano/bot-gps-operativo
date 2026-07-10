## Context

Tres defectos de respuesta verificados en vivo el 2026-07-10 (conv 175, lead chatwoot:174) durante la revisión post-auditoría. Los tres tienen causa raíz identificada con evidencia archivo:línea; ninguno requiere arquitectura nueva.

## Goals / Non-Goals

**Goals**: (1) que la confirmación del resumen sobreviva a turnos compuestos, (2) revivir el re-encauce natural con protección de regresión, (3) voz única en transiciones generadas.

**Non-Goals**: resolver el Bug #3 completo de multi-intent compuesto (investigación aparte, `project_multi_intent_compound_gap`); tocar el routing RAG/embedded question (funciona bien — la pregunta del candidato SÍ se respondió); ampliar `ROUTE1_ALLOWED` (alcance v1 deliberado).

## Decisions

**D1 — La confirmación del resumen se persiste ANTES del gate del guard, no dentro.**
La detección ya existe y es correcta: `extract_current_turn_facts` (current_turn.py:452-465) produce `funnel.summary_confirmed=true` cuando `last_bot_message` matchea `_TOPIC_SUMMARY_CONFIRM` y el mensaje abre con afirmación sin negación — incluso en el turno compuesto real ("Si todo bien señor, me falto preguntarle hacen dopin?") el fact SÍ se computó. Lo que lo mata es el gate: `_guard_should_fire` (tasks_chatwoot.py:617-623) exige `not has_business_question(...)`, y ese turno traía pregunta de negocio, así que el guard entero (incluida la persistencia) se saltó.

Fix: en el worker, si el guard NO dispara pero `_current_turn_facts` contiene `funnel.summary_confirmed=true`, persistir SOLO ese fact (mismo `upsert_lead_fact`, `source="summary_confirm_compound"`) sin tocar el reply del turno — el orquestador sigue respondiendo la pregunta embebida exactamente como hoy. El siguiente turno ya ve el perfil confirmado y avanza al cierre en vez de re-emitir el resumen.

*Alternativa rechazada*: relajar `has_business_question` en el gate — reabriría el bug #3 original (el guard pisaba la respuesta a la pregunta). La persistencia del fact y la autoría del reply son responsabilidades separables; solo la primera debe cruzar el gate.

**D2 — Fix de scope del re-encauce: construir los facts localmente en la rama.**
`handle_message` línea 2217 pasa `active_facts` a `_build_natural_reencauce`, pero esa variable solo existe dentro de `_build_funnel_nudge` (línea 1744, otra función) — `NameError` en cada ejecución, tragado por el `except` de la línea 2226. Fix: construir en la rama un dict local con los facts persistidos (`lead_memory_before`) + los validados del turno (`_pre_validated`), el mismo merge que ya se usa en otros puntos del orquestador. Efecto colateral corregido de paso: hoy `increment_insistence` corre ANTES del crash, así que el contador avanza sin mensaje de re-encauce; con el fix, contador y mensaje vuelven a ir juntos.

**D3 — Test de regresión estructural + funcional para la rama revivida.**
El bug vivió invisible porque el `except Exception` genérico convierte cualquier error de la rama en un log warning. Dos protecciones: (a) test funcional que ejercita `_build_natural_reencauce` vía el flujo con mocks y asserta que produce texto (no None por excepción); (b) test que compila la fuente de `handle_message` y verifica que todo nombre usado en la rama ROUTE1 esté definido en el scope de la función (o al menos que `active_facts` ya no aparezca en ella). El patrón (a) es el principal; (b) es barato y directo contra la clase de bug.

**D4 — Voz única en `generate_funnel_transition_reply`: una línea de prompt.**
Añadir al prompt: Mundo habla en primera persona del singular y trata de usted ("¿Me podría indicar...?"); nunca "indicarnos", "nosotros necesitamos" ni tuteo. Sin validador regex post-generación (la regla de proyecto es prompt sobre diccionario; la degradación determinista ya existe).

## Risks / Trade-offs

- **D1 persiste un fact fuera del guard** → mitigado: es un único fact booleano, con la MISMA detección (regex + anti-negación) que el guard usa hoy; `source` distinto para poder auditar en BD de dónde vino cada confirmación.
- **D2 revive una rama que llevaba tiempo muerta** → su lógica ya estaba probada en tests unitarios de `_build_natural_reencauce`; lo que nunca se probó fue la integración (por eso el NameError sobrevivió). El test D3(a) cubre exactamente eso.
- **Turno compuesto "no + pregunta"** (negación del resumen + duda): sin cambio — la detección existente ya bloquea la confirmación ante negación, y el flujo actual (responder la duda, mantener resumen pendiente) es el correcto.
