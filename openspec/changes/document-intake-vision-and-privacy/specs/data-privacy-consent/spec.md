## ADDED Requirements

### Requirement: Aviso de confidencialidad y consentimiento al primer documento
Al primer documento que el candidato sube, el sistema SHALL enviar un aviso de privacidad simplificado (finalidad = integrar expediente del proceso de contratación; responsable = Transmontes; medios ARCO; enlace al aviso integral) y SHALL registrar el consentimiento (timestamp + versión del aviso). Para datos sensibles (apto médico = salud) el consentimiento SHALL ser expreso.

#### Scenario: Aviso al subir el primer documento
- **WHEN** el candidato sube su primer documento (imagen)
- **THEN** el bot envía el aviso de confidencialidad y registra el consentimiento antes de procesar datos sensibles

#### Scenario: Consentimiento expreso para dato sensible
- **WHEN** el documento es el apto médico (dato de salud)
- **THEN** se requiere una acción afirmativa de consentimiento expreso; sin ella no se procesa el dato sensible

### Requirement: No persistir imágenes de documentos
El sistema SHALL NOT almacenar en la base de datos las imágenes de los documentos. Visión SHALL extraer únicamente el tipo de documento y su estado de recepción (+ metadatos mínimos); la imagen SHALL descartarse tras procesarse.

#### Scenario: La imagen no se guarda
- **WHEN** se procesa la imagen de un documento
- **THEN** solo se persiste `document.<tipo>.received` + metadatos; la imagen no queda en la BD

### Requirement: Retención y eliminación de datos
El sistema SHALL conservar los datos personales solo mientras dure el proceso y SHALL bloquearlos y eliminarlos al concluir la contratación, al no culminar el proceso, o tras un periodo de inactividad definido; y SHALL soportar eliminación a solicitud (derecho de cancelación ARCO).

#### Scenario: Eliminación al finalizar o abandonar
- **WHEN** el proceso concluye o el candidato queda inactivo el periodo definido
- **THEN** sus datos personales se bloquean y eliminan

#### Scenario: Eliminación a solicitud (ARCO)
- **WHEN** el candidato solicita la eliminación de sus datos
- **THEN** el sistema procesa la cancelación y confirma
