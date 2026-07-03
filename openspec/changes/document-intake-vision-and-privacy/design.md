## Context

El funnel recolecta facts de perfil (licencia, apto, unidad, experiencia, ciudad, comprobante). Al completar, pide **subir documentos**. Hoy: (a) la unidad se etiqueta con un label combinado ambiguo; (b) un mensaje multi-fact puede irse a RAG y perder los facts; (c) no hay seguimiento de qué documentos se **recibieron** (vía imagen) vs se **declararon**; (d) no hay capa de privacidad para datos personales/sensibles. Ver evidencia en `proposal.md` (conv 157, 2026-07-03).

## Decisions

**D1 — Labels de unidad separados.** Retirar `objetivo_full_sencillo`; usar `objetivo_full` **y** `objetivo_sencillo`. Se asigna según `experience.vehicle_type`. Cualquiera de los dos satisface el campo para `perfil_listo` (ambas unidades son vacantes válidas). `chatwoot_note_sync` (labels) y la taxonomía se actualizan; migración: leads con `objetivo_full_sencillo` se re-etiquetan al reproyectar según su fact.

**D2 — Persistir facts de perfil aunque el turno vaya a RAG.** Causa raíz (logs): `ROUTE1_SHADOW … medical.apto_expiration_text … reason=field_not_allowed` — un mensaje que enuncia apto/cartas se ruteó a RAG y sus facts no se persistieron. Decisión: la extracción y persistencia de facts de perfil ocurre **antes/independiente** de la decisión de ruta (RAG vs profile); un mensaje compuesto "dato(s) + (implícito) info" persiste los datos y, si además hay pregunta, la responde. Se elimina el `field_not_allowed` que descarta esos campos en la ruta RAG. Test de regresión: el caso exacto de conv 157 (apto+cartas → no re-preguntar).

**D3 — Sección "Documentos" en la Nota IA con estados declarado/recibido.** Por cada documento requerido, dos estados independientes:
- **declarado**: el candidato DIJO que lo tiene (`documents.proof`, o "tengo mi licencia"). NO se palomea como recibido.
- **recibido ✓**: el candidato ENVIÓ la imagen y visión la verificó. Solo esto palomea ✓.

Checklist de documentos: `licencia_federal`, `apto_medico`, y **comprobante laboral** = (`cartas_laborales` [2 membretadas] **O** `semanas_imss`) según residencia (foráneo→cartas, local La Laguna→cualquiera). La nota muestra p. ej.:
```
📄 Documentos
  Licencia federal:  declarado ✓ | recibido ☐
  Apto médico:       declarado ✓ | recibido ☐
  Comprobante (2 cartas/IMSS): declarado ☐ | recibido ☐
```

**D4 — Visión verifica recepción, NO se almacena la imagen.** Cuando llega una imagen en el estado de documentos, visión (`call_groq_vision`) clasifica QUÉ documento es y si es legible → marca `document.<tipo>.received=true` + metadatos mínimos (tipo, timestamp, legible sí/no). **La imagen NO se persiste en la BD** (ver D6/privacidad). No se hace OCR de contenido sensible más allá de identificar el tipo de documento y su recepción; la validación de vigencia/datos la hace el equipo humano.

**D5 — El extractor distingue DECLARAR vs ENVIAR.** En texto: "tengo/cuento con licencia/cartas" → declarado. Un adjunto de imagen → evento de recepción (visión), no texto. El requisito documental queda explícito en el prompt: **2 cartas laborales membretadas O documento de semanas cotizadas del IMSS**, además de licencia y apto. Decir que se tienen ≠ haberlos enviado; la nota refleja ambos estados por separado.

**D6 — Privacidad y consentimiento (marco legal abajo).** Al **primer documento** que el candidato sube:
1. El bot envía un **aviso de confidencialidad** (aviso de privacidad simplificado): "Sus datos y documentos se usan únicamente para integrar su expediente del proceso de contratación en Transmontes. Puede solicitar acceso, corrección o eliminación en cualquier momento. [aviso completo]".
2. Se registra el **consentimiento** (timestamp + versión del aviso) — para el apto médico (dato sensible de salud) el consentimiento debe ser **expreso** (acción afirmativa clara).
3. **No se almacenan las imágenes** en la BD (solo estado recibido + metadatos). Minimización de datos.
4. **Retención/eliminación**: los datos se conservan solo mientras dure el proceso; se **bloquean y eliminan** al concluir la contratación (o al no culminar / tras N días de inactividad). Proceso de eliminación automatizado + a solicitud (derecho de cancelación).

