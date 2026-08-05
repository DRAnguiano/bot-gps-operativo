# Design — fix-note-risk-and-situated-denial-replies

## Context

Evidencia conv 178 (WhatsApp, primera conversación real del canal):

- Mensaje 4289 "…le mando fotos de mis tractos… todo el show pa k vea que si se arma" → `safety_intent` con `is_admission=true` (intent_enricher.py:100) → `risk_level=high`, `requires_human=true` → respuesta enlatada "Ese punto debe revisarlo nuestro equipo…" (knowledge_orchestrator.py:271) y nota "Candidato con Señal de Riesgo" con "⚠️ Riesgo: Alto" (chatwoot_note_sync.py:740).
- Los 3 turnos siguientes reportaron `risk_level=low` en el task result, pero sus notas siguieron siendo de riesgo: el label `riesgo_alto` se decide con `lead.get("risk_level")` (chatwoot_note_sync.py:314), que quedó en `high` persistido en el lead.
- Facts `license.expiration_text` / `medical.apto_expiration_text` guardados como "dos años" (el extractor unificado no normaliza números en palabras; el prompt del extractor legacy `profile_extractor` sí enseñaba dígitos).
- Respuesta 4302 = tres fragmentos apilados: "Perfecto. Cuando tenga la licencia o el apto actualizado, escríbanos…" + "Entendido, lo tomamos en cuenta y puedes enviarlo…" (tuteo) + "¿Cuenta con su documento de semanas cotizadas del IMSS?" (tercera vez).

## Goals / Non-Goals

**Goals:**

- Nota IA sin línea "Riesgo: Alto" y sin arrastre de riesgo a turnos sin señal.
- Coloquialismos sin contexto de seguridad no disparan admisión.
- Vigencias en dígitos al persistir (fuente única para resumen y nota).
- Un solo acuse de denegación por respuesta, generado con contexto; enlatado = fallback.

**Non-Goals:**

- No se toca la política de handoff para admisiones REALES de seguridad (esa sigue igual: requires_human + nota de riesgo).
- No se rediseña el pipeline de composición; solo se dedupe el join y se cambia el primario del acuse.
- No se persigue parseo general de fechas ("31 de diciembre de 2027" queda como está); solo números en palabras dentro de expresiones de duración.

## Decisions

**D1 — La línea "⚠️ Riesgo: Alto" se elimina del cuerpo de la nota.**
El título ("Candidato con Señal de Riesgo"), el estado y "Requiere Agente: Sí" ya comunican todo; la línea es redundante y alarma sin información accionable (feedback usuario 2026-07-13).

**D2 — El tipo de nota de riesgo se decide por la señal del TURNO, no por el lead.**
`_note_labels`/builder reciben hoy el `risk_level` pegado del lead; se pasa/usa el `risk_level` del turno actual (ya viaja en el result del orquestador). El label `riesgo_alto` puede seguir aplicado en Chatwoot como marca histórica de la conversación (eso es correcto: hubo una señal), pero la NOTA de cada turno refleja el turno. Alternativa rechazada: limpiar `risk_level` del lead al primer turno low — borra historia que Capital Humano puede necesitar.

**D3 — Few-shots de coloquialismos en el clasificador multi-intent.**
Regla del proyecto "prompt over dictionary": se enseña al clasificador con contraejemplos reales ("todo el show pa k vea que si se arma" = entusiasmo por demostrar experiencia; "deme chance", "está la onda" = coloquial) que `is_admission` exige referencia real a sustancias/alcohol/seguridad operativa. No se construye lista negra en código.

**D4 — Canonicalización numérica determinista al persistir duraciones.**
Mapa fijo uno→1 … doce→12 aplicado SOLO dentro de expresiones de duración/vigencia (`*.expiration_text`, patrón "N año(s)/mes(es)/semana(s)/día(s)") en el chokepoint de canonicalización de facts (misma capa que `documents.proof`). Es normalización de formato (como `is_local_laguna` string), no política de negocio: no viola la regla de seed-solo-vocabulario. El valor mostrado en resumen/nota sale ya normalizado por leer el fact persistido.

**D5 — Acuse de denegación: LLM situado primario, enlatado fallback, join con dedupe.**
Los tres orígenes de acuse predefinido (requires_human deflection línea 271, plantillas "lo anotamos" ~1107/1112, y el fragmento de renovación) pasan a ser fallback de `_generate_situated_reply` (mecanismo existente, ya usado para `document_ack` y validado en prod), con instrucción situada: reconoce lo que el candidato dijo (denegación/postergación + su circunstancia), NO prometas excepciones ni evalúes si califica, trato de usted en singular, y cierra con la ÚNICA pregunta pendiente. El join de composición garantiza una sola instancia de la pregunta: si la pregunta del funnel ya está contenida en el acuse generado, no se re-adjunta; y nunca se concatenan dos acuses (el primero gana, los demás se descartan).

## Risks / Trade-offs

- **D2**: una conversación con señal real de riesgo seguida de turnos normales dejará de re-emitir nota de riesgo en cada turno — es el comportamiento deseado; el label en la conversación conserva la marca.
- **D3**: few-shots pueden no cubrir todo coloquialismo; el fallo residual degrada al comportamiento actual (falso positivo puntual), no a algo peor.
- **D4**: mapa acotado a doce; "quince años" quedaría en palabras — aceptable (vigencias reales son cortas). Solo se toca el patrón duración; fechas y textos libres intactos.
- **D5**: el LLM podría no incluir la pregunta → la validación existente de `_generate_situated_reply`/join degrada al fallback enlatado + pregunta literal (mismo contrato D8 de las transiciones). El dedupe usa igualdad normalizada de la pregunta, no similitud — conservador: en el peor caso la pregunta aparece una vez en el acuse y una vez literal solo si el LLM la reformuló mucho.
