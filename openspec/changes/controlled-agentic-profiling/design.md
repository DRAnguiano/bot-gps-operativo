## Context

Funnel rígido con parches acumulados vs. certificadores deterministas sólidos ya en
producción (`validate_extraction`, `calculate_candidate_labels`,
`profile_funnel_complete`, resumen de confirmación, expediente). Gemini es el
proveedor único y el clasificador unificado ya devuelve 10 señales por turno en UNA
llamada JSON. Principio del usuario: **el modelo conduce la conversación; el
sistema certifica el perfil.**

## Goals / Non-Goals

**Goals**: conducción conversacional por el LLM expresada como `AgentDecision`
auditable; frontera de autoridad EN CÓDIGO (no solo en prompt); shadow-first con
diff logueado contra el funnel actual; cero llamadas LLM adicionales; activación
incremental por bloques con gate de casos reales.

**Non-Goals**: que el LLM escriba labels/`perfil_listo`/decisiones de elegibilidad;
reemplazar o modificar los certificadores deterministas; retirar el resumen de
confirmación; activar el modo vivo dentro de este change sin revisión del shadow
por el usuario.

## Decisions

**D1 — `AgentDecision` sale de la MISMA llamada del clasificador unificado.**
El JSON del turno crece con una sección `agent_decision`:
```json
{
  "public_reply": "<respuesta al candidato>",
  "proposed_facts": [{"field": "...", "value": "...", "evidence": "<literal del mensaje>", "confidence": 0.0}],
  "next_action": "ask_field:<campo> | answer_question | acknowledge | close_profile | handoff | wait",
  "missing_fields": ["..."],
  "uncertainty_flags": ["..."],
  "crm_private_note": "<nota privada breve o null>",
  "handoff_recommendation": {"recommended": false, "reason": null}
}
```
Cero cuota extra (crítico: 20 RPD free tier). *Alternativa rechazada*: llamada LLM
dedicada por turno — duplica cuota/latencia y separa la decisión de las señales que
la justifican.

**D2 — Frontera de autoridad en código: `agent_decision_validator.py`.**
Pipeline sobre `proposed_facts`, en orden:
1. **Evidencia literal**: `evidence` debe estar (normalizada) dentro del mensaje del
   turno; si no → fact descartado + log `[AGENT_FACT_REJECTED]`. Cubre "no inventar"
   y "no sobrescribir sin evidencia".
2. **Confidence mínima**: < `AGENT_FACT_MIN_CONFIDENCE` (default 0.7) → descartado.
3. **Capa 2 existente**: lo que sobrevive entra por `validate_extraction` (mismos
   catálogos: unidades, B/E, edad 18-70, renovada≠plazo). Un solo camino de
   persistencia — jamás un bypass del agente a BD.
4. **Contradicción**: valor distinto al fact previo sin marcador explícito de
   corrección → NO pisa; se convierte en `uncertainty_flag` visible en la Nota IA.
Etiquetas y `perfil_listo`: EXCLUSIVAMENTE `calculate_candidate_labels` /
`profile_funnel_complete` sobre facts certificados — el validador nunca expone una
API para que el agente los escriba. `handoff_recommendation` solo puede ACTIVAR
revisión humana; nunca desactivar un `requires_human` ya decidido por los overrides
deterministas (B1, reingreso, edad).

**D3 — Shadow no bloqueante (patrón del composer shadow ya en prod).**
Con `AGENTIC_PROFILING_SHADOW=true`: `handle_message` construye y valida el
`AgentDecision` en hilo daemon y loguea `[AGENTIC_SHADOW]`:
`{same_question, funnel_question, agent_question, facts_diff, missing_diff,
rejected_facts, handoff_diff, crm_note}`. El candidato recibe el reply del flujo
actual, la Nota IA no cambia, cero etiquetas del agente.

**D4 — Activación incremental por bloques, cada uno con gate.**
Orden: (1) `next_action`/orden de preguntas — el gap real del funnel rígido (datos
fuera de secuencia); (2) `public_reply`; (3) `crm_private_note` como sección de la
Nota IA; (4) `handoff_recommendation` (solo-activar). Gate por bloque: revisión del
shadow con casos reales por el usuario — acuerdo con el funnel donde el funnel
acierta, y mejora demostrada donde el funnel falla. `proposed_facts` nunca se vuelve
fuente primaria: el extractor unificado sigue corriendo y ambos entran por Capa 2.

**D5 — El funnel rígido queda como certificador de completitud y fallback.**
`missing_fields`/`profile_funnel_complete` deterministas anclan al agente cada turno
(el agente decide CÓMO/CUÁNDO preguntar; el sistema define QUÉ falta). Ante fallo
del agente (GeminiError, JSON inválido, `next_action` fuera de catálogo), el turno
degrada al funnel actual — deja de conducir, nunca deja de existir.

## Risks / Trade-offs

- **Facts inventados por el LLM** → evidencia-literal-o-descarte + Capa 2; queda
  trazado, no persiste.
- **Conducción inconsistente entre turnos** → `missing_fields` determinista ancla
  cada turno; el resumen de confirmación certifica al final.
- **Shadow con muestra sesgada** → el gate exige casos reales revisados por el
  usuario (cadencia de pruebas de 20s por el free tier).
- **El prompt unificado crece** → medir tokens antes/después; si el JSON degrada,
  compactar few-shots antes de considerar una llamada separada.

## Open Questions

1. Umbral `AGENT_FACT_MIN_CONFIDENCE`: ¿0.7 o alineado al 0.75-0.9 por campo de los
   extractores actuales?
2. `crm_private_note`: ¿sección dentro de la Nota IA existente (propuesto, evita
   duplicar notas) o nota de Chatwoot separada?
