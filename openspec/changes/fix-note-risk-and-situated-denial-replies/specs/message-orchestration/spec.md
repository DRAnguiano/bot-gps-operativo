# message-orchestration — delta

## MODIFIED Requirements

### Requirement: Acuse de denegación único y situado

Cuando el candidato deniega o pospone un dato/documento solicitado, la respuesta del turno SHALL contener exactamente UN acuse — generado por el LLM situado con el contexto del turno (lo que el candidato dijo, lo que falta, la única pregunta pendiente; trato de usted en singular, sin prometer excepciones ni evaluar elegibilidad) — y a lo más UNA instancia de la pregunta pendiente. Los textos de acuse predefinidos SHALL usarse únicamente como degradación determinista cuando la generación falla o es inválida. La composición MUST NOT concatenar múltiples acuses predefinidos ni repetir la misma pregunta dentro de una respuesta.

#### Scenario: Denegación con circunstancia personal

- **WHEN** el candidato deniega un documento explicando su circunstancia (p. ej. "no tengo eso, pero deme chance, tengo familia")
- **THEN** la respuesta reconoce la circunstancia en un solo acuse natural y cierra con una única instancia de la pregunta o siguiente paso pendiente

#### Scenario: Generación falla

- **WHEN** la generación situada del acuse falla o produce salida inválida
- **THEN** la respuesta degrada al acuse predefinido + pregunta literal, una sola vez cada uno

#### Scenario: Sin apilamiento de fragmentos

- **WHEN** varios mecanismos de composición aportan acuse para el mismo turno
- **THEN** la respuesta final contiene solo el primero aplicable — nunca dos acuses concatenados ni la pregunta duplicada
