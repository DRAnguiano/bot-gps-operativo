## Context

El path activo de un turno entrante en Chatwoot es:

```
tasks_chatwoot.process_debounced_message
  → extract_turn(combined_content, last_bot, known_facts)   # unified turn extractor (8b)
  → validate_extraction(...) → _pre_validated
  → _current_turn_facts = {fields validados} + _extract_context_confirmation_facts(...)
  → build_current_turn_ack(msg, merged_facts, last_bot, pre_current_facts=_current_turn_facts)
  → persist (solo keys nuevas en _PERSIST_KEYS)
```

Dos defectos observados en producción (conv 139):

- **Bug 1 (ack acumulativo)**: `build_current_turn_ack` (current_turn.py ~667-721) arma los
  `confirms` desde `current = pre_current_facts` sin restar los facts ya conocidos. El extractor
  8b re-emite los "DATOS YA CONOCIDOS" del prompt como fields del turno, así que `_current_turn_facts`
  acarrea ciudad/edad/vehículo de turnos previos y el ack los re-confirma cada vez.
- **Bug 2 (renovación no detectada)**: `validate_extraction` (turn_extractor.py ~235+) solo itera
  `extraction.fields`; la señal `signals.renewal_proof` se pierde. Y
  `_extract_context_confirmation_facts` (current_turn.py 331-338) mapea "Si" a apto/licencia/cartas
  pero no a `documents.renewal_proof`. El consumidor `_renewal_question_for_short_expiry`
  (current_turn.py 201-215) ya lee `documents.renewal_proof`, pero nadie lo setea → bucle.

Constraint del proyecto: las preguntas del funnel las emite el sistema (no el LLM); la prioridad
de verdad es turno actual > lead_memory > Neo4j > RAG > LLM; los fixes deben ser deterministas.

## Goals / Non-Goals

**Goals:**
- El ack confirma solo facts genuinamente nuevos del turno, robusto ante el parroteo del extractor.
- La señal `renewal_proof` (por extractor o por confirmación contextual) se persiste como
  `documents.renewal_proof` y rompe el bucle del funnel.
- Cobertura con tests unitarios deterministas (sin red).

**Non-Goals:**
- No se revierte el extractor a 70b (el change de presupuesto TPD se mantiene).
- No se rediseña el pipeline de extracción ni el funnel.
- No se toca la lógica de cierre suave `vencido_sin_tramite` (ya existe).

## Decisions

### D1 — Filtrar el ack a facts nuevos dentro de `build_current_turn_ack`
`build_current_turn_ack` recibe `merged_facts` (saved + current) y `pre_current_facts` (current).
Decisión: calcular los facts realmente nuevos como `current` cuyos valores difieren de lo ya
guardado, y construir los `confirms` solo sobre ese subconjunto.

Implementación: pasar los `saved_facts` al ack (o el subconjunto "nuevo" precomputado en
tasks_chatwoot) y filtrar cada `current.get(key)` por "key no estaba en saved con el mismo valor".
Preferimos precomputar el conjunto nuevo en `tasks_chatwoot` (donde ya existe `saved_facts` y la
variable `context_new`) y pasarlo como `pre_current_facts`, de modo que `build_current_turn_ack`
siga confirmando "solo current" pero current ya venga depurado. Esto mantiene la firma simple y
centraliza el "qué es nuevo" en un solo lugar.

- Alternativa considerada: filtrar dentro del ack recibiendo `saved_facts` como parámetro nuevo.
  Rechazada por duplicar la noción de "nuevo" (ya existe `context_new` en tasks_chatwoot) y por
  ampliar la firma. Se elige reusar el cómputo existente.
- Alternativa considerada: revertir extractor a 70b. Rechazada: reintroduce el problema TPD que
  el change anterior resolvió; además el ack debe ser robusto sin importar el modelo.

Nota: la siguiente pregunta del funnel SÍ debe derivarse de `merged_facts` (estado completo),
no solo de los nuevos — eso ya ocurre porque `next_question_from_missing_facts(facts)` usa el
`facts` mergeado. Solo el PREFIJO de confirmación se restringe a lo nuevo.

### D2 — `validate_extraction` emite `documents.renewal_proof` desde la señal
Tras iterar `extraction.fields`, añadir un bloque que, si `extraction.signals.renewal_proof in
{"si","no"}`, haga `out.append({fact_group:"documents", fact_key:"renewal_proof",
fact_value:<señal>, confidence:~0.8, is_explicit_correction:is_correction})`.

- Alternativa considerada: setearlo en `profile_extractor.py` (que ya lo hace en su path). Rechazada:
  ese path no es el activo aquí; el guard consume `_pre_validated`. La corrección debe vivir donde
  se construye el fact del path vivo.

### D3 — Confirmación contextual mapea renovación
En `_extract_context_confirmation_facts`, añadir: si la última pregunta del bot contiene el patrón
de comprobante de renovación (regex sobre "comprobante de renovación" / "papel ... renovación"),
entonces `is_yes` → `documents.renewal_proof = "si"`; y una negación corta → `documents.renewal_proof
= "no"`. Esto cubre el caso "Si" / "no" que el extractor no marca como señal.

- Reusar los `_TOPIC_*` existentes: agregar un `_TOPIC_RENEWAL_PROOF` análogo a `_TOPIC_APTO`.
- La negación corta ya se detecta vía `has_negation`; para el "no" explícito a renovación se añade
  una rama simétrica que setee `"no"` cuando el tópico es renovación y el mensaje es negativo.

## Risks / Trade-offs

- [El extractor 8b podría seguir parroteando otros campos] → El filtro de D1 es genérico (cualquier
  fact ya conocido con igual valor se excluye del ack), así que cubre todos los campos, no solo los
  observados. Mitigación adicional: tests que simulan extractor con echo de known_facts.
- [Doble fuente de renovación (D2 señal + D3 contextual)] → Ambas convergen al mismo fact
  `documents.renewal_proof`; el merge en `_current_turn_facts` usa "no sobrescribir si ya existe",
  así que no hay conflicto. Si ambas disparan con el mismo valor, es idempotente.
- [Falsos positivos de confirmación] → D3 solo dispara cuando la ÚLTIMA pregunta del bot fue la de
  renovación (gate por tópico), igual que el patrón ya probado de apto/licencia/cartas.
- [Cierre suave] → Cuando renewal_proof="no" con licencia <3 meses, `_renewal_question_for_short_expiry`
  ya fija `funnel.status="vencido_sin_tramite"`; verificar que ese path sigue intacto.

## Migration Plan

1. Implementar D1, D2, D3 + tests unitarios.
2. `docker compose build worker api && up -d worker api`.
3. Verificar en conversación real de Chatwoot: secuencia ciudad→edad→full→licencia E (vence 3
   meses)→"Si" al comprobante. Confirmar (a) cada ack solo acusa el dato nuevo y (b) el bot NO
   re-pregunta el comprobante y avanza al siguiente campo.
4. Rollback: revertir el commit; los cambios son acotados a 3 funciones y no hay migración de datos.

## Open Questions

- ¿El ack debe seguir confirmando un dato si el candidato lo REPITE explícitamente (no echo del
  extractor)? Decisión propuesta: si el valor no cambió respecto a lo guardado, no re-confirmar
  (es ruido); si es una corrección (valor distinto), sí confirmar. La rama de corrección ya está
  cubierta por `is_explicit_correction` y queda fuera del alcance de este fix.
