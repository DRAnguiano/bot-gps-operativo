## ADDED Requirements

### Requirement: Friendly lateral aterrizado en datos del corpus
El sistema SHALL responder un comentario o pregunta lateral de negocio en tono casual
("está chida la paga", "qué rollo con las rutas") de forma cálida y CON el dato real
del corpus (vía RAG), en vez de un re-encauce seco. Los guardrails vigentes se
mantienen: el friendly SHALL NOT preguntar (la pregunta la agrega el nudge del
sistema) y el fail-closed de pago sin fuente autorizada SHALL seguir derivando sin
inventar cifras.

#### Scenario: Comentario casual de pago con dato real
- **WHEN** el candidato comenta "¿está chida la paga o qué?" y el corpus tiene el rango
- **THEN** la respuesta es cálida e incluye el dato real (p. ej. el rango semanal
  observado) seguida del nudge del funnel

#### Scenario: Fail-closed intacto
- **WHEN** el comentario pide cifras y no hay fuente autorizada recuperada
- **THEN** se deriva al equipo sin inventar montos (comportamiento vigente)
