## ADDED Requirements

### Requirement: Acuse personalizado por nombre de pila la primera vez
Cuando el nombre del candidato se conoce por primera vez en el turno (extraído de un documento por visión o respondido al funnel), el acuse del turno SHALL saludar con "Gracias, <nombre de pila>." una sola vez. En turnos posteriores, ya conocido el nombre, NO SHALL repetir el vocativo. Si no hay nombre disponible, el acuse SHALL omitir el vocativo sin fallar.

#### Scenario: Primera vez que se conoce el nombre
- **WHEN** el nombre es nuevo de este turno y hay un nombre de pila válido
- **THEN** el acuse comienza con "Gracias, <nombre>." seguido de la siguiente pregunta del funnel

#### Scenario: Nombre ya conocido en turnos posteriores
- **WHEN** el nombre ya estaba establecido antes de este turno
- **THEN** el acuse NO incluye el vocativo "Gracias, <nombre>."

#### Scenario: Sin nombre disponible
- **WHEN** no hay `candidate.name` disponible
- **THEN** el acuse usa el texto genérico sin vocativo y no falla

### Requirement: Pregunta de unidad sin redundancia
La pregunta del funnel para el tipo de unidad (cuando aún no se conoce la licencia) SHALL mencionar la disponibilidad de vacantes una sola vez y luego preguntar, sin repetir "full o sencillo" dos veces.

#### Scenario: Copy de unidad
- **WHEN** el funnel pregunta el tipo de unidad sin licencia conocida
- **THEN** el texto es "Le comento, actualmente tenemos vacantes para operador de tracto full y de sencillo. ¿En cuál tiene experiencia?" (una sola mención de full/sencillo)

### Requirement: Mundo no se presenta como Capital Humano
El system message del LLM de respuesta SHALL instruir a Mundo a hablar como parte del equipo de reclutamiento de Transmontes y a NUNCA presentarse al candidato como "Capital Humano". Las notas internas dirigidas al equipo ("Para Capital Humano") quedan fuera de este requisito.

#### Scenario: Saludo del LLM
- **WHEN** el LLM genera una respuesta de presentación o saludo
- **THEN** se identifica como Mundo del equipo de Transmontes y no como "asistente de Capital Humano"

#### Scenario: Intro público del primer reply
- **WHEN** se antepone el intro de presentación (`ASSISTANT_PUBLIC_INTRO`) al primer reply de una conversación
- **THEN** el texto identifica a Mundo como parte del equipo de Transmontes y NO como "asistente de Capital Humano"
