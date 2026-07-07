## ADDED Requirements

### Requirement: Glosario ampliado de unidades y vigencias implícitas
La extracción SHALL reconocer: `doble articulado`/`doble` (en contexto de unidad) →
`experience.vehicle_type=full`; `caja seca` → `experience.vehicle_type=sencillo` con
confianza media (validada por el resumen de confirmación, nunca decide elegibilidad);
`recién renovada`/`renovada` (licencia/apto) → estado vigente implícito, preguntando
SOLO el plazo restante sin re-preguntar el tipo ya dado. Aplica al prompt del extractor
(few-shots), al seed de vocabulario y a los few-shots de Gemini (Fase G3).

#### Scenario: Doble articulado es full
- **WHEN** el candidato dice "manejo doble articulado" o "traigo doble"
- **THEN** se registra `experience.vehicle_type=full` sin re-preguntar la unidad

#### Scenario: Licencia dada con renovación no se re-pregunta
- **WHEN** el candidato dice "E doble articulado, recién renovada"
- **THEN** se registran licencia E y unidad full, y el funnel pregunta a lo más el plazo
  de vencimiento — nunca vuelve a preguntar el tipo de licencia (bug conv 163)

#### Scenario: Caja seca tiende a sencillo con confirmación
- **WHEN** el candidato dice "manejo caja seca"
- **THEN** se registra sencillo con confianza media y el resumen final lo confirma

