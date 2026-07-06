> Orden: primero specs (fuente de verdad), luego tests por grupo de causa, luego infra y
> housekeeping. Regla D1: los tests reescritos asertan DOMINIO, no copy literal. Cada
> bloque se verifica corriendo su subconjunto en contenedor antes de seguir.

## 1. Specs (sincronizar la fuente de verdad)

- [ ] 1.1 Aplicar delta `message-orchestration`: sustituir "Confirmación de datos sin
      duplicaciones" por "Acuse del funnel sin eco de datos" (+ cita de renovación en
      términos de dominio) — `openspec sync` o edición del spec principal según flujo.
- [ ] 1.2 Aplicar delta `chatwoot-label-taxonomy`: `insistencia` + `descartado_edad`
      (terminal) en el catálogo oficial del spec.

## 2. Tests — voz sin eco (drift intencional nuevo)

- [ ] 2.1 `test_current_turn_ack.py`: reescribir a propiedades (conector+pregunta, sin
      valor del dato, saludo con nombre primera vez, cierre ligero sin "siempre que sigas
      interesado").
- [ ] 2.2 `test_ack_fresh_and_renewal_proof.py`: fresh-facts ahora significa "no eco de
      nada"; renovación → copy de comprobante de pago en dominio (la parte de
      `documents.renewal_proof` si/no se conserva tal cual — sigue vigente).
- [ ] 2.3 `test_b2_unit_domain.py`, `test_first_contact_and_fact_guards.py`,
      `test_expiration_validation_and_ready_gating.py`, `test_call_scheduling.py`:
      actualizar asserts de ack/cierre a dominio.
- [ ] 2.4 `test_funnel_vigencia_edad.py`: orden del funnel y regla B→sencillo se conservan;
      renovación → comprobante de pago; descarte por edad → espera `["descartado_edad"]`.
- [ ] 2.5 Correr el subconjunto de los 7 archivos en contenedor → 0 FAILED.

## 3. Tests — labels

- [ ] 3.1 `test_candidate_labels.py`: catálogo esperado = actual (split full/sencillo, +
      `insistencia`, + `descartado_edad`); casos: pausa activa → `insistencia`; pausa
      expirada → sin `insistencia`; edad → `["descartado_edad"]`.
- [ ] 3.2 Correr el archivo en contenedor → 0 FAILED.

## 4. Tests — specs vigentes que los tests no siguieron (drift pre-existente)

- [ ] 4.1 `test_admin_release.py`: fail-closed (spec production-security-baseline): sin
      `INTERNAL_API_KEY` → 401; con key correcta → released. Eliminar la expectativa
      "sin key → abierto".
- [ ] 4.2 `test_chatwoot_note_renderer.py`: cabecera por escenario operativo (spec
      chatwoot-ai-note), no cabecera fija; revisar los 9 asserts contra el formato canónico
      del spec (secciones, orden, next-action única).
- [ ] 4.3 Correr ambos archivos en contenedor → 0 FAILED.

## 5. Infra del canary

- [ ] 5.1 Montar `./openspec:/app/openspec:ro` en el servicio api-test (docker-compose).
- [ ] 5.2 `test_core_consistency::test_live_specs_use_configured_age_limit` corre y pasa
      (57 en spec == `AGE_DISQUALIFICATION_LIMIT`).

## 6. Housekeeping de changes stale

- [ ] 6.1 Archivar `cumulative-ack-repetition-and-renewal-proof-not-detected` (su delta
      contradictorio muere con el archive; trabajo integrado y superado por
      empathetic-funnel).
- [ ] 6.2 Archivar `funnel-naturalness-and-persona-voice`, `qwen-disable-reasoning` y
      `groq-tpd-exhaustion-and-token-budget` (solo les falta verificación en vivo, cubierta
      de facto por las pruebas de esta sesión; anotarlo en el cierre).

## 7. Validación final

- [ ] 7.1 Suite completa en contenedor (`-m "not external_llm"`) → 0 FAILED.
- [ ] 7.2 `openspec validate realign-tests-and-specs-with-live-funnel` sin errores.
