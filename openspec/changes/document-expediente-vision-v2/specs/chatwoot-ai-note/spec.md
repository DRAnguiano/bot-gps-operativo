## ADDED Requirements

### Requirement: Sección Documentos del expediente en la Nota IA
La Nota IA SHALL incluir, después de las secciones principales del perfil, una sección
"📄 Documentos (expediente)" con el checklist del expediente completo (licencia federal,
apto médico, INE, comprobante laboral [2 cartas o semanas IMSS], CURP, RFC, acta de
nacimiento, NSS, comprobante de domicilio, comprobante de estudios) mostrando el estado de
cada uno (`pendiente | declarado | recibido ✓ | analizado ✓ [+ dato leído] | ilegible`) y
las discrepancias (⚠️ declarado vs leído). Los documentos pendientes SHALL compactarse
para no inflar la nota. La sección deriva del registro de expediente (facts), nunca del
texto libre del LLM.

#### Scenario: Documento analizado visible con su dato
- **WHEN** la licencia fue analizada por visión (tipo E, vence 03/2027)
- **THEN** la sección muestra "Licencia federal: analizado ✓ · tipo E, vence 03/2027"

#### Scenario: Discrepancia visible para Capital Humano
- **WHEN** existe una discrepancia declarado vs leído en un documento
- **THEN** la sección la muestra con ⚠️ y ambos valores

#### Scenario: Pendientes compactados
- **WHEN** varios documentos del expediente siguen pendientes
- **THEN** se listan compactados en una línea (no una línea por pendiente)
