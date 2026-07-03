## ADDED Requirements

### Requirement: Requisito cumplido por alternativa, sin recordatorio redundante
El comprobante laboral SHALL considerarse cumplido con cartas laborales membretadas **O** semanas cotizadas del IMSS (una de las dos). Cuando el requisito ya está cumplido, el sistema SHALL acusar específico y NO SHALL emitir el recordatorio genérico de "sube tus documentos / nos comunicaremos".

#### Scenario: Cartas basta, sin redundancia (bug conv 160)
- **WHEN** el candidato dice "tengo cartas laborales, no tengo semanas IMSS"
- **THEN** el sistema acusa "con las cartas laborales es suficiente, continuamos" y NO repite el recordatorio genérico de subir todos los documentos

### Requirement: Alternativas aceptadas por requisito
El sistema SHALL aceptar alternativas: comprobante laboral cartas↔IMSS (ofrecer la otra si falta una); licencia/apto médico NO vigente → **comprobante de pago** de renovación/trámite. Ciudad, unidad y experiencia NO tienen alternativa.

#### Scenario: Ofrecer la alternativa de comprobante laboral
- **WHEN** el candidato (local ZM Laguna) dice que no tiene semanas del IMSS
- **THEN** el sistema ofrece las cartas laborales membretadas como alternativa

#### Scenario: Alternativa para licencia/apto no vigente
- **WHEN** la licencia o el apto no están vigentes
- **THEN** el sistema acepta el comprobante de pago de renovación/trámite como alternativa
