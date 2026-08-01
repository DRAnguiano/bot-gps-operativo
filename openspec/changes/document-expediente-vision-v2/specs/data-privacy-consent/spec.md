## ADDED Requirements

### Requirement: Aviso de confidencialidad y consentimiento expreso
Al recibir el PRIMER documento de un candidato, el sistema SHALL enviar un aviso de
confidencialidad simplificado (responsable, finalidad: integrar expediente del proceso de
contratación, enlace al aviso integral y medios ARCO) y SHALL registrar el consentimiento
(timestamp + versión del aviso). Antes de procesar el apto médico (dato sensible de salud,
LFPDPPP) el consentimiento SHALL ser expreso (acción afirmativa del candidato).

#### Scenario: Primer documento dispara el aviso
- **WHEN** el candidato sube su primer documento
- **THEN** el bot envía el aviso simplificado y registra `expediente.consent` con
  timestamp y versión

#### Scenario: Apto médico requiere consentimiento expreso
- **WHEN** el candidato va a enviar su apto médico sin consentimiento expreso registrado
- **THEN** el bot solicita la confirmación afirmativa antes de procesarlo

### Requirement: Minimización, retención y eliminación
Las imágenes de documentos SHALL NOT almacenarse; solo el estado y los datos mínimos por
tipo. Los datos del expediente SHALL bloquearse y eliminarse al concluir el proceso, tras
el plazo de inactividad definido, o a solicitud del candidato (derechos ARCO), mediante un
proceso de eliminación automatizado. Los datos extraídos de documentos SHALL NOT
imprimirse en logs en claro.

#### Scenario: Imagen no persistida
- **WHEN** visión procesa un documento
- **THEN** la imagen se descarta tras el procesamiento; solo persisten estado + datos mínimos

#### Scenario: Eliminación por retención
- **WHEN** el proceso concluye o vence el plazo de inactividad
- **THEN** el job de purga elimina los facts `expediente.*` del lead

#### Scenario: Solicitud ARCO
- **WHEN** el candidato solicita la eliminación de sus datos
- **THEN** existe un mecanismo para bloquear y eliminar su expediente
