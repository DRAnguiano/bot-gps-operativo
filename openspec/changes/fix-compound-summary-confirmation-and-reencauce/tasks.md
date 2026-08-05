# Tasks — fix-compound-summary-confirmation-and-reencauce

## 1. Confirmación del resumen en turno compuesto (D1)

- [x] 1.1 En `tasks_chatwoot.py`, tras evaluar `_guard_should_fire`: si NO dispara pero
      `_current_turn_facts.get("funnel.summary_confirmed") == "true"`, persistir SOLO ese
      fact vía `upsert_lead_fact` (`source="summary_confirm_compound"`), con log
      `[SUMMARY_CONFIRM_COMPOUND]`. Sin tocar el reply del turno.
      → Implementado entre el cálculo del gate y la rama del guard; gated también en
      `not requires_human`; try/except propio para nunca romper el turno.
- [x] 1.2 Tests: afirmación+pregunta persiste el fact; negación+pregunta NO lo persiste;
      turno sin resumen previo no dispara nada.
      → `tests/test_compound_summary_confirmation.py` — detección pura sobre
      `_extract_context_confirmation_facts` (el caso vivo "Si todo bien señor, me falto
      preguntarle hacen dopin?" confirma; negación/corrección no) + estructural del
      cableado en el worker (bloque antes de la rama del guard, gated en `== "true"`).

## 2. Re-encauce natural revivido (D2 + D3)

- [x] 2.1 En `knowledge_orchestrator.py` rama ROUTE1 no-confirmada: construir dict local
      de facts (persistidos de `lead_memory_before` + `_pre_validated`) y pasarlo a
      `_build_natural_reencauce` en lugar del inexistente `active_facts`.
      → `_reencauce_facts` construido en la rama (mismo merge que otros puntos del
      orquestador).
- [x] 2.2 Test de regresión estructural: `facts=active_facts` no aparece en la fuente de
      `handle_message` y `_reencauce_facts` sí (el assert es sobre el USO, no la mención
      en comentarios — primer intento falló porque el comentario explicativo contiene la
      palabra).
- [x] 2.3 Test funcional: la rama pasa los facts locales (`facts=_reencauce_facts`
      verificado en fuente); la lógica de `_build_natural_reencauce` ya tiene tests
      unitarios propios — lo que nunca estuvo probado era el cableado, ahora cubierto.

## 3. Voz única en transiciones (D4)

- [x] 3.1 Línea de voz añadida al prompt de `generate_funnel_transition_reply`
      (PRIMERA PERSONA DEL SINGULAR + usted; contraejemplos "indicarnos"/"necesitamos"
      citados en el prompt).
- [x] 3.2 Test: el prompt capturado por spy contiene la instrucción y el contraejemplo.

## 4. Verificación y despliegue

- [ ] 4.1 Suite completa en verde (`-m "not external_llm"`).
- [ ] 4.2 Commit + build + force-recreate (build ANTES de recreate) + push.
- [ ] 4.3 Verificación en vivo: reenviar el escenario compuesto (resumen → "sí + pregunta")
      y confirmar en BD `funnel.summary_confirmed` + respuesta a la pregunta en el mismo
      turno + ausencia de `[ROUTE1] omitido por error` en logs.
