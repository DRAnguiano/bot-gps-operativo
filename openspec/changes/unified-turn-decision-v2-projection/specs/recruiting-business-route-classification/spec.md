## ADDED Requirements

### Requirement: Pre-verificación de handoff sin activar human handoff
`pre_handoff_verification` (pregunta del dato mínimo para B1/escuelita/cecati/reingreso) SHALL usar `route != human_handoff` y `requires_human=False`. El escalamiento final a humano SHALL ser explícito (`handoff_reason` seteado + `requires_human=True`), y el ack público lo decide `delivery_policy` — nunca un booleano suelto como única semántica.

#### Scenario: B1 incompleto → pre-verificación, no handoff
- **WHEN** el candidato pide vacante con cruce a EUA (B1) pero falta el dato mínimo (licencia B/E o comprobante)
- **THEN** el turno hace pre-verificación (pregunta el dato) con `requires_human=False` y NO activa human handoff

#### Scenario: B1 completo → handoff con delivery policy
- **WHEN** el dato mínimo B1 está confirmado
- **THEN** se activa el handoff explícito (`handoff_reason="b1"`, `requires_human=True`) y `delivery_policy=ack_then_handoff` entrega el acuse específico antes de escalar

#### Scenario: El ack de handoff lo decide delivery_policy
- **WHEN** se escala un lead a revisión humana
- **THEN** la existencia y contenido del ack público dependen de `delivery_policy` (`ack_then_handoff` vs `suppress`), no de un flag booleano aislado
