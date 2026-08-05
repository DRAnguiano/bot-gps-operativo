## 1. Bug 1 — Ack solo de facts nuevos (D1)

- [x] 1.1 En `app/tasks_chatwoot.py`, antes de llamar `build_current_turn_ack`, computar el
      subconjunto "nuevo" del turno: `_fresh_facts = {k: v for k, v in _current_turn_facts.items()
      if saved_facts.get(k) != v}`. (saved_facts ya está calculado en el bloque del guard.)
- [x] 1.2 Pasar `pre_current_facts=_fresh_facts` a `build_current_turn_ack` (en vez de
      `_current_turn_facts`). Verificar que `merged_facts` sigue siendo `{**saved_facts,
      **_current_turn_facts}` para que la siguiente pregunta del funnel use el estado completo.
- [x] 1.3 Confirmar que `result["current_turn_facts"]` y la persistencia siguen usando
      `_current_turn_facts` completo (no `_fresh_facts`) — solo el ACK cambia.
- [x] 1.4 Revisar que `build_current_turn_ack` no asume que `pre_current_facts` contiene todos los
      facts del estado (la pregunta siguiente ya deriva de `facts = {**merged_facts, **current}`,
      que sigue completo). Documentar con un comentario breve la invariante "prefijo = solo nuevos".

## 2. Bug 2 — Persistir `documents.renewal_proof` (D2 + D3)

- [x] 2.1 En `app/knowledge/turn_extractor.py::validate_extraction`, tras el loop de
      `extraction.fields`, añadir bloque: si `extraction.signals.renewal_proof in {"si","no"}`,
      `out.append({"fact_group":"documents","fact_key":"renewal_proof","fact_value":<señal>,
      "confidence":0.8,"is_explicit_correction":is_correction})`.
- [x] 2.2 En `app/knowledge/current_turn.py`, definir `_TOPIC_RENEWAL_PROOF` (regex sobre
      "comprobante de renovacion" / "papel ... renovacion") análogo a `_TOPIC_APTO`.
- [x] 2.3 En `_extract_context_confirmation_facts`, cuando `is_yes` y la última pregunta del bot
      hace match con `_TOPIC_RENEWAL_PROOF`, fijar `facts["documents.renewal_proof"] = "si"`.
- [x] 2.4 En `_extract_context_confirmation_facts` (o en `extract_current_turn_facts` donde ya se
      maneja `_bare_neg`), cuando la negación corta coincide con el tópico de renovación, fijar
      `documents.renewal_proof = "no"`.
- [x] 2.5 Verificar en `app/tasks_chatwoot.py` que `documents.renewal_proof` está en `_PERSIST_KEYS`
      (ya lo está) y que fluye a `_current_turn_facts` vía `_ctx`. Ajustar si el merge lo bloquea.
- [x] 2.6 Confirmar que `_renewal_question_for_short_expiry` deja de re-preguntar cuando
      `documents.renewal_proof="si"` y aplica `funnel.status="vencido_sin_tramite"` cuando es "no".

## 3. Tests

- [x] 3.1 Test de ack solo-nuevos: dado `saved_facts` con ciudad/edad/vehículo y un turno que
      (por echo del extractor) reporta esos mismos + licencia nueva, el ack solo confirma la
      licencia y agrega la siguiente pregunta. (unit, sin red)
- [x] 3.2 Test de no-repetición: dos turnos consecutivos no acumulan confirmaciones de turnos
      previos en el prefijo.
- [x] 3.3 Test `validate_extraction`: extracción con `signals.renewal_proof="si"` produce un fact
      `documents.renewal_proof="si"`; con `null` no produce fact.
- [x] 3.4 Test de confirmación contextual: última pregunta = comprobante de renovación + "Si" →
      `documents.renewal_proof="si"`; + "no" → `documents.renewal_proof="no"`.
- [x] 3.5 Test de regresión del bucle: con licencia <3 meses y `documents.renewal_proof="si"`,
      `_next_funnel_question_or_none` NO devuelve la pregunta de renovación (avanza al siguiente
      campo).
- [x] 3.6 Correr la suite relacionada en contenedor worker (bind-mount de `app/` y `tests/`) y
      confirmar verde. 15/15 tests nuevos verde; los 3 fallos en test_current_turn_ack son
      preexistentes (copy "Perfecto"→"Anotado" y doble "años"), confirmados idénticos en baseline
      vía git stash — no son regresión de este change.

## 4. Deploy y verificación

- [x] 4.1 `docker compose build worker api`.
- [x] 4.2 `docker compose up -d worker api`. (worker `celery ready`, api Up)
- [ ] 4.3 Verificación en Chatwoot real: secuencia ciudad→edad→full→licencia E (vence 3 meses)→
      "Si" al comprobante. Confirmar (a) cada ack acusa SOLO el dato nuevo y (b) el bot NO
      re-pregunta el comprobante y avanza al siguiente campo del funnel.
- [ ] 4.4 Si la verificación es correcta, cerrar el change. Si hay regresión, revertir el commit.