**D7 — (Operacional, fuera de esta capa) 429/TPD.** Los logs muestran 429 recurrentes (turnos 23–69s). `gpt-oss-120b` probablemente tiene TPD bajo. Anotar para resolver en paralelo (revisar TPD de gpt-oss, o generación en otro modelo, o más orgs). No es parte de esta propuesta pero condiciona la UX.

## Marco legal (México) — investigación, NO sustituye asesoría de abogado

**Ley aplicable — matiz importante (corrige la premisa "leyes de Coahuila"):**
- Transmontes es **empresa privada** → aplica la **LFPDPPP** (Ley Federal de Protección de Datos Personales en Posesión de los Particulares) y su Reglamento — es **FEDERAL** y rige en todo el país, incluido Torreón, Coahuila.
- Las **leyes estatales de protección de datos de Coahuila** rigen a **entes públicos/sujetos obligados** (transparencia), **no** a empresas privadas. Por eso NO hay un régimen "de Coahuila" distinto para Transmontes; el marco es federal.
- Relevante también: **Ley Federal del Trabajo** (expediente del trabajador) y NOMs aplicables.
- ⚠️ **Reforma 2025**: en 2025 México reformó el marco (desaparición del INAI; la autoridad pasó a la Secretaría Anticorrupción y Buen Gobierno) y se publicó una nueva LFPDPPP. Los principios se mantienen, pero **la autoridad y algunos procedimientos cambiaron** — **verificar el texto vigente con un abogado**.

**Obligaciones clave para el diseño:**
- **Aviso de privacidad** al momento de recabar datos. Válido usar un **aviso simplificado/corto** en el chat (con enlace al **aviso integral**). Debe identificar: responsable (Transmontes), finalidad (integrar expediente para proceso de contratación), y medios para ejercer **derechos ARCO** (Acceso, Rectificación, Cancelación, Oposición) + revocación del consentimiento.
- **Datos sensibles**: el **apto médico** son datos de **salud** = sensibles → **consentimiento expreso** (acción afirmativa) y salvaguardas reforzadas; minimizar su tratamiento.
- **Principios**: licitud, consentimiento, información, calidad, **finalidad** (solo para el proceso), **proporcionalidad/minimización** (no almacenar la imagen si basta el estado de recepción), **responsabilidad**.
- **Retención y supresión**: conservar solo lo necesario para la finalidad; luego **bloqueo** y **supresión**. Definir plazo (p. ej. borrar al contratar o a los X días de abandono).
- **Transferencias**: si los datos se comparten con la entidad contratante u otros, declararlo en el aviso.

**Recomendaciones concretas al sistema (implementan lo anterior):**
1. Aviso corto al primer documento + enlace al aviso integral (hospedado por Transmontes/legal).
2. Consentimiento **expreso** ("acepto") antes de procesar el apto médico (sensible); registrar timestamp + versión del aviso.
3. **No almacenar imágenes**: visión extrae solo tipo + recepción; la imagen se descarta tras procesar.
4. Retención con **eliminación automatizada** (fin de proceso / inactividad) + a solicitud (ARCO).
5. Mecanismo ARCO visible (cómo pedir acceso/eliminación) en el aviso.
6. **Validación por abogado mexicano** del aviso integral y de la clasificación de datos sensibles ANTES de producción.

## Risks / Trade-offs

- **Cumplimiento legal**: alto — datos sensibles de salud. Mitigación: no almacenar imágenes, consentimiento expreso, eliminación, validación legal.
- **Visión clasificando documentos**: puede confundir tipo/legibilidad → marca "recibido, ilegible" para revisión humana; nunca decide elegibilidad.
- **Migración de labels**: `objetivo_full_sencillo` existente → re-etiquetar al reproyectar.
- **D2 (persistir en RAG)**: riesgo de persistir facts falsos si el enunciado es negativo/ajeno — reusar los guards existentes (explicit_marker / answered_direct_question) para no sobre-persistir.

## Open Questions

- ¿Dónde se hospeda el **aviso integral** (URL) y quién lo redacta/valida legalmente?
- Plazo exacto de retención antes de eliminar (¿al contratar? ¿X días de inactividad?).
- ¿La entidad contratante es un tercero al que se transfieren datos (declarar en aviso)?
- ¿Se requiere conservar ALGÚN documento para el expediente laboral (LFT) más allá del proceso? Si sí, cifrado + acceso restringido + en el aviso.
