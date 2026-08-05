# funnel-summary-confirmation — delta

## MODIFIED Requirements

### Requirement: Detección de confirmación sobre el mensaje previo completo

El sistema SHALL evaluar la detección de confirmación de resumen sobre el contenido completo del último mensaje del bot (no un prefijo truncado), y SHALL reconocer como pregunta de confirmación todas las variantes que el propio sistema emite (formas singulares y plurales de la confirmación de datos y el encabezado de resumen).

#### Scenario: Resumen al final de una respuesta larga

- **WHEN** el último mensaje del bot es una respuesta larga cuyo tramo final contiene el resumen de datos con su pregunta de confirmación, y el candidato responde con una afirmación (sola o acompañada de una pregunta de negocio)
- **THEN** la confirmación del resumen se detecta y `funnel.summary_confirmed` se persiste

#### Scenario: Variante plural de la pregunta de confirmación

- **WHEN** el último mensaje del bot pregunta por la corrección de los datos en forma plural (p. ej. "¿son correctos?") y el candidato afirma
- **THEN** la confirmación se detecta igual que con la forma singular

#### Scenario: Truncado para prompts conserva la pregunta vigente

- **WHEN** el último mensaje del bot excede el límite usado para alimentar prompts LLM
- **THEN** el recorte conserva el tramo final del mensaje (donde vive la pregunta activa), no el inicial
