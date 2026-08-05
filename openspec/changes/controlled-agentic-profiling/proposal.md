## Why

El perfilamiento actual es un funnel RÍGIDO de preguntas secuenciales (nombre →
ciudad → edad → unidad → licencia → apto → experiencia → documentos). Cada caso
real que no cabe en esa secuencia — el candidato adelanta tres datos en un mensaje,
responde en desorden, mezcla una duda con un dato — se ha resuelto con un parche
más sobre `_next_funnel_question_or_none` y sus duplicados. El resultado: reglas
parcheadas acumuladas, prompts gigantes, y conversaciones que se sienten de
formulario, no de reclutador.

Al mismo tiempo, lo que SÍ funciona y no debe cambiar es la certificación
determinista: `validate_extraction` (Capa 2: catálogos de unidad, licencia B/E,
edad, vigencias), `calculate_candidate_labels` (27 labels como función pura de
facts), `profile_funnel_complete`, el resumen de confirmación y el expediente.

**Principio central: el modelo conduce la conversación; el sistema certifica el
perfil.**

## What Changes

1. **`AgentDecision` schema** — la salida estructurada del turno agéntico:
   - `public_reply` — la respuesta al candidato.
   - `proposed_facts[]` — datos extraídos con `{field, value, evidence, confidence}`.
   - `next_action` — qué sigue (preguntar campo X, responder duda, cerrar, handoff…).
   - `missing_fields` — lo que el agente cree que falta.
   - `uncertainty_flags[]` — ambigüedades que detectó y no quiso resolver solo.
   - `crm_private_note` — nota privada para Chatwoot (contexto para el reclutador).
   - `handoff_recommendation` — recomendación de pasar a humano, con razón.

2. **Lo que el modelo PUEDE**: decidir la siguiente pregunta y su orden; adaptar el
   tono; interpretar respuestas naturales/desordenadas; proponer datos extraídos con
   evidencia; recomendar handoff; generar la nota privada para Chatwoot.

3. **Lo que el modelo NO PUEDE** (frontera de autoridad, validada en código):
   marcar `perfil_listo` directamente; escribir etiquetas críticas directamente;
   aprobar o rechazar candidatos; inventar políticas, rutas, pagos o requisitos;
   sobrescribir datos previos sin evidencia; ejecutar acciones CRM sin pasar por
   los validadores.

4. **Validación determinista del backend** sobre cada `AgentDecision`:
   evidencia textual por fact (literal en el mensaje del turno); confidence mínima;
   contradicciones contra el estado previo; completitud de campos requeridos;
   emisión segura de etiquetas (solo `calculate_candidate_labels`); condiciones de
   `perfil_listo` (solo `profile_funnel_complete` + resumen de confirmación).

5. **Shadow primero**: el flujo actual se conserva intacto y sigue respondiendo;
   `AgentDecision` corre en paralelo; se loggean las diferencias entre el funnel
   actual y el agente (`[AGENTIC_SHADOW]`); el agente NO emite etiquetas ni
   respuestas hasta validar con casos reales.

6. **Resultado esperado**: conversación más natural; menos reglas parcheadas;
   mejor manejo de respuestas desordenadas; integración sólida con Chatwoot/CRM;
   mayor auditabilidad (cada decisión es un JSON trazable con evidencia); menor
   dependencia de prompts gigantes.

## Capabilities

### New Capabilities
- `agentic-conversation-driver`: el LLM conduce el turno (AgentDecision: siguiente
  pregunta, tono, interpretación, nota CRM, recomendación de handoff), primero en
  shadow.
- `agent-decision-validation`: el backend valida evidencia, confidence,
  contradicciones, completitud, etiquetas y perfil_listo — nada del agente llega a
  BD/CRM sin pasar por aquí.

### Modified Capabilities
- `message-orchestration`: `handle_message` gana la rama shadow del agente; en
  activación por bloques, el agente sustituye la conducción (no la certificación).
- `unified-turn-extraction`: `proposed_facts` entra por el MISMO
  `validate_extraction` (Capa 2) que el extractor actual — un solo camino de
  persistencia.

## Impact

- **Código**: nuevo `app/knowledge/agent_decision.py` (schema, prompt, parsing) y
  `app/knowledge/agent_decision_validator.py`; hook shadow en
  `knowledge_orchestrator.handle_message`. Los certificadores existentes
  (`validate_extraction`, `calculate_candidate_labels`, `profile_funnel_complete`,
  resumen D6) NO se modifican: se reutilizan.
- **Config**: `AGENTIC_PROFILING_SHADOW` (default false) y
  `AGENTIC_PROFILING_ENABLED` (default false; se activa por bloques tras revisar el
  shadow).
- **Cuota LLM**: la decisión agéntica se emite desde la MISMA llamada del
  clasificador unificado (patrón ya validado con `conversational_purpose`) — cero
  llamadas extra; crítico con el free tier de Gemini (20 RPD).
- **Riesgo**: medio. Cambia quién CONDUCE, no quién CERTIFICA. Mitigación:
  shadow-first con diff logueado, validadores ya probados en producción, activación
  por bloque con gate de casos reales, y el funnel rígido queda como fallback
  permanente ante fallo del agente.
