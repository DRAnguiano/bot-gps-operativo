## ADDED Requirements

### Requirement: El modelo conduce el turno mediante AgentDecision
El sistema SHALL obtener por turno un `AgentDecision` estructurado (public_reply,
proposed_facts[], next_action, missing_fields, uncertainty_flags[],
crm_private_note, handoff_recommendation) emitido por el LLM DENTRO de la misma
llamada del clasificador unificado (sin llamadas adicionales), con el cual el
modelo puede decidir la siguiente pregunta y su orden, adaptar el tono, interpretar
respuestas naturales o desordenadas, proponer datos con evidencia, recomendar
handoff y generar la nota privada para Chatwoot.

#### Scenario: Candidato adelanta varios datos en desorden
- **WHEN** el candidato responde "soy de Lerdo, manejo full desde hace 10 años y mi
  licencia E vence en 2027" a la pregunta del nombre
- **THEN** el AgentDecision propone los cuatro facts con evidencia y elige como
  next_action preguntar solo lo que realmente falta (el nombre), sin re-preguntar lo
  ya dicho

#### Scenario: El agente decide el orden, el sistema define qué falta
- **WHEN** el backend entrega al agente los missing_fields deterministas del turno
- **THEN** el agente elige cuál preguntar y cómo, pero no puede declarar completo un
  perfil con campos requeridos faltantes

### Requirement: Shadow primero, sin efectos visibles
El sistema SHALL conservar el flujo actual como único emisor de respuestas,
etiquetas y notas mientras `AGENTIC_PROFILING_SHADOW` esté activo y la conducción
agéntica no haya sido activada; el AgentDecision SHALL correr en paralelo (no
bloqueante) y SHALL loguearse `[AGENTIC_SHADOW]` con el diff contra la decisión del
funnel actual (pregunta elegida, facts, missing_fields, handoff). El agente SHALL
NOT emitir etiquetas ni respuestas hasta validar casos reales.

#### Scenario: Shadow no altera la conversación
- **WHEN** un turno se procesa con el shadow activo
- **THEN** el candidato recibe exactamente la respuesta del flujo actual y el diff
  queda logueado para análisis

#### Scenario: Fallo del agente no afecta el turno
- **WHEN** el AgentDecision falla (error LLM, JSON inválido, next_action desconocido)
- **THEN** el turno se completa por el flujo actual sin degradación visible

### Requirement: Activación incremental con fallback permanente
La conducción agéntica SHALL activarse por bloques (orden de preguntas → reply →
nota CRM → handoff), cada bloque tras revisar el shadow con casos reales; y ante
cualquier fallo del agente en modo activo, el turno SHALL degradar al funnel
determinista actual, que permanece como fallback permanente.

#### Scenario: Degradación en vivo
- **WHEN** la conducción agéntica está activa y el AgentDecision de un turno es
  inválido
- **THEN** ese turno lo conduce el funnel determinista y el fallo queda logueado
