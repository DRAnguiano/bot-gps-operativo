## MODIFIED Requirements

### Requirement: Confirmación de datos sin duplicaciones

La confirmación (ack) que el sistema emite al registrar datos SHALL usar un solo prefijo de
confirmación y SHALL NOT repetir el mismo fact en dos formas (p. ej. "20 años, 20 años de
experiencia") ni duplicar palabras como "Perfecto".

Además, el ack del current-turn guard SHALL confirmar ÚNICAMENTE los facts que son nuevos en
el turno actual (ausentes en la memoria del lead). SHALL NOT re-confirmar datos ya registrados
en turnos anteriores, aunque el extractor del turno los vuelva a reportar (p. ej. por parroteo
del modelo de los "DATOS YA CONOCIDOS"). El acuse de un turno donde el candidato solo aporta un
dato nuevo SHALL contener solo la confirmación de ese dato más la siguiente pregunta del funnel.

#### Scenario: Ack de ciudad y licencia
- **WHEN** el sistema confirma ciudad y tipo de licencia y agrega la siguiente pregunta
- **THEN** la respuesta contiene un solo "Perfecto"
- **AND** no repite el mismo dato dos veces

#### Scenario: Ack solo del dato nuevo del turno
- **WHEN** el candidato ya tenía registrados ciudad, edad y tipo de vehículo, y en el turno
  actual solo aporta el tipo de licencia
- **THEN** el ack confirma únicamente la licencia (no re-confirma ciudad/edad/vehículo)
- **AND** agrega la siguiente pregunta pendiente del funnel

#### Scenario: Extractor re-reporta datos conocidos
- **WHEN** el extractor del turno reporta facts que ya estaban en la memoria del lead (sin que
  el candidato los haya mencionado de nuevo)
- **THEN** el ack ignora esos facts repetidos y no los incluye en el prefijo de confirmación

## ADDED Requirements

### Requirement: Confirmación contextual corta resuelve el campo según la última pregunta

El sistema SHALL resolver de forma determinista (sin LLM) el campo de perfil correspondiente a
la última pregunta cerrada del bot cuando el candidato responde con una confirmación o negación
corta ("Si", "ya tengo", "no", "todavía no"). Esto incluye apto médico, vigencia de licencia,
cartas laborales y el comprobante/papel de renovación.

En particular, cuando la última pregunta del bot fue la de comprobante de renovación
("¿Ya tiene el papel o comprobante de renovación?"), una confirmación corta SHALL fijar
`documents.renewal_proof = "si"` y una negación corta SHALL fijar `documents.renewal_proof = "no"`.

#### Scenario: Confirmación a la pregunta de comprobante de renovación
- **WHEN** el bot preguntó "¿Ya tiene el papel o comprobante de renovación?" y el candidato
  responde "Si" o "ya tengo comprobante de renovación"
- **THEN** el sistema fija `documents.renewal_proof = "si"`
- **AND** el funnel no vuelve a preguntar por el comprobante de renovación

#### Scenario: Negación a la pregunta de comprobante de renovación
- **WHEN** el bot preguntó por el comprobante de renovación y el candidato responde "no" o
  "todavía no"
- **THEN** el sistema fija `documents.renewal_proof = "no"`
- **AND** el funnel aplica el cierre suave por vencido-sin-trámite en lugar de re-preguntar
