## ADDED Requirements

### Requirement: Sección Documentos con palomeo por recepción
La Nota IA SHALL incluir una sección "Documentos" que liste licencia federal, apto médico y comprobante laboral (2 cartas membretadas O semanas IMSS), mostrando por cada uno su estado declarado y recibido. Solo el estado **recibido** (imagen verificada por visión) SHALL mostrar palomeo ✓.

#### Scenario: Palomeo solo al recibir
- **WHEN** el candidato declaró tener licencia pero no la ha enviado
- **THEN** la Nota IA muestra "Licencia federal: declarado ✓ | recibido ☐"

#### Scenario: Recepción actualiza la nota
- **WHEN** el candidato envía la imagen de su apto médico y visión la verifica
- **THEN** la Nota IA actualiza "Apto médico: recibido ✓"
