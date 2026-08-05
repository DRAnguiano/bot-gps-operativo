## ADDED Requirements

### Requirement: Finalidad conversacional en el clasificador unificado
El clasificador unificado de turno SHALL emitir `conversational_purpose`
("smalltalk" | "queja" | "agradecimiento" | "despedida" | "animo" | "none") y
`is_joke_request` como señales adicionales EN LA MISMA llamada LLM existente (sin
llamadas dedicadas por intención), definidas por few-shots que distingan el uso
genuino del idiomático (p. ej. "cuéntame un chiste" = petición; "así que chiste" =
queja).

#### Scenario: Chiste embebido en mensaje compuesto
- **WHEN** el candidato escribe "Licencia vence en dos años... Oye usted no cuenta
  chistes para animarme"
- **THEN** `is_joke_request=true` aunque el mensaje también traiga datos de perfil

#### Scenario: Uso idiomático no dispara humor
- **WHEN** el candidato escribe "así que chiste todo este proceso"
- **THEN** `is_joke_request=false` y `conversational_purpose="queja"`

### Requirement: Respuesta generada para turnos conversacionales
El sistema SHALL generar con el LLM (persona Mundo, contexto del lead y datos
deterministas del turno) la respuesta de todo turno con `conversational_purpose` ≠
"none" (o `is_joke_request`) que sea seguro (sin requires_human, sin risk alto, sin
términos vetados), en vez de un texto fijo; el texto fijo SHALL usarse únicamente
como degradación ante fallo o vacío del LLM. Los guardrails vigentes SHALL
mantenerse: fail-closed de pago sin fuente autorizada, no-promesa de contratación,
léxico de vigencia, y el friendly no hace preguntas (el nudge del sistema las
agrega).

#### Scenario: Queja recibe respuesta empática generada
- **WHEN** el candidato se queja del proceso en tono casual y el turno es seguro
- **THEN** la respuesta es generada (empática, variada) + nudge del funnel, no
  CONTROLLED_FALLBACK_REPLY

#### Scenario: Texto fijo solo como degradación
- **WHEN** el LLM falla al generar la respuesta conversacional
- **THEN** el candidato recibe el texto determinista de fallback y el turno se
  completa

#### Scenario: Guardrail de pago intacto
- **WHEN** el turno conversacional además pide cifras de pago sin fuente autorizada
- **THEN** aplica el fail-closed vigente (deriva sin inventar montos)

### Requirement: Terms Neo4j sin intenciones conversacionales
Los Terms del seed Neo4j SHALL limitarse a vocabulario de negocio
(lenguaje→concepto); las intenciones CONVERSACIONALES (humor, small talk, queja)
SHALL detectarse por el extractor few-shot, y los Terms conversacionales existentes
SHALL retirarse tras verificar que la señal del extractor los cubre.

#### Scenario: Overlap de aliases no secuestra el turno
- **WHEN** un mensaje compuesto contiene un alias de negocio ("licencia") y una
  intención conversacional
- **THEN** la intención conversacional se detecta por el extractor y no se pierde
  por la competencia de aliases exactos
