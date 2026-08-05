## ADDED Requirements

### Requirement: Un único detector de pregunta embebida
El sistema SHALL tener un único detector de "pregunta embebida en mensaje compuesto" consumido tanto por el guard del worker como por el orquestador. NO SHALL coexistir dos detectores en desacuerdo (hoy `signals.has_embedded_question` en el worker vs `_looks_like_question` en el orquestador). El detector SHALL reconocer una pregunta de negocio aunque el mensaje NO tenga signo `?` ni un término de negocio conocido explícito.

#### Scenario: Guard y orquestador coinciden
- **WHEN** un mensaje compuesto (dato de perfil + pregunta) se evalúa
- **THEN** el guard y el orquestador usan el mismo detector y llegan al mismo veredicto sobre si hay pregunta embebida

#### Scenario: Compuesto sin marcador explícito
- **WHEN** el candidato dice algo como "manejo full y ando viendo cuanto sale el km" (sin `?` claro)
- **THEN** el detector reconoce la pregunta de negocio embebida y el turno la responde, sin descartarla en silencio

#### Scenario: Pregunta compuesta se responde a media marcha del funnel
- **WHEN** falta un campo del funnel y el candidato aporta un dato + pregunta de negocio en el mismo turno
- **THEN** se responde la pregunta (RAG/policy), se preserva el pendiente y NO se avanza el funnel — sin depender de qué modelo clasifique
