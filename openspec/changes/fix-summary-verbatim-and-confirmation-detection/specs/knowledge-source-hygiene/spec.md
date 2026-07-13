# knowledge-source-hygiene — delta

## MODIFIED Requirements

### Requirement: Respuestas sugeridas sin canalización redundante

Los documentos del corpus RAG SHALL incluir la referencia de contacto con horario ("llámenos de 8:00 a 17:30 hrs") únicamente cuando la respuesta requiere genuinamente derivar al equipo (dato no documentado, validación humana, logística); una respuesta sugerida cuyo contenido está completamente documentado en el corpus SHALL terminar en el contenido de negocio, sin coletilla de derivación.

#### Scenario: Respuesta documentada sin coletilla

- **WHEN** el candidato pregunta por un tema completamente documentado en el corpus (p. ej. política de antidoping) durante el funnel
- **THEN** la respuesta entregada contiene la política de negocio y no incluye invitación a llamar en horario de oficina

#### Scenario: Derivación genuina conserva el horario

- **WHEN** la respuesta requiere acción humana fuera del alcance del bot (documentos vencidos por resolver, confirmación de disponibilidad de escuelita)
- **THEN** la referencia de contacto con horario se mantiene como parte de la derivación
