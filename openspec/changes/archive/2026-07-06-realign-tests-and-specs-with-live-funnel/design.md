## Context

Suite completa 2026-07-06: 40 FAILED / 11 archivos. Causa raíz común: iteraciones
prod-first (voz del funnel, labels, seguridad, nota) sin actualizar contratos ni tests en
el mismo commit. Dos requirements del spec principal contradicen el código vivo.

## Decisions

**D1 — Los tests asertan dominio, no copy literal.** Regla ya acordada (memoria
`feedback_contract_phrasing`): el mensaje concreto es un ejemplo, no el contrato. Los tests
reescritos verifican propiedades: "el reply NO contiene el valor del dato recién dado",
"termina con la siguiente pregunta del funnel", "ofrece la alternativa de comprobante de
pago cuando el documento está vencido" — sin fijar la frase exacta (que además ahora varía
por diseño: conector aleatorio, generación LLM).
*Alternativa descartada*: actualizar los strings literales uno a uno — se rompe en la
siguiente iteración de copy, que es exactamente lo que pasó.

**D2 — El spec manda el comportamiento nuevo; el viejo requirement se REEMPLAZA, no se
acumula.** "Confirmación de datos sin duplicaciones" nació para el bug de duplicación
("20 años, 20 años"); su solución vigente es más fuerte: no hay eco alguno. El requirement
nuevo ("Acuse del funnel sin eco de datos") subsume el anti-duplicación y documenta la
excepción única (saludo con nombre de pila la primera vez, `name_just_learned`).

**D3 — El delta contradictorio muere con el archive del change stale.** El delta de
`cumulative-ack-...` no se edita: ese change se archiva (su trabajo está integrado y
superado). Archivar los 4 changes stale evita que `openspec list` sugiera trabajo ya hecho.

**D4 — Canary de consistencia habilitado por montaje, no por copia.** `openspec/` se monta
read-only en api-test (igual que `./app`). Copiarlo a la imagen lo congelaría por build.
El canary (`test_live_specs_use_configured_age_limit`) es valioso: es el único test que
detecta divergencia spec↔config automáticamente.

**D5 — Fallas que NO se tocan.** El matcher de renovación (`_TOPIC_RENEWAL_PROOF`) ya
funciona con el copy nuevo (verificado por regex sobre la pregunta viva); el cierre de
perfil cumple su requirement (paso siguiente + variantes por horario). No se cambia código
de producción en este change.

## Clasificación de las 40 fallas (evidencia)

| Grupo | Archivos | Causa | Acción |
|---|---|---|---|
| Voz sin eco (nuevo, intencional) | test_current_turn_ack (5), test_ack_fresh… (2), test_b2_unit_domain (2), test_first_contact… (3), test_expiration… (1), test_funnel_vigencia_edad (~6), test_call_scheduling (2) | eco/cierre/copy retirados por feedback 2026-07-03 | reescribir asserts a dominio (D1) |
| Labels (intencional) | test_candidate_labels (5), test_funnel_vigencia_edad (parcial) | split full/sencillo + `insistencia` + `descartado_edad` | actualizar catálogo esperado; edad → `["descartado_edad"]` |
| Tests vs specs vigentes (pre-existente) | test_admin_release (2), test_chatwoot_note_renderer (9) | specs ya mandan fail-closed 401 y cabecera por escenario; tests fijan lo anterior | reescribir asserts al spec vigente |
| Infra | test_core_consistency (1) | api-test no monta `openspec/` | montar volumen ro |

## Risks / Trade-offs

- **Asserts de dominio demasiado laxos** → un bug real podría pasar. Mitigación: cada test
  conserva al menos una propiedad negativa fuerte (p. ej. "no re-confirma el dato", "no
  contiene 'caduca'", "no promete agenda").
- **Archivar changes con 1-2 tareas de verificación en vivo abiertas** → se pierde el
  recordatorio. Mitigación: la verificación en vivo quedó cubierta de facto por las pruebas
  de esta sesión (documentadas en los tasks de `empathetic-funnel`); se anota en el archive.
