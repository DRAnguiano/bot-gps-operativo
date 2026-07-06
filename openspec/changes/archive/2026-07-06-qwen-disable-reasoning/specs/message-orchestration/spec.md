## ADDED Requirements

### Requirement: Generación sin razonamiento truncado
Cuando el modelo de generación de respuestas es un modelo qwen *reasoning*, el sistema SHALL suprimir su modo de razonamiento (interruptor `/no_think`) para que la respuesta al candidato sea directa y completa, sin bloques de pensamiento ni respuestas truncadas dentro del razonamiento. La supresión SHALL estar condicionada al modelo (sin efecto en modelos no-qwen).

#### Scenario: Respuesta directa con qwen
- **WHEN** el generador es qwen y se produce una respuesta (friendly, RAG o embebida)
- **THEN** el candidato recibe la respuesta directa, sin `<think>` ni contenido de razonamiento, y sin truncarse

#### Scenario: Modelo no-qwen sin cambios
- **WHEN** el generador NO es un modelo qwen reasoning
- **THEN** no se aplica la supresión de razonamiento y el comportamiento no cambia

### Requirement: Respuesta embebida limpia
Cuando se produce una respuesta a la pregunta embebida de un mensaje compuesto (multi-intención), esta SHALL pasar por el mismo limpiador unificado que el resto de rutas, de modo que llegue sin artefactos de generación (bloque de razonamiento vacío, marcadores de blockquote). (El que la respuesta embebida se produzca y anteponga en TODO mensaje compuesto es un gap de routing del orquestador — model-agnostic, verificado — que se resuelve en un cambio aparte.)

#### Scenario: Sin artefactos en la respuesta embebida
- **WHEN** el generador emite un bloque de razonamiento vacío o marcadores de blockquote en la respuesta embebida
- **THEN** el limpiador unificado los elimina antes de enviar al candidato
