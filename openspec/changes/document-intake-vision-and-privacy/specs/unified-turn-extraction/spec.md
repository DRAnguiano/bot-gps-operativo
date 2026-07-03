## ADDED Requirements

### Requirement: Persistir facts de perfil aunque el turno vaya a RAG
Cuando un mensaje enuncia facts de perfil (apto médico, comprobante laboral, licencia) con marcador explícito o respondiendo la pregunta del funnel, el sistema SHALL persistir esos facts, aunque el mismo turno además dispare una ruta RAG. NO SHALL descartarlos por `field_not_allowed` en la ruta RAG.

#### Scenario: Multi-fact no se pierde por RAG (regresión conv 157)
- **WHEN** el candidato escribe "tengo apto médico vigente, vence en un año y dispongo de cartas laborales membretadas"
- **THEN** se persisten `medical.apto_expiration_text` y `documents.proof`, y el funnel NO vuelve a preguntar por el apto en el siguiente turno

### Requirement: Distinguir declarar vs enviar documento
El extractor SHALL distinguir "declaro que tengo X" (texto → estado declarado / `documents.proof`) de "envío la imagen de X" (adjunto → evento de recepción por visión). El requisito documental (2 cartas membretadas O semanas IMSS, más licencia y apto) SHALL estar explícito para el extractor.

#### Scenario: Declarar tener cartas
- **WHEN** el candidato dice "sí tengo mis cartas laborales"
- **THEN** se registra el comprobante como **declarado**, NO como recibido; no se infiere que envió imagen
