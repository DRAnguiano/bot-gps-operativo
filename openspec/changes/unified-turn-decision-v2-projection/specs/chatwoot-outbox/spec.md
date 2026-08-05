## ADDED Requirements

### Requirement: Entrega idempotente vía outbox
La proyección a Chatwoot (mensaje público, nota privada, reemplazo de labels) SHALL pasar por un outbox idempotente indexado por `(lead_key, turn_id, kind)` con `kind ∈ {public_reply, private_note, labels}`. Un retry SHALL leer el outbox y NO reenviar lo ya entregado, sin duplicar reply ni nota.

#### Scenario: Retry no duplica
- **WHEN** la entrega de un turno se reintenta tras un fallo parcial
- **THEN** los kinds ya entregados no se reenvían y no se crean mensajes ni notas duplicadas

#### Scenario: Reemplazo de labels idempotente
- **WHEN** se proyectan los labels de un lead más de una vez con el mismo estado objetivo
- **THEN** el resultado en Chatwoot es el mismo conjunto de labels, sin duplicar ni acumular

### Requirement: La proyección se deriva de V2
El outbox SHALL proyectar a Chatwoot a partir del estado en V2 (reply del turno, nota y labels derivados del stage/facts de V2), no de cálculos paralelos.

#### Scenario: Fuente única V2
- **WHEN** se construye la nota o los labels a enviar
- **THEN** se derivan del stage/facts de V2 del lead, coherentes con el `TurnDecision` del turno
