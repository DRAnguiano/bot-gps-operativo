## Why

Auditoría 2026-07-06 (suite completa en contenedor, 40 FAILED en 11 archivos): los
contratos OpenSpec y los tests quedaron **rezagados del comportamiento vivo** tras varias
iteraciones prod-first. Hay dos requirements del spec principal que hoy **contradicen** el
código desplegado, y ~40 tests que fijan comportamiento ya retirado a propósito. Mientras
esto no se corrija, la suite no sirve como red de regresión (todo rojo = nada señal) y el
spec miente como fuente de verdad.

Clasificación de las 40 fallas (evidencia por ejecución + lectura de asserts):

1. **Drift intencional NUEVO** (feedback de voz 2026-07-03, cambio `empathetic-funnel`):
   el funnel ya NO hace eco de datos ("licencia tipo E vigente, anotado") — conector
   variado + siguiente pregunta; cierre ligero; copy de renovación = "comprobante de pago".
   Tests que fijan el eco viejo: `test_current_turn_ack` (5), `test_ack_fresh_and_renewal_proof`
   (2), `test_b2_unit_domain` (2), `test_first_contact_and_fact_guards` (3),
   `test_expiration_validation_and_ready_gating` (1), `test_funnel_vigencia_edad` (parcial de 8),
   `test_call_scheduling` (2, cierre viejo).
2. **Drift intencional de labels**: split `objetivo_full_sencillo`→`objetivo_full`/`objetivo_sencillo`
   (sesión anterior) + nuevos `insistencia`/`descartado_edad` (B5) — `test_candidate_labels` (5)
   asserta el catálogo viejo y el descarte por edad sin label.
3. **Drift PRE-EXISTENTE de tests vs specs que YA mandan lo vivo**: `test_admin_release` (2)
   espera "sin key → abierto" pero `production-security-baseline` manda fail-closed 401 (el
   código cumple el spec; el test no); `test_chatwoot_note_renderer` (9) asserta cabecera fija
   "Seguimiento de candidato" pero `chatwoot-ai-note` manda cabecera por escenario.
4. **Infra de tests**: `test_core_consistency::test_live_specs_use_configured_age_limit` falla
   con FileNotFoundError — el contenedor api-test NO monta `openspec/`; el canary de
   consistencia spec↔config no puede correr.

Además, dos incongruencias spec↔código directas:
- `openspec/specs/message-orchestration` "Confirmación de datos sin duplicaciones"
  (líneas ~133-161) exige que el ack **confirme el fact fresco** — contradice el código vivo
  (sin eco). Su gemelo vive en el delta del change `cumulative-ack-...` (stale).
- El requirement "Confirmación contextual corta" cita el copy viejo de renovación
  ("¿Ya tiene el papel o comprobante de renovación?"); el vivo es "comprobante de pago de su
  renovación o trámite" (verificado: el matcher determinista SÍ sigue funcionando).

## What Changes

- **Spec `message-orchestration`**: reemplazar el requirement de confirmación-con-eco por
  "Acuse del funnel sin eco de datos" (conector breve variado + siguiente pregunta; el saludo
  con nombre de pila la primera vez es la única confirmación con dato; cierre ligero sin
  recordatorio redundante). Actualizar la cita del copy de renovación en términos de dominio
  (no literal).
- **Spec `chatwoot-label-taxonomy`**: añadir `insistencia` (pausa por ruego activa) y
  `descartado_edad` (terminal; el descarte por edad SHALL emitir label, antes cerraba sin
  rastro) al catálogo oficial.
- **Tests**: reescribir los 11 archivos con fallas para asertar el contrato vigente en
  términos de dominio (no copy literal — regla de redacción de contratos), cubriendo:
  sin-eco, conector+pregunta, cierre ligero, comprobante de pago, labels nuevos, fail-closed
  admin, cabecera de nota por escenario.
- **Infra**: montar `openspec/` (read-only) en el servicio api-test para que el canary de
  consistencia corra; o marcar el test con skip-si-no-existe.
- **Housekeeping**: archivar los 4 changes stale casi-completos (`funnel-naturalness…` 12/13,
  `qwen-disable-reasoning` 8/9, `groq-tpd…` 18/20, `cumulative-ack…` 18/20) cuyo único
  pendiente es verificación en vivo ya realizada de facto, dejando nota de cierre; el delta
  contradictorio de `cumulative-ack` muere con su archivo.

## Capabilities

### Modified Capabilities
- `message-orchestration`: acuse sin eco de datos (sustituye confirmación-con-eco).
- `chatwoot-label-taxonomy`: catálogo +2 labels (`insistencia`, `descartado_edad` terminal).

## Impact

- **Tests**: 11 archivos reescritos/ajustados; la suite vuelve a ser señal (0 rojos esperados
  fuera de `external_llm`).
- **Specs**: 2 archivos principales editados vía delta; 1 change stale archivado con su delta
  contradictorio.
- **Infra**: docker-compose (montaje `openspec/` en api-test).
- **Riesgo**: bajo — no toca código de producción; solo contratos, tests e infra de test.
  El riesgo real es el inverso: NO hacerlo deja la suite inservible como red de regresión.
