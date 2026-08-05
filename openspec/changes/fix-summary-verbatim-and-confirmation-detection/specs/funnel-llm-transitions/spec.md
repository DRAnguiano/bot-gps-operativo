# funnel-llm-transitions — delta

## MODIFIED Requirements

### Requirement: Reformulación acotada a preguntas atómicas

El sistema SHALL aplicar la reformulación LLM de transiciones únicamente a preguntas de funnel atómicas (un solo dato); toda pregunta que porte contenido estructurado — en particular el resumen de datos del candidato — SHALL entregarse verbatim tal como la construyó el funnel determinista, sin pasar por el generador de transiciones.

#### Scenario: El resumen de datos se entrega completo

- **WHEN** el siguiente paso del funnel es la pregunta de confirmación del resumen (encabezado de confirmación + lista de datos capturados)
- **THEN** la respuesta entregada contiene la lista de datos completa y la reformulación LLM no se invoca para ese contenido

#### Scenario: Pregunta atómica sí se reformula

- **WHEN** el siguiente paso del funnel es una pregunta de un solo dato (p. ej. ciudad) y la generación LLM de transiciones está habilitada
- **THEN** la transición generada puede reformular la voz de esa pregunta, sujeta a las validaciones existentes, con el conector determinista como fallback

#### Scenario: Contenido estructurado detectado dentro del generador

- **WHEN** cualquier punto del orquestador invoca el generador de transiciones con una pregunta que contiene marcadores de contenido estructurado (encabezado de resumen o viñetas de datos)
- **THEN** el generador regresa el fallback determinista sin realizar llamada LLM
