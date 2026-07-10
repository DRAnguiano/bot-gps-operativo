# funnel-summary-confirmation

## MODIFIED Requirements

### Requirement: La confirmación del resumen sobrevive a turnos compuestos

El sistema SHALL persistir `funnel.summary_confirmed=true` cuando el último mensaje del bot fue el resumen de confirmación y el candidato responde con una afirmación sin negación, AUNQUE el mismo mensaje contenga una pregunta de negocio que enrute el turno a RAG. La respuesta a la pregunta embebida se emite igual que hoy; solo la persistencia del fact cruza el gate del guard.

#### Scenario: Afirmación + pregunta de negocio en el mismo mensaje

- **GIVEN** el último mensaje del bot es el resumen de confirmación ("...¿Así es correcto?")
- **WHEN** el candidato responde con una afirmación seguida de una pregunta de negocio (p. ej. una duda de antidoping — el mensaje literal es solo ejemplo)
- **THEN** `funnel.summary_confirmed=true` queda persistido en los facts del lead
- **AND** la pregunta de negocio recibe su respuesta RAG normal en el mismo turno
- **AND** el siguiente turno de perfilamiento NO re-emite el resumen

#### Scenario: Negación del resumen + pregunta no confirma

- **GIVEN** el último mensaje del bot es el resumen de confirmación
- **WHEN** el candidato responde con una corrección o negación acompañada de una pregunta
- **THEN** `funnel.summary_confirmed` NO se persiste
