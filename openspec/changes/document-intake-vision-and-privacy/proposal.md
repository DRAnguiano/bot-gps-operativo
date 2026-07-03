## Why

Prueba en producción (2026-07-03, conv 157 / lead chatwoot:156) reveló bugs verificados en logs y un vacío de funcionalidad + un riesgo legal:

- **Etiqueta ambigua**: el label es `objetivo_full_sencillo` (combinado) — no distingue si el candidato busca **full** o **sencillo**. Debe haber `objetivo_full` y `objetivo_sencillo` separados; cualquiera de los dos puede completar el perfil (ambas unidades son vacantes válidas).
- **Extracción/ruteo del apto perdido**: el mensaje *"tengo apto médico vigente, vence en un año y dispongo de cartas laborales membretadas"* se **ruteó a RAG** (respuesta genérica) y el `medical.apto_expiration_text` + `documents.proof` **NO se persistieron** (`ROUTE1_SHADOW … reason=field_not_allowed`). Consecuencia: el funnel **re-preguntó** "¿Cuándo vence su apto médico?" y el candidato tuvo que **repetir** el dato. Un mensaje que enuncia varios facts de perfil no debe perderse por ir a RAG.
- **Falta el apartado de Documentos (con visión)**: ya existe modo visión (INE/stickers). Debe agregarse una sección **"Documentos"** en la Nota IA donde, **cada vez que el candidato ENVÍA la imagen** de un documento solicitado, se **palomee** (✓) ese documento. **NO confundir** que el candidato *diga* que tiene los documentos con que los *envíe*: son dos estados distintos (declarado vs recibido).
- **Riesgo legal/privacidad**: los documentos (INE, licencia, apto médico, cartas) son datos personales — el apto médico es **dato sensible (salud)**. Hoy no hay aviso de privacidad ni política de retención/eliminación, y almacenar las imágenes en BD es comprometedor.

Bonus verificado en logs: el híbrido **sigue topando TPD (429)** — turnos de 23–69s por reintentos. Probablemente `gpt-oss-120b` tiene TPD bajo. Se anota como riesgo operacional a resolver en paralelo.

## What Changes

- **Labels de unidad separados**: `objetivo_full` y `objetivo_sencillo` (se retira `objetivo_full_sencillo`). Cualquiera de los dos satisface el campo `experience.vehicle_type` para `perfil_listo`. Nota IA y taxonomía de labels se actualizan.
- **Fix de persistencia de facts en mensaje multi-fact**: un mensaje que enuncia facts de perfil (apto vigente, cartas, licencia) **persiste esos facts** aunque también dispare RAG; se elimina el `field_not_allowed` que descarta `medical.apto_expiration_text`/`documents.proof` en esa ruta. El funnel no re-pregunta lo ya respondido.
- **NUEVO apartado "Documentos" en la Nota IA** con dos estados por documento: **declarado** (el candidato dice que lo tiene) y **recibido** (envió la imagen, verificada por visión). Solo "recibido" se palomea ✓. Documentos rastreados: licencia federal, apto médico, y comprobante laboral (2 cartas membretadas **o** documento de semanas cotizadas del IMSS), más los demás que se soliciten en el funnel.
- **Extractor entiende el requisito documental**: distingue "declaro que tengo X" (fact `documents.proof`/estado) de "envío imagen de X" (evento de recepción por visión). El requisito es **2 cartas laborales membretadas O semanas cotizadas del IMSS** (según residencia), licencia y apto.
- **Capa de privacidad/consentimiento**: al **subir el primer documento**, el bot envía un **aviso de confidencialidad** (aviso de privacidad simplificado) — los datos se usan solo para integrar su expediente del proceso de contratación — y registra el consentimiento. **Las imágenes de documentos NO se almacenan en la BD**: visión extrae solo el resultado (documento recibido: sí/no + metadatos mínimos); la imagen no se persiste. Se define **política de retención y eliminación** (borrar/bloquear al concluir o si no se culmina el proceso), conforme a la **LFPDPPP** (federal, aplica a Transmontes como empresa privada; ver design para el marco legal y el matiz Coahuila).

## Capabilities

### New Capabilities
- `document-intake-tracking`: estados declarado/recibido por documento y su palomeo por visión en la Nota IA.
- `data-privacy-consent`: aviso de confidencialidad al primer documento, no-persistencia de imágenes, retención y eliminación conforme a LFPDPPP.

### Modified Capabilities
- `chatwoot-label-taxonomy`: `objetivo_full` / `objetivo_sencillo` separados (retira `objetivo_full_sencillo`).
- `chatwoot-ai-note`: nueva sección Documentos con checklist declarado/recibido.
- `unified-turn-extraction` / `candidate-profile-extraction`: distingue declarar vs enviar documento; persiste facts de perfil aunque el turno vaya a RAG.
- `message-orchestration`: un mensaje multi-fact no pierde los facts por ir a RAG.

## Impact

- **Código**: `app/chatwoot_note_sync.py` (labels + sección Documentos), `app/knowledge/turn_extractor.py` / `profile_extractor.py` (declarar vs enviar), `app/orchestrators/knowledge_orchestrator.py` + `app/tasks_chatwoot.py` (persistencia en ruta RAG), `app/indexer.py` (visión → verificación de documento), taxonomía de labels.
- **Datos**: NO se persisten imágenes de documentos; solo estado de recepción + metadatos. Nueva política de retención/eliminación.
- **Legal**: aviso de privacidad + registro de consentimiento + retención (LFPDPPP). **Requiere validación por abogado mexicano** — el design da el marco, no sustituye asesoría legal.
- **Riesgo**: medio-alto (toca extracción viva + datos personales sensibles). Mitigación: no almacenar imágenes, consentimiento explícito, eliminación automatizada, y validación legal previa a producción.
