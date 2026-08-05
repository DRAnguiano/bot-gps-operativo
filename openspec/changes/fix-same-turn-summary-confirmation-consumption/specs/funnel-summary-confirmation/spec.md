# funnel-summary-confirmation — delta

## MODIFIED Requirements

### Requirement: Consumo mismo-turno de la confirmación detectada

El sistema SHALL incorporar la confirmación de resumen detectada en el turno actual a la composición de la respuesta de ese mismo turno: cuando el candidato confirma el resumen vigente (solo o junto con una pregunta de negocio), la parte de funnel de la respuesta SHALL avanzar al siguiente paso del proceso y SHALL NOT re-emitir el resumen ya confirmado.

#### Scenario: Confirmación compuesta avanza en el mismo turno

- **WHEN** el último mensaje del bot contiene la pregunta de confirmación del resumen y el candidato responde con una afirmación acompañada de una pregunta de negocio
- **THEN** la respuesta del turno contesta la pregunta de negocio y su parte de funnel es el paso posterior a la confirmación (cierre/documentos), sin repetir la lista de datos

#### Scenario: Confirmación simple avanza en el mismo turno

- **WHEN** el candidato responde al resumen solo con una afirmación
- **THEN** la respuesta del turno es el paso posterior a la confirmación, sin repetir la lista de datos

#### Scenario: Negación o corrección no avanza

- **WHEN** el candidato responde al resumen negando o corrigiendo un dato
- **THEN** la composición del turno no marca la confirmación y el flujo de corrección existente opera sin cambios
