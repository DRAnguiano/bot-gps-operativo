## ADDED Requirements

### Requirement: funnel_state_planner es la única autoridad del funnel
`funnel_state_planner` SHALL ser la única fuente de `profile_ready`, campos completos/faltantes, conflictos, `next_question` y `asked_field_keys`. NO SHALL existir otra definición del "siguiente pendiente" del funnel (se eliminan `current_turn._next_funnel_question_or_none`, `_FUNNEL_STEPS` del nudge y la lista de `intent_orchestrator`).

#### Scenario: Una sola pregunta y una sola autoridad
- **WHEN** se necesita la siguiente pregunta o el estado de completitud
- **THEN** proviene de `funnel_state_planner`, y ningún otro módulo lo recalcula

### Requirement: Preguntas laterales preservan el campo pendiente
Cuando el turno trae una pregunta (RAG/policy/clarificación) y hay un campo del funnel pendiente, el `TurnDecision` SHALL responder la pregunta, `next_question=None`, `should_continue_profile=True`, y NO SHALL avanzar el funnel ni marcar el pendiente como preguntado/respondido; se permite un cierre suave opcional.

#### Scenario: Pregunta de pago mientras falta licencia
- **WHEN** falta la licencia y el candidato pregunta cuánto pagan
- **THEN** el reply responde el pago (desde RAG/policy), NO avanza el funnel, y la licencia sigue pendiente para el siguiente turno

#### Scenario: "Soy de Monterrey" no es pregunta de rutas
- **WHEN** el candidato dice "soy de Monterrey"
- **THEN** se persiste `candidate.city=Monterrey` como dato de perfil y NO se clasifica como pregunta de rutas ni se responde con información de rutas
