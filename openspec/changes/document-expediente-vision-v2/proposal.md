## Why

La auditoría completa del proyecto (2026-07-06, 6 auditores especializados: arquitectura,
backend, RAG, DevOps, seguridad, QA) confirmó que el pipeline de documentos es el área
menos avanzada del producto (~35%) y la que falta para cerrar el ciclo del reclutador:

- **La visión YA lee imágenes pero no deja rastro**: `call_groq_vision` interpreta la
  imagen, su texto **sustituye** el mensaje y alimenta el funnel — pero no se registra
  QUÉ documento fue, ni queda evento "documento recibido", ni aparece en la Nota IA.
  Ante una disputa o auditoría no hay forma de reconstruir qué llegó (backend §4/§5.11).
- **No hay expediente digital**: no existe tabla/registro de adjuntos por candidato; la
  Nota IA solo deriva texto de facts, no una lista de documentos reales (arquitecto §5).
- **PDFs se rechazan**: un candidato que sube su licencia como PDF recibe un mensaje
  enlatado, sin acuse ni registro (backend §4, RAG §5).
- **Cero marco de privacidad**: las imágenes ya viajan a Groq (tercero) sin consentimiento
  registrado; el apto médico es dato sensible de salud (LFPDPPP) sin retención/borrado ni
  cifrado (seguridad §2). Bloqueante legal antes de escalar.
- La propuesta previa `document-intake-vision-and-privacy` (PR #17) cubría recepción
  (declarado/recibido ✓) y el marco legal, pero limitaba visión a "recibido sí/no". El
  negocio decidió (2026-07-06) ir más lejos: **la visión LEE y EXTRAE datos** de cada
  documento. **Esta v2 ABSORBE a #17** (que se cierra a su favor); lo ya implementado de
  #17 (split objetivo_full/sencillo) se excluye.

Decisiones de negocio confirmadas por el usuario (2026-07-06):
1. Visión **lee y extrae datos** (clasifica el documento + extrae campos clave) para
   llenar/validar facts automáticamente.
2. En conflicto declarado vs leído: **el documento gana**, se actualiza el fact, se marca
   la discrepancia para Capital Humano, y el bot avisa al candidato con tacto.
3. El apartado "Documentos" de la Nota IA rastrea el **expediente completo** (10
   documentos de `02_documentos_requisitos.md`).
4. Una sola propuesta v2 que absorbe #17.

## What Changes

- **Lector de documentos con visión**: al recibir una imagen (o PDF, ver abajo), visión
  (a) clasifica el tipo de documento — licencia federal, apto médico, INE, carta laboral,
  semanas IMSS, comprobante de pago de renovación, CURP, RFC, acta de nacimiento, NSS,
  comprobante de domicilio, comprobante de estudios, desconocido/ilegible — y (b) extrae
  sus **datos clave** (tipo de licencia, vigencias, nombre) para llenar/validar facts.
- **Registro de expediente por candidato** (persistencia nueva): por documento se guarda
  {tipo, estado declarado/recibido/analizado, datos extraídos mínimos, legible sí/no,
  timestamp, message_id de origen}. **La imagen NO se persiste** (minimización LFPDPPP).
  Duplicados: re-subir el mismo tipo actualiza el registro (última versión gana).
- **Apartado "📄 Documentos" en la Nota IA**, después de las preguntas principales del
  perfil: checklist del expediente completo con estado por documento —
  `☐ pendiente · declarado · recibido ✓ · analizado ✓ (dato leído)` — visible para el
  reclutador sin leer el chat.
- **Acuse específico por documento**: al subir uno, el bot agradece nombrándolo y dice
  qué falta ("Gracias por subir su INE ✓. Nos falta su licencia federal y su apto
  médico."). Documento ilegible → pide re-tomar la foto con tacto (sin culpar).
- **Conflicto declarado vs leído**: el dato leído del documento prevalece y actualiza el
  fact; la Nota IA marca la discrepancia (ej. "⚠️ Licencia: declaró vigente, el documento
  muestra vencida 03/2026") para revisión de Capital Humano; el bot informa al candidato
  con tacto y ofrece la alternativa vigente (comprobante de pago, política ya viva de #18).
- **Soporte PDF**: los adjuntos tipo documento dejan de rechazarse; se convierten a imagen
  (primera página) y entran al mismo lector. Si no es convertible → acuse pidiendo foto.
- **Capa de privacidad/consentimiento (absorbida de #17, sin cambios de fondo)**: aviso de
  confidencialidad al primer documento + consentimiento expreso registrado (timestamp +
  versión) antes de procesar el apto médico (dato sensible); no-persistencia de imágenes;
  política de retención con eliminación automatizada (fin de proceso / inactividad) y a
  solicitud (ARCO); validación por abogado mexicano ANTES de producción (LFPDPPP federal;
  las leyes de Coahuila aplican a entes públicos, no a Transmontes).
- **Trazabilidad y logs sin PII**: cada adjunto deja rastro auditable (metadata en
  `external_metadata` de `rh_lead_messages_v2` + registro de expediente), y los datos
  extraídos NUNCA se imprimen en logs en claro (hallazgo de seguridad §4).

## Capabilities

### New Capabilities
- `document-vision-reader`: clasificación + extracción de datos de documentos por visión;
  conflicto documento-gana con marca CH; ilegible → re-toma; PDF → imagen.
- `candidate-expediente-registry`: registro persistente del expediente (10 documentos,
  estados, datos mínimos, sin imágenes) con dedupe por tipo.
- `data-privacy-consent` (de #17): aviso + consentimiento expreso + retención/eliminación
  LFPDPPP + no-persistencia de imágenes.

### Modified Capabilities
- `chatwoot-ai-note`: nueva sección "📄 Documentos" (checklist expediente completo con
  estados y discrepancias), después de las secciones principales.
- `unified-turn-extraction` / `candidate-profile-extraction`: distingue DECLARAR (texto)
  vs ENVIAR (imagen); facts provenientes de documento con fuente `vision_document` y
  prioridad sobre lo declarado.
- `message-orchestration`: acuse por documento con "qué falta"; facts de perfil de un
  mensaje multi-fact no se pierden por ir a RAG (D2 de #17 — verificar si la extracción
  única ya lo resolvió; si no, corregirlo aquí).

## Impact

- **Código**: `app/app.py` (rama media: clasificar tipo, PDF→imagen), `app/indexer.py`
  (prompt de visión por tipo de documento), módulo nuevo `app/knowledge/document_reader.py`
  + `app/lead_memory/expediente.py` (registro), `app/chatwoot_note_sync.py` (sección
  Documentos + discrepancias), `app/orchestrators/knowledge_orchestrator.py` (acuse por
  documento, conflicto documento-gana), consentimiento en el flujo del worker.
- **Datos**: persistencia nueva de expediente (facts grupo `expediente.*` o tabla) SIN
  imágenes; registro de consentimiento; job de eliminación por retención.
- **Legal**: requiere aviso integral hospedado + validación por abogado (marco en design).
- **Riesgo**: medio-alto — datos sensibles + visión puede leer mal (fotos borrosas).
  Mitigaciones: documento-gana solo con lectura legible y confianza alta, discrepancias
  siempre visibles para CH, nunca decide elegibilidad final (eso es humano), imágenes no
  se almacenan, consentimiento previo.
