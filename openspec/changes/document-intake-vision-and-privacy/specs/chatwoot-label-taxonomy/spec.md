## ADDED Requirements

### Requirement: Labels de unidad separados full/sencillo
La taxonomía SHALL usar `objetivo_full` y `objetivo_sencillo` como labels separados (se retira `objetivo_full_sencillo`). El label se asigna según `experience.vehicle_type`. Cualquiera de los dos SHALL satisfacer el campo de unidad para `perfil_listo`.

#### Scenario: Full asigna objetivo_full
- **WHEN** el candidato declara experiencia en full
- **THEN** se aplica `objetivo_full` (no `objetivo_full_sencillo`) y el campo de unidad queda completo

#### Scenario: Sencillo asigna objetivo_sencillo
- **WHEN** el candidato declara experiencia en sencillo
- **THEN** se aplica `objetivo_sencillo` y el campo de unidad queda completo

#### Scenario: Migración del label combinado
- **WHEN** un lead con `objetivo_full_sencillo` se reproyecta
- **THEN** se re-etiqueta a `objetivo_full` u `objetivo_sencillo` según su fact `experience.vehicle_type`
