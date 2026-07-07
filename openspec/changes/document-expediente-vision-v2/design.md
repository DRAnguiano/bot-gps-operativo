## Context

Visión ya opera en vivo (`call_groq_vision`, modelo scout-17b) pero como flujo transitorio:
interpreta la imagen → texto → funnel, sin registro. No hay expediente, ni sección de
documentos en la Nota IA, ni PDFs, ni marco de privacidad. Esta v2 absorbe la propuesta
`document-intake-vision-and-privacy` (PR #17, se cierra a su favor) y la extiende con
lectura/extracción de datos según decisiones de negocio del 2026-07-06.

## Decisions

**D1 — Visión clasifica Y extrae (dos pasos en una llamada).** El prompt de visión para
adjuntos devuelve JSON: `{tipo_documento, legible, datos}` donde `datos` depende del tipo:
- licencia federal → {tipo (A/B/E), vigencia/vencimiento, nombre}
- apto médico → {vigencia/vencimiento} (dato sensible: solo vigencia, NO diagnósticos)
- INE → {nombre, vigencia} (NO CURP/clave de elector/dirección — minimización)
- carta laboral → {membretada sí/no, empresa}
- semanas IMSS → {presente sí/no}
- comprobante de pago de renovación → {documento al que aplica}
- otros del expediente (CURP, RFC, acta, NSS, comprobante domicilio, estudios) →
  {presente sí/no} (solo recepción; sin extraer contenido)
- desconocido/ilegible → estado para re-toma.
La validación es determinista post-LLM (catálogo de tipos, formatos de vigencia) — la
visión NUNCA persiste directo, pasa por `validate_extraction` como cualquier fuente.

**D2 — Registro de expediente: facts con grupo dedicado, no tabla nueva.** Se reusa
`rh_lead_facts_v2` con grupo `expediente` y llaves por documento:
`expediente.<tipo>.status` (`declarado|recibido|analizado|ilegible`),
`expediente.<tipo>.dato` (valor extraído mínimo, ej. vigencia),
`expediente.<tipo>.discrepancia` (si contradice lo declarado),
`expediente.<tipo>.received_at` (timestamp), más
`expediente.consent.status/timestamp/version` para el consentimiento.
Ventaja: cero migración de esquema, upsert único ya existente (dedupe por tipo gratis:
re-subir actualiza), la Nota IA ya lee facts. La metadata cruda del adjunto
(message_id, kind) va en `external_metadata` de `rh_lead_messages_v2` (columna existente)
para trazabilidad. *Alternativa descartada*: tabla `rh_expediente` — más limpia a largo
plazo pero requiere migración y nuevo repositorio; se reevalúa si el expediente crece.

**D3 — Documento gana + marca CH (decisión de negocio).** Si el dato leído (legible, con
confianza validada) contradice el fact declarado: se actualiza el fact con fuente
`vision_document` y confianza superior; se escribe `expediente.<tipo>.discrepancia` con
ambos valores; la Nota IA lo muestra con ⚠️; el bot avisa al candidato con tacto
reutilizando la política viva de #18 (ej. licencia vencida → ofrece comprobante de pago).
Guardrail: si `legible=false` o la validación determinista rechaza el valor, NO se
sobreescribe nada — solo se marca "recibido, ilegible" y se pide re-toma.

**D4 — Sección "📄 Documentos" en la Nota IA (expediente completo).** Después de las
secciones principales (Estado, Lo que ya sabemos, Falta confirmar):
```
📄 Documentos (expediente)
  Licencia federal:   analizado ✓ · tipo E, vence 03/2027
  Apto médico:        recibido ✓ · ilegible, se pidió re-toma
  INE:                analizado ✓
  Comprobante laboral (2 cartas o IMSS): declarado — falta enviar
  CURP · RFC · Acta · NSS · Comp. domicilio · Comp. estudios: pendientes
  ⚠️ Licencia: declaró "vigente", el documento muestra vencida 03/2026
```
Los 10 documentos del expediente (`02_documentos_requisitos.md`) siempre visibles;
compactar los pendientes en una línea para no inflar la nota. Declarado ≠ recibido
(regla de #17 intacta: solo enviar palomea).

**D5 — Acuse por documento.** Al procesar un adjunto el reply del turno es el acuse
específico: "Gracias por subir su <documento> ✓." + siguiente faltante del expediente (si
el funnel conversacional ya terminó) o retorno natural al funnel (si sigue activo). El
copy lo redacta el LLM (persona Mundo, variado) con los datos deterministas del registro
(qué llegó, qué falta) — mismo patrón voz-LLM/decisión-código del resto del sistema.

**D6 — PDF → imagen.** Adjuntos `file/document` PDF: se descarga, se rasteriza la primera
página (pypdfium2 o pdf2image) y entra al mismo lector. Falla de conversión → acuse
pidiendo foto del documento. Deja de usarse el rechazo enlatado del media guard para PDFs.

**D7 — Privacidad (absorbido de #17, íntegro).** Marco LFPDPPP federal (empresa privada;
reforma 2025: autoridad ahora Secretaría Anticorrupción y Buen Gobierno — verificar texto
vigente con abogado):
1. Aviso de confidencialidad simplificado al PRIMER documento + enlace al aviso integral.
2. Consentimiento EXPRESO (acción afirmativa) registrado (timestamp + versión) antes de
   procesar apto médico (dato sensible de salud).
3. Imágenes NUNCA se persisten; solo estado + datos mínimos del D1 (minimización).
4. Retención: bloqueo y eliminación al concluir el proceso / N días de inactividad /
   a solicitud (derechos ARCO). Job de purga automatizado sobre `expediente.*`.
5. Datos extraídos JAMÁS en logs en claro (hallazgo de auditoría de seguridad: los logs
   actuales ya imprimen PII — este change no lo empeora y el fix global va aparte).
6. Validación por abogado mexicano del aviso integral ANTES de producción.

**D8 — Prerequisito de fiabilidad.** El modelo de visión actual (scout-17b) se evalúa con
un set de fotos reales (licencias/INE/apto de prueba, borrosas y legibles) ANTES de
activar documento-gana; hasta pasar el eval, la extracción corre en modo shadow (registra
pero no sobreescribe facts) — mismo patrón shadow→gobierno usado en el resto del proyecto.

## Risks / Trade-offs

- **Visión lee mal** (borrosas, reflejos) → D8 shadow + solo sobreescribe con legible y
  validación determinista; discrepancias siempre a CH; humano decide elegibilidad.
- **Dato sensible (apto)** → consentimiento expreso previo; solo vigencia, nunca
  diagnóstico; eliminación automatizada.
- **INE con datos de más** → prompt minimizado (nombre+vigencia); nada más se extrae.
- **Costo LLM por imagen** → 1 llamada visión/adjunto (igual que hoy); rate limits ya
  cubiertos por el fallback multi-org.
- **Facts `expediente.*` inflan la tabla** → acotado: ≤ ~30 llaves por lead.

## Open Questions

1. ¿URL/hosting del aviso de privacidad integral y quién lo redacta? (bloqueante legal)
2. Plazo exacto de retención (¿al contratar? ¿90 días de inactividad?).
3. ¿Se conserva ALGÚN documento para el expediente laboral LFT post-contratación? Si sí,
   dónde (fuera de este sistema) y cómo se transfiere.
4. ¿El comprobante de pago de renovación (alternativa de #18) cuenta como "analizado"
   para palomar licencia/apto en el expediente, o queda como estado propio "en trámite"?
