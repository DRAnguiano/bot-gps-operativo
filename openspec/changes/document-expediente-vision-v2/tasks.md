> Orden: registro + palomeo primero (bajo riesgo, valor inmediato en la Nota IA), luego
> lectura/extracción en SHADOW, luego gobierno (documento-gana) tras pasar el eval, y la
> capa legal en paralelo desde el inicio. Cada bloque con tests en el mismo PR (lección de
> la auditoría 2026-07-06: módulos nuevos sin tests generan drift).

## 1. Registro de expediente + palomeo (sin extracción aún)

- [ ] 1.1 Módulo `expediente` (facts grupo `expediente.*`): estados por documento,
      helpers read/write, dedupe por tipo (última versión gana). Tests unitarios.
- [ ] 1.2 Clasificador de tipo de documento en visión (prompt JSON: tipo + legible),
      validación determinista del catálogo de 12 tipos. Tests con fixtures.
- [ ] 1.3 Rama media de `app.py`: al procesar imagen, registrar
      `expediente.<tipo>.status=recibido` + metadata del adjunto en `external_metadata`.
- [ ] 1.4 Extractor de texto: "tengo mi <doc>" → `expediente.<tipo>.status=declarado`
      (declarar ≠ enviar). Tests.
- [ ] 1.5 Sección "📄 Documentos" en la Nota IA (checklist 10 docs, estados, pendientes
      compactados). Tests del renderer.
- [ ] 1.6 Acuse por documento con faltantes (copy LLM variado sobre datos deterministas).
      Tests + verificación en vivo.

## 2. Privacidad y consentimiento (paralelo, bloqueante para producción)

- [ ] 2.1 Aviso simplificado al primer documento + registro `expediente.consent`
      (timestamp + versión). Tests.
- [ ] 2.2 Gate de consentimiento expreso antes de procesar apto médico. Tests.
- [ ] 2.3 Confirmar no-persistencia de imágenes (la imagen se descarta post-visión) y que
      los datos extraídos no van a logs en claro. Test + revisión de logs.
- [ ] 2.4 Job de purga por retención (fin de proceso / N días inactividad) + mecanismo de
      eliminación a solicitud (ARCO). Tests.
- [ ] 2.5 Resolver open questions legales (URL del aviso integral, plazo de retención,
      conservación LFT post-contratación) con el usuario/abogado. **Validación por
      abogado mexicano ANTES de producción.**

## 3. Lectura/extracción de datos (SHADOW)

- [ ] 3.1 Prompts de extracción por tipo (licencia: tipo+vencimiento; apto: SOLO
      vigencia; INE: nombre+vigencia; cartas: membretada; resto: solo recepción).
- [ ] 3.2 Validación determinista de valores extraídos (catálogos, formatos de fecha) vía
      `validate_extraction`. Tests.
- [ ] 3.3 Modo shadow: registrar lectura + discrepancias en expediente/Nota IA SIN
      sobreescribir facts declarados. Log `[EXPEDIENTE_SHADOW]`.
- [ ] 3.4 Eval de visión con set de fotos reales (legibles + borrosas + documento
      equivocado); criterio de aprobación acordado con el usuario.

## 4. Gobierno: documento-gana (tras aprobar 3.4)

- [ ] 4.1 Facts con fuente `vision_document` prevalecen sobre declarados (solo legible +
      validado); discrepancia registrada y visible con ⚠️ en la Nota IA.
- [ ] 4.2 Aviso al candidato con tacto en conflicto + alternativa aplicable (comprobante
      de pago para licencia/apto vencidos — política de #18). Tests.
- [ ] 4.3 Verificar D2 de #17: ¿los facts de un mensaje multi-fact aún se pierden al ir a
      RAG? Si sí, corregir; si la extracción única ya lo resolvió, documentar y cerrar.

## 5. PDF

- [ ] 5.1 Conversión PDF→imagen (primera página) en la rama media; fallo → acuse pidiendo
      foto. Dependencia nueva (pypdfium2 o pdf2image) en requirements + imagen Docker.
- [ ] 5.2 Tests del flujo PDF (convertible y no convertible).

## 6. Cierre

- [ ] 6.1 Cerrar PR #17 a favor de esta v2 (comentario con referencia).
- [ ] 6.2 Archivar `image-sticker-vision-profiling` (completo desde antes, sin archivar —
      hallazgo de auditoría).
- [ ] 6.3 Suite completa en verde + verificación en vivo del flujo: subir licencia foto,
      licencia PDF, doc ilegible, discrepancia declarado-vs-leído.
- [ ] 6.4 `openspec validate document-expediente-vision-v2` sin errores.
