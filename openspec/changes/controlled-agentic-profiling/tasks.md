> Orden: schema+validador primero (testeables sin LLM), luego el prompt en el
> clasificador unificado, luego el shadow en el orchestrator, y la revisión de
> casos reales como gate antes de CUALQUIER activación. Los certificadores
> existentes no se tocan. Cadencia 20s en pruebas vivas (free tier Gemini).

## 1. AgentDecision — schema y parsing

- [x] 1.1 `app/knowledge/agent_decision.py`: dataclass `AgentDecision`
      (public_reply, proposed_facts[{field,value,evidence,confidence}], next_action,
      missing_fields, uncertainty_flags, crm_private_note, handoff_recommendation) +
      parsing tolerante desde el JSON del turno (campo ausente → default neutro;
      next_action fuera de catálogo → None). 13 tests, sin LLM.
- [x] 1.2 Hallazgo previo a esta tarea: `is_joke_request`/`conversational_purpose`
      (Bloque 6 de gemini-full-provider-migration) se habían agregado SOLO al
      prompt de `turn_intent_classifier.py`, que el worker NO llama en el camino
      vivo — `extract_turn` (turn_extractor.py) tiene su propio prompt/parser de
      señales duplicado y nunca los pedía ni parseaba. `is_joke_request` estaba
      muerto en producción (siempre False). Corregido: ambos campos agregados al
      schema y `_parse_signals` de `turn_extractor.py` (6 tests de paridad nuevos).
      Extendido el schema de `_TURN_EXTRACTOR_SYSTEM` (el prompt real del camino
      vivo, no `_TURN_INTENT_SYSTEM`) con la sección `agent_decision` + reglas +
      3 few-shots (multi-dato desordenado, dato incierto, queja sin datos).
      Tokens del prompt: ~2655 → ~3435 (+779, +29%). `TurnExtraction.agent_decision`
      poblado en `extract_turn` vía `parse_agent_decision`. Suite completa
      (898 tests) verde tras el cambio.

## 2. Validador — frontera de autoridad

- [x] 2.1 `app/knowledge/agent_decision_validator.py`: pipeline D2 (evidencia
      literal normalizada → confidence mínima `AGENT_FACT_MIN_CONFIDENCE` (default
      0.7) → contradicción sin corrección explícita → Capa 2 `validate_extraction`,
      mismo camino que el extractor determinista). Log `[AGENT_FACT_REJECTED]` por
      cada descarte con motivo. 15 tests: fact sin evidencia, confidence baja,
      licencia A (no certifica, igual que el extractor determinista), doble
      articulado→full vía catálogo, edad fuera de rango, contradicción
      full→sencillo sin corrección (no pisa + uncertainty_flag).
- [x] 2.2 Frontera dura verificada: test estructural confirma que
      `calculate_candidate_labels` (chatwoot_note_sync.py) no importa ni menciona
      el módulo agéntico — labels siguen saliendo EXCLUSIVAMENTE de ahí.
      `resolve_handoff` (OR puro): 4 tests — no puede desactivar un
      `requires_human` determinista, sí puede activar uno nuevo, y
      `validate_agent_decision` propaga el override al resultado.
      19 tests nuevos. Suite completa: 918 passed, 0 failed.

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
