## ADDED Requirements

### Requirement: Registro persistente del expediente por candidato, sin imágenes
El sistema SHALL mantener por lead un registro del expediente (facts grupo `expediente`)
con, por documento: estado (`pendiente|declarado|recibido|analizado|ilegible`), dato
extraído mínimo, discrepancia (si existe), y timestamp de recepción. Las imágenes SHALL
NOT persistirse (minimización). La metadata del adjunto de origen (message_id, tipo) SHALL
registrarse en `external_metadata` del mensaje para trazabilidad auditable.

#### Scenario: Documento recibido queda registrado y auditable
- **WHEN** el candidato envía la foto de un documento
- **THEN** el expediente registra tipo/estado/timestamp y el mensaje conserva la metadata
  del adjunto — sin almacenar la imagen

#### Scenario: Re-subida actualiza, no duplica
- **WHEN** el candidato envía dos veces el mismo tipo de documento
- **THEN** el registro de ese tipo se actualiza (última versión gana), sin duplicados

### Requirement: Declarar no es enviar
Decir que se tiene un documento (texto) SHALL marcar estado `declarado`; solo el envío del
adjunto verificado por visión SHALL marcar `recibido`/`analizado`. Los estados son
independientes y visibles por separado.

#### Scenario: "Tengo mi licencia" no palomea
- **WHEN** el candidato escribe que tiene su licencia pero no la envía
- **THEN** el expediente muestra `declarado` y NO `recibido ✓`

### Requirement: Acuse específico por documento con faltantes
Al procesar un documento, el bot SHALL acusar nombrándolo y SHALL indicar qué documentos
del expediente faltan, con la voz natural de Mundo (copy variado por LLM sobre datos
deterministas del registro).

#### Scenario: Acuse con faltantes
- **WHEN** el candidato sube su INE y aún faltan licencia y apto
- **THEN** el bot responde al estilo "Gracias por subir su INE ✓. Nos faltaría su licencia
  federal y su apto médico." (redacción variable, contenido determinista)
