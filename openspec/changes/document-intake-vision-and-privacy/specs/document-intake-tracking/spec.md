## ADDED Requirements

### Requirement: Estados declarado vs recibido por documento
El sistema SHALL rastrear por cada documento requerido dos estados independientes: **declarado** (el candidato dijo tenerlo) y **recibido** (envió la imagen y visión la verificó). Decir que se tiene un documento NO SHALL marcarlo como recibido.

#### Scenario: Declarar no es recibir
- **WHEN** el candidato escribe "sí tengo mi licencia y mis cartas"
- **THEN** los documentos quedan en estado **declarado**, NO **recibido**; la Nota IA no palomea recepción

#### Scenario: Enviar imagen marca recibido
- **WHEN** el candidato envía la imagen de un documento y visión lo identifica y lo considera legible
- **THEN** ese documento pasa a **recibido ✓** con metadatos (tipo, timestamp, legible)

### Requirement: Sección Documentos en la Nota IA con checklist
La Nota IA SHALL incluir una sección "Documentos" con el checklist: licencia federal, apto médico, y comprobante laboral (2 cartas membretadas O semanas cotizadas del IMSS según residencia), mostrando declarado/recibido por cada uno.

#### Scenario: Comprobante laboral condicional por residencia
- **WHEN** el candidato es foráneo
- **THEN** el comprobante requerido son 2 cartas laborales membretadas; para local ZM La Laguna, cartas O semanas IMSS

#### Scenario: Documento ilegible
- **WHEN** visión recibe una imagen pero no puede verificar el documento
- **THEN** se marca "recibido, ilegible" para revisión humana; NO se decide elegibilidad automáticamente
