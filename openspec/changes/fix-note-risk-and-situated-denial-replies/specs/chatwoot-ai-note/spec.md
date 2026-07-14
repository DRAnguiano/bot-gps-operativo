# chatwoot-ai-note — delta

## MODIFIED Requirements

### Requirement: Nota de riesgo por señal del turno, sin línea redundante

La nota IA de tipo riesgo SHALL emitirse únicamente cuando el turno actual porta señal de riesgo; los turnos posteriores sin señal SHALL producir la nota que corresponda a su propio contenido, aunque el lead conserve un nivel de riesgo histórico. El cuerpo de la nota de riesgo SHALL NOT incluir una línea separada de nivel de riesgo ("Riesgo: Alto"): el título, el estado y "Requiere Agente" comunican la situación.

#### Scenario: Turno con señal de riesgo

- **WHEN** el turno actual es clasificado con nivel de riesgo alto
- **THEN** la nota emitida es de tipo riesgo, con título y estado que lo comunican, sin línea separada "Riesgo: Alto"

#### Scenario: Turno posterior sin señal

- **WHEN** un turno posterior del mismo lead es clasificado con riesgo bajo
- **THEN** la nota emitida corresponde al contenido de ese turno (p. ej. perfilamiento), no al riesgo histórico del lead
