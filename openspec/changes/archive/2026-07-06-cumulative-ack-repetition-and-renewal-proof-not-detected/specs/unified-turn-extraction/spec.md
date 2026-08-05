## MODIFIED Requirements

### Requirement: Capas de validación y política deterministas

La extracción SHALL separarse en tres capas: (1) LLM lenguaje→concepto, (2) validación
determinista contra catálogo cerrado (Neo4j para ciudad, `domain_catalog` para unidad, rango
de edad, catálogo A/B/E para licencia), (3) política de negocio en código. La política de
negocio (inferencia licencia→vacante, clasificación de unidad objetivo/escuelita, documento
por residencia) SHALL NOT residir en el prompt del LLM.

La capa de validación (`validate_extraction`) SHALL surface no solo los campos de
`extraction.fields`, sino también las señales del turno que representan facts del candidato.
En particular, cuando la extracción trae `signals.renewal_proof` con valor `"si"` o `"no"`,
`validate_extraction` SHALL emitir un fact canónico `documents.renewal_proof` con ese valor,
para que el path activo (current-turn guard y persistencia) lo registre. SHALL NOT descartar
silenciosamente esa señal.

#### Scenario: Unidad no-objetivo clasificada por catálogo, no por LLM
- **WHEN** el candidato menciona "torton"
- **THEN** el LLM reporta el término crudo y la capa determinista lo mapea a NON_TARGET (escuelita), sin que el LLM decida el estatus de negocio

#### Scenario: Ciudad validada contra catálogo
- **WHEN** el LLM extrae una ciudad de residencia
- **THEN** la capa determinista la valida/normaliza contra Neo4j; si no hay match, queda como texto crudo de baja confianza y no se afirma como ciudad canónica

#### Scenario: Señal de comprobante de renovación se surfacea como fact
- **WHEN** la extracción del turno trae `signals.renewal_proof = "si"` (candidato dijo "ya tengo
  el comprobante de renovación")
- **THEN** `validate_extraction` emite un fact `documents.renewal_proof = "si"`
- **AND** ese fact fluye al current-turn guard y se persiste, evitando que el funnel re-pregunte

#### Scenario: Señal de renovación ausente no inventa fact
- **WHEN** la extracción del turno trae `signals.renewal_proof = null`
- **THEN** `validate_extraction` no emite ningún fact `documents.renewal_proof`
