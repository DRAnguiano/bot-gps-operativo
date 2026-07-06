> Orden: primero specs (fuente de verdad), luego tests por grupo de causa, luego infra y
> housekeeping. Regla D1: los tests reescritos asertan DOMINIO, no copy literal. Cada
> bloque se verifica corriendo su subconjunto en contenedor antes de seguir.

## 1. Specs (sincronizar la fuente de verdad)

- [x] 1.1 Aplicar delta `message-orchestration`: sustituir "Confirmación de datos sin
      duplicaciones" por "Acuse del funnel sin eco de datos" (+ cita de renovación en
      términos de dominio) — `openspec sync` o edición del spec principal según flujo.
- [x] 1.2 Aplicar delta `chatwoot-label-taxonomy`: `insistencia` + `descartado_edad`
      (terminal) en el catálogo oficial del spec. Además se corrigió `objetivo_full_sencillo`
      → `objetivo_full`/`objetivo_sencillo` (split ya vivo en código, spec estaba stale) en
      catálogo, tabla de semántica, exclusividad mutua y tricotomía determinista.

## 2. Tests — voz sin eco (drift intencional nuevo)

- [x] 2.1 `test_current_turn_ack.py`: reescrito a propiedades (conector+pregunta, sin
      valor del dato, saludo con nombre primera vez, cierre ligero sin "siempre que sigas
      interesado"). 13 passed.
- [x] 2.2 `test_ack_fresh_and_renewal_proof.py`: fresh-facts ahora significa "no eco de
      nada"; `_RENEWAL_Q` fixture actualizado al copy vigente de comprobante de pago.
      15 passed.
- [x] 2.3 `test_b2_unit_domain.py` (29 passed), `test_first_contact_and_fact_guards.py`
      (además se hicieron deterministas 3 tests de `TestAniosElipticos` que dependían de
      una llamada LLM sin mockear — turn_signals inyectado explícito),
      `test_expiration_validation_and_ready_gating.py` (31 passed),
      `test_call_scheduling.py` (fixture `_PERFIL_LISTO_FACTS` incompleto —le faltaban
      name/age/expiration_text, pre-existente; copy "no interpretable"→"por confirmar").
- [x] 2.4 `test_funnel_vigencia_edad.py` (35 passed): causa raíz pre-existente — el funnel
      pide `candidate.name` ANTES que ciudad y casi ningún fixture del archivo lo incluía;
      además edad=52 estaba bajo el límite real (57) y "no tengo cartas" ahora persiste
      "ninguno" (Bloque 2, D3) en vez de no persistir nada.
- [x] 2.5 Los 7 archivos verificados individualmente en contenedor → 0 FAILED cada uno.

## 3. Tests — labels

- [x] 3.1 `test_candidate_labels.py`: catálogo corregido a 27 (no 26 — error de conteo
      propio corregido también en el spec); `TRICHOTOMY` con `objetivo_full`/
      `objetivo_sencillo`; fixture de sufijo de estado corregido a alias reales del
      catálogo (el caso con coma "Gómez Palacio, Durango" no es alias real).
      **Bug de producción encontrado y corregido**: `calculate_candidate_labels` comparaba
      la ciudad cruda contra el set canónico sin resolver alias primero (a diferencia de
      `residency_is_local`) — candidatos que escriben "Torreón Coahuila"/"Cd. Lerdo" se
      etiquetaban `foraneo` por error. Fix: `normalize_zm_laguna_city` antes de
      `is_zm_laguna_canonical` en `chatwoot_note_sync.py` (2 sitios).
- [x] 3.2 105 passed.

## 4. Tests — specs vigentes que los tests no siguieron (drift pre-existente)

- [x] 4.1 `test_admin_release.py`: 2 tests reescritos a fail-closed real (key configurada +
      header correcto); +1 test nuevo cubriendo explícitamente "key vacía → 401 siempre,
      incluso con header". 4 passed.
- [x] 4.2 `test_chatwoot_note_renderer.py`: el archivo entero probaba un contrato
      DEPRECADO (`chatwoot-ai-note-contract`, superseded por `chatwoot-ai-note`) — secciones
      "📋 Perfil confirmado"/"📍 Embudo" y `lead.next_best_action` ya no existen en el
      renderer vivo. Reescritos los 9 asserts a las secciones vigentes (Estado del
      candidato, Lo que ya sabemos, Falta confirmar, cabecera por escenario, next-action
      determinista). Docstring del archivo actualizado.
- [x] 4.3 35 passed (note_renderer) + 4 passed (admin_release).

## 5. Infra del canary

- [x] 5.1 Montado `./openspec:/app/openspec:ro` en el servicio api-test (docker-compose).
- [x] 5.2 `test_core_consistency.py` corre y pasa (6 passed) — 57 en spec ==
      `AGE_DISQUALIFICATION_LIMIT`.

## 6. Housekeeping de changes stale

- [x] 6.1 Archivado `cumulative-ack-repetition-and-renewal-proof-not-detected` SIN
      sincronizar su delta (contradictorio, superseded por empathetic-funnel).
- [x] 6.2 Sincronizados y archivados `funnel-naturalness-and-persona-voice`,
      `qwen-disable-reasoning`, `groq-tpd-exhaustion-and-token-budget`. Cada requirement
      se verificó contra código antes de sincronizar (no se sincronizó a ciegas):
      `GROQ_LLM_HISTORY_TURNS` resultó NO implementado (env var muerto) — se sincronizó
      corregido reflejando el mecanismo real (`messages[-4:]` fijo). Bug de parseo
      pre-existente encontrado en el proceso: header rogue "## Requirements added in
      funnel-objection-handling-and-ready-gating" ocultaba requirements de
      `validate`/`list`/`archive` en 2 specs — corregido. `openspec validate --specs`:
      22/22 (antes 20/22).

## 7. Validación final

- [x] 7.1 Suite completa en contenedor (`-m "not external_llm"`) → **932 passed, 0 failed**
      (1 deselected, 24 warnings, 1762.97s). Encontró y resolvió 26 fallas adicionales
      más allá de las 40 iniciales (ver commit `6b32e06`), todas pre-existentes.
- [x] 7.2 `openspec validate realign-tests-and-specs-with-live-funnel` sin errores.
