## ADDED Requirements

### Requirement: Clasificación y extracción de datos de documentos por visión
Al recibir un adjunto de imagen (o PDF convertido a imagen), el sistema SHALL clasificar
el tipo de documento (licencia federal, apto médico, INE, carta laboral, semanas IMSS,
comprobante de pago de renovación, CURP, RFC, acta de nacimiento, NSS, comprobante de
domicilio, comprobante de estudios, desconocido) y SHALL extraer solo los datos clave
mínimos por tipo (p. ej. licencia: tipo y vencimiento; apto: solo vigencia, nunca
diagnósticos; INE: nombre y vigencia). Todo valor extraído SHALL pasar por la validación
determinista antes de persistirse; la visión NUNCA persiste directo.

#### Scenario: Licencia legible extrae tipo y vigencia
- **WHEN** el candidato envía la foto de su licencia federal legible
- **THEN** el sistema clasifica "licencia federal", extrae tipo (A/B/E) y vencimiento, y
  los valida deterministamente antes de llenar los facts correspondientes

#### Scenario: Documento ilegible pide re-toma sin sobreescribir
- **WHEN** la imagen es borrosa o la lectura no pasa la validación
- **THEN** el registro queda "recibido, ilegible", NINGÚN fact se sobreescribe, y el bot
  pide con tacto re-tomar la foto

#### Scenario: Apto médico minimizado
- **WHEN** el candidato envía su apto médico
- **THEN** solo se extrae la vigencia; ningún dato clínico/diagnóstico se lee ni persiste

### Requirement: El documento prevalece sobre lo declarado, con marca para Capital Humano
El sistema SHALL actualizar el fact con el valor del documento (fuente `vision_document`)
cuando un dato leído (legible y validado) contradice lo declarado por el candidato; SHALL
registrar la discrepancia en el expediente, SHALL mostrarla en la Nota IA (⚠️ con ambos
valores) para revisión de Capital Humano, y SHALL avisar al candidato con tacto ofreciendo
la alternativa aplicable (p. ej. comprobante de pago si la licencia resultó vencida). El
sistema SHALL NOT decidir elegibilidad final (humano).

#### Scenario: Licencia declarada vigente, documento vencido
- **WHEN** el candidato declaró licencia vigente pero el documento muestra vencimiento pasado
- **THEN** el fact se actualiza a vencida, la Nota IA marca "⚠️ declaró vigente, documento
  muestra vencida <fecha>", y el bot ofrece con tacto la alternativa del comprobante de pago

### Requirement: Soporte de PDF
Los adjuntos PDF SHALL convertirse a imagen (primera página) y entrar al mismo lector de
documentos, en lugar de rechazarse. Si la conversión falla, el bot SHALL pedir una foto
del documento con un acuse amable.

#### Scenario: Licencia en PDF
- **WHEN** el candidato sube su licencia como PDF
- **THEN** se procesa igual que una foto (clasifica + extrae) y se acusa el documento

### Requirement: Extracción en shadow hasta pasar evaluación
La extracción de datos SHALL correr en modo shadow hasta que el modelo de visión pase una
evaluación con fotos reales (legibles y borrosas): registra el resultado en el expediente
pero SHALL NOT sobreescribir facts declarados. El palomeo de recepción sí opera desde el
inicio.

#### Scenario: Modo shadow activo
- **WHEN** la extracción aún no está aprobada y llega un documento con datos que
  contradicen lo declarado
- **THEN** se registra la lectura y la discrepancia en el expediente/Nota IA, pero el fact
  declarado no cambia
