## ADDED Requirements

### Requirement: V2 es la única verdad operacional
`rh_leads_v2` SHALL ser la fuente operacional de facts, stage y estado de revisión humana. `release_human_review` SHALL vivir en V2. La DB legacy SHALL quedar read-only durante la transición y luego retirarse; ninguna decisión operativa SHALL depender de legacy tras el cutover.

#### Scenario: Reingreso conserva estado V2
- **WHEN** un candidato con historial regresa
- **THEN** su estado (facts, stage) se lee de V2 y la proyección de labels refleja ese estado, sin depender de legacy

#### Scenario: Release humano modifica V2
- **WHEN** un agente libera la revisión humana de un lead
- **THEN** el cambio se escribe en V2 (`release_human_review`) y la siguiente proyección a Chatwoot elimina el estado de revisión

### Requirement: La memoria assistant guarda el texto exacto entregado
El mensaje assistant persistido SHALL ser idéntico al `reply` entregado al candidato en ese turno.

#### Scenario: Primer contacto — assistant almacenado == enviado
- **WHEN** es el primer contacto y se entrega el saludo/intro
- **THEN** el mensaje assistant guardado en V2 es exactamente el texto enviado (incluido el intro), sin divergencia
