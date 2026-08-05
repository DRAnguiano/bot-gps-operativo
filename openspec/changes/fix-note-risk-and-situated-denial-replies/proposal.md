# Proposal — fix-note-risk-and-situated-denial-replies

## Why

Primera conversación real por WhatsApp (conv 178, 2026-07-13) expuso tres defectos de calidad de respuesta/nota: (1) la frase coloquial "…le mando fotos de mis tractos… y todo el show pa k vea que si se arma" fue clasificada como admisión de seguridad → `risk_level=high` → nota "Candidato con Señal de Riesgo" con línea "⚠️ Riesgo: Alto", respuesta enlatada de derivación en lugar del funnel, y el riesgo quedó PEGADO en el lead: los 3 turnos siguientes (risk `low`) siguieron emitiendo nota de riesgo; (2) los facts de vigencia se persisten con números en palabras ("dos años") y así viajan a resumen y nota — informal; (3) los turnos de denegación de documento ("no tengo eso, pero deme chance…") produjeron respuestas cosidas de acuses predefinidos apilados — el peor caso pegó TRES fragmentos (uno de usted, otro de tuteo) y repitió la misma pregunta del IMSS por tercera vez.

## What Changes

- **(A) Nota IA sin línea de riesgo y sin riesgo pegajoso**: se elimina la línea "⚠️ Riesgo: Alto" del cuerpo de la nota (el título y el estado ya lo comunican); la nota de tipo riesgo se emite solo cuando el TURNO ACTUAL trae señal de riesgo, no por el `risk_level` histórico del lead.
- **(B) Clasificador: coloquialismos no son admisión**: few-shots en el clasificador multi-intent para que expresiones coloquiales norteñas ("se arma", "deme chance", "está la onda", "el show") no se marquen `safety_intent`/`is_admission` sin contexto real de sustancias/seguridad.
- **(C) Vigencias con dígitos**: canonicalización determinista de números en palabras a dígitos en los facts de duración/vigencia al persistir ("dos años" → "2 años", "un año" → "1 año"); resumen y nota los muestran ya normalizados.
- **(D) Acuses de denegación situados, sin apilamiento**: los turnos donde el candidato deniega/pospone un dato o documento generan UN solo acuse vía LLM situado (contexto: mensaje del candidato, qué falta, siguiente pregunta; voz usted singular) usando el mecanismo `_generate_situated_reply` existente; los textos predefinidos quedan SOLO como fallback determinista (patrón D8 ya validado). La composición garantiza: un solo acuse y una sola instancia de la pregunta por respuesta — nunca fragmentos apilados.

## Capabilities

### New Capabilities

(ninguna)

### Modified Capabilities

- `chatwoot-ai-note`: nota de riesgo sin línea redundante de riesgo; tipo de nota decidido por señal del turno actual.
- `llm-intent-classifiers`: coloquialismos sin contexto de seguridad no constituyen admisión.
- `fact-value-canonicalization`: duraciones/vigencias se persisten con dígitos.
- `message-orchestration`: acuse de denegación único, generado situado con fallback enlatado; sin duplicación de acuses ni de pregunta.

## Impact

- `app/chatwoot_note_sync.py` — nota de riesgo (bloque 4.6) y label `riesgo_alto`.
- Clasificador multi-intent (few-shots de `safety_intent`/`is_admission`).
- Punto de persistencia de facts `*.expiration_text` (canonicalización numérica).
- `app/orchestrators/knowledge_orchestrator.py` — acuses de denegación (`_controlled_reply_from_contract`, plantillas "lo anotamos", joins que apilan fragmentos).
- Tests: nota, clasificador (estructural de prompt), canonicalización, composición de denegación.
