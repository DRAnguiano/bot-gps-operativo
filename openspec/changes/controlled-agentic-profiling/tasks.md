> Orden: schema+validador primero (testeables sin LLM), luego el prompt en el
> clasificador unificado, luego el shadow en el orchestrator, y la revisión de
> casos reales como gate antes de CUALQUIER activación. Los certificadores
> existentes no se tocan. Cadencia 20s en pruebas vivas (free tier Gemini).

## 1. AgentDecision — schema y parsing

- [ ] 1.1 `app/knowledge/agent_decision.py`: dataclass `AgentDecision`
      (public_reply, proposed_facts[{field,value,evidence,confidence}], next_action,
      missing_fields, uncertainty_flags, crm_private_note, handoff_recommendation) +
      parsing tolerante desde el JSON del turno (campo ausente → default neutro;
      next_action fuera de catálogo → None). Tests con mocks.
- [ ] 1.2 Extender el schema de `_TURN_INTENT_SYSTEM` con la sección
      `agent_decision` + few-shots (caso desordenado multi-dato, caso duda+dato,
      caso queja sin datos). Medir tokens del prompt antes/después. Tests de parsing.

## 2. Validador — frontera de autoridad

- [ ] 2.1 `app/knowledge/agent_decision_validator.py`: pipeline D2 (evidencia
      literal → confidence mínima → Capa 2 `validate_extraction` → contradicción
      sin corrección explícita → uncertainty_flag). Log `[AGENT_FACT_REJECTED]`
      por descarte. Tests: fact inventado, confidence baja, licencia A, caja seca,
      contradicción full→sencillo sin corrección.
- [ ] 2.2 Frontera dura: verificación (tests) de que ningún código del agente llama
      a escritura de labels/stage/perfil_listo — labels siguen saliendo solo de
      `calculate_candidate_labels`; handoff_recommendation solo-activar (test: no
      puede desactivar requires_human de B1/reingreso/edad).

## 3. Shadow en el orchestrator

- [ ] 3.1 Hook en `handle_message` bajo `AGENTIC_PROFILING_SHADOW` (default false):
      hilo daemon no bloqueante (patrón composer shadow), log `[AGENTIC_SHADOW]`
      con diff {same_question, funnel_question, agent_question, facts_diff,
      missing_diff, rejected_facts, handoff_diff, crm_note}. Cero cambios en reply/
      labels/Nota IA. Tests con mocks (shadow no altera el resultado del turno).
- [ ] 3.2 Suite completa en verde con el shadow apagado Y encendido (mockeado).
- [ ] 3.3 Activar `AGENTIC_PROFILING_SHADOW=true` en staging; conversaciones de
      prueba del usuario (cadencia 20s) cubriendo: funnel ordenado, datos en
      desorden, duda+dato, corrección, insistencia. Recolectar logs.

## 4. Revisión del shadow (gate del usuario)

- [ ] 4.1 Analizar `[AGENTIC_SHADOW]` de los casos reales: % de acuerdo con el
      funnel donde el funnel acierta; casos donde el agente maneja mejor el
      desorden; facts rechazados por el validador y por qué. Reporte al usuario.
- [ ] 4.2 Decisión del usuario sobre activación del Bloque 1 (next_action/orden de
      preguntas) — BLOQUEADO hasta 4.1.

## 5. Activación incremental (post-gate, cada bloque con su propio gate)

- [ ] 5.1 Bloque 1: next_action conduce el orden de preguntas
      (`AGENTIC_PROFILING_ENABLED` + degradación al funnel ante fallo — D5). Tests
      de degradación. Verificación en vivo.
- [ ] 5.2 Bloque 2: public_reply sustituye conector+pregunta del guard. Guardrails
      re-verificados (no promesas, léxico vigencia, fail-closed pago).
- [ ] 5.3 Bloque 3: crm_private_note como sección de la Nota IA (resolver open
      question 2 con el usuario antes).
- [ ] 5.4 Bloque 4: handoff_recommendation solo-activar en vivo.

## 6. Cierre

- [ ] 6.1 Suite completa en verde; `openspec validate controlled-agentic-profiling`.
- [ ] 6.2 Actualizar memoria del proyecto (arquitectura conduce/certifica, estado
      de bloques activados).
