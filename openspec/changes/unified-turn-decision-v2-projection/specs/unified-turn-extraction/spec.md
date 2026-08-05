## ADDED Requirements

### Requirement: Facts en namespace canónico único sin mapeos implícitos
Los facts SHALL emitirse y persistirse en el namespace canónico único definido por `funnel_state_planner`: `license.type` (no `license.category`), `license.expiration_text`, `medical.apto_status` y `medical.apto_expiration_text` como facts distintos y explícitos, `documents.proof`, `experience.vehicle_type`. Cualquier clave legacy SHALL mapearse en un único adapter explícito; NO SHALL haber mapeos implícitos ambiguos dispersos.

#### Scenario: Tipo de licencia canónico
- **WHEN** el candidato indica su tipo de licencia
- **THEN** se persiste como `license.type` (y `license.category` legacy se mapea a `license.type` en el adapter, no en múltiples lugares)

#### Scenario: apto_status distinto de vigencia
- **WHEN** se registra el apto médico
- **THEN** `medical.apto_status` (estado) y `medical.apto_expiration_text` (vigencia) se tratan como facts distintos; `apto_status=vigente` requiere una vigencia válida (>3 meses)
