> Orden: primero los fixes verificados en prod (labels, apto perdido) que son bajo
> riesgo; luego el apartado Documentos+visión; la capa de privacidad requiere
> validación legal ANTES de producción. Cada bloque con test.

## 1. Fix labels de unidad (D1) — bug verificado

- [ ] 1.1 Retirar `objetivo_full_sencillo`; emitir `objetivo_full` / `objetivo_sencillo` según `experience.vehicle_type` en `chatwoot_note_sync`.
- [ ] 1.2 Cualquiera de los dos satisface el campo de unidad para `perfil_listo`.
- [ ] 1.3 Migración: re-etiquetar leads con `objetivo_full_sencillo` al reproyectar.
- [ ] 1.4 Test: full→`objetivo_full`, sencillo→`objetivo_sencillo`, ambos completan unidad.

## 2. Fix persistencia multi-fact en ruta RAG (D2) — bug verificado

- [ ] 2.1 Persistir facts de perfil (con explicit_marker/answered_direct_question) ANTES/independiente de la decisión RAG vs profile; eliminar el `field_not_allowed` que descarta `medical.apto_expiration_text`/`documents.proof` en RAG.
- [ ] 2.2 Test de regresión conv 157: "tengo apto vigente vence en un año y cartas membretadas" → persiste apto+cartas, funnel NO re-pregunta.

## 3. Extractor: declarar vs enviar + requisito documental (D5)

- [ ] 3.1 Prompt del extractor: distinguir "tengo/cuento con X" (declarado) de adjunto de imagen (recepción); requisito explícito 2 cartas membretadas O semanas IMSS + licencia + apto.
- [ ] 3.2 Test: "sí tengo mis cartas" → declarado, NO recibido.

## 4. Apartado Documentos + visión (D3, D4)

- [ ] 4.1 Modelo de estado por documento: `document.<tipo>.declared` y `document.<tipo>.received` (+ metadatos: tipo, timestamp, legible).
- [ ] 4.2 Visión (`call_groq_vision`) clasifica el documento recibido y su legibilidad → set `received`; imagen NO se persiste.
- [ ] 4.3 Sección "Documentos" en la Nota IA con checklist declarado/recibido y palomeo ✓ solo en recibido.
- [ ] 4.4 Comprobante condicional por residencia (foráneo→cartas; local→cartas O IMSS).
- [ ] 4.5 Test: declarar no palomea; enviar imagen legible palomea; ilegible → "recibido, ilegible" para revisión.

## 5. Privacidad y consentimiento (D6) — REQUIERE validación legal antes de prod

- [ ] 5.1 Redactar aviso simplificado + **aviso integral** (hospedado); **validar con abogado mexicano** (LFPDPPP vigente post-reforma 2025; apto médico = dato sensible).
- [ ] 5.2 Enviar aviso al primer documento; consentimiento **expreso** antes de procesar el apto médico; registrar timestamp + versión.
- [ ] 5.3 No persistir imágenes (solo estado + metadatos) — verificar que ningún path guarde la imagen.
- [ ] 5.4 Retención: eliminación automatizada (fin de proceso / inactividad N días) + a solicitud (ARCO).
- [ ] 5.5 Mecanismo ARCO documentado en el aviso.
- [ ] 5.6 Definir open questions del design (URL aviso integral, plazo de retención, transferencias a la entidad contratante).

## 6. Operacional (paralelo, no bloquea)

- [ ] 6.1 Investigar 429/TPD del híbrido: TPD de `gpt-oss-120b`; considerar generación en otro modelo o más orgs. Los turnos de 23–69s por reintentos degradan UX.

## 7. Validación

- [ ] 7.1 `openspec validate document-intake-vision-and-privacy` sin errores.
- [ ] 7.2 Suite de regresión (labels, conv 157 apto, declarar-vs-enviar, palomeo) en verde.
- [ ] 7.3 Aviso legal validado por abogado ANTES de activar la capa de documentos en producción.
