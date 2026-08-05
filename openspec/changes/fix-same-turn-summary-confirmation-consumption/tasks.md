# Tasks — fix-same-turn-summary-confirmation-consumption

## 1. Merge mismo-turno en el nudge (D1 + D2)

- [x] 1.1 En `_build_funnel_nudge` (`knowledge_orchestrator.py`), tras construir
      `active_facts` (persistidos + pre_validated): computar
      `_extract_context_confirmation_facts(normalize_text(message), <último mensaje
      del bot completo desde lead_memory>, _turn_signals=turn_signals)` y mergear
      ÚNICAMENTE `funnel.summary_confirmed` si viene en el resultado, con try/except
      propio (fallo del detector → comportamiento actual).
- [x] 1.2 Verificar que con el merge, `next_question_from_missing_facts(active_facts)`
      devuelve el cierre y no el resumen (camino ya existente, sin lógica nueva).

## 2. Tests (D3)

- [x] 2.1 En `tests/test_compound_summary_confirmation.py`: caso de composición —
      `_build_funnel_nudge` con lead_memory cuyo último mensaje del bot contiene el
      resumen (builder real, datos arbitrarios) y mensaje "afirmación + pregunta" →
      el nudge devuelto NO contiene el encabezado del resumen (avanza al cierre).
- [x] 2.2 Contra-caso: mensaje de negación/corrección → el nudge conserva el
      comportamiento actual (no avanza al cierre por esta vía).
- [x] 2.3 Acotación del merge: solo `funnel.summary_confirmed` entra a `active_facts`
      desde el detector de contexto (otras claves inferidas no se cuelan).

## 3. Verificación y despliegue

- [x] 3.1 Suite completa en verde → 968 passed, 63 deselected (965 + 3 nuevos).
- [ ] 3.2 Commit + build + force-recreate + push; verificar el código nuevo en la
      imagen corriendo.
- [ ] 3.3 Verificación en vivo: llegar al resumen y responder "sí + pregunta de
      negocio" → la respuesta contesta la pregunta y pasa a documentos SIN repetir
      el resumen; en BD `funnel.summary_confirmed=true`.
