## ADDED Requirements

### Requirement: Guardia de ruego/insistencia con pausa de 1 hora
Cuando el candidato dice que NO tiene un requisito y NO aporta alternativa, el sistema SHALL contar sus mensajes de insistencia/ruego (`insistence_count`). Durante las insistencias 1..5 SHALL responder empático manteniendo la política. Si el candidato aporta un documento/alternativa válida en cualquier momento, SHALL resetear el contador y seguir el funnel. Tras la 5ª insistencia sin dato válido, SHALL emitir un mensaje empático final y NO SHALL responder al candidato durante 1 hora (`paused_until`), preservando el avance del perfil.

#### Scenario: Insistencia respondida con empatía (1..5)
- **WHEN** el candidato no tiene el documento y ruega ("tengo familia, apiádese, trabajo gratis")
- **THEN** el LLM responde empático ("entiendo; en cuanto tenga sus documentos vigentes continuamos") y NO cede la política

#### Scenario: Reset al aportar dato válido
- **WHEN** durante la insistencia el candidato dice que sí tiene uno de los documentos aceptados
- **THEN** `insistence_count` se resetea y el funnel continúa normal

#### Scenario: Pausa tras la 5ª insistencia
- **WHEN** el candidato insiste por 5ª vez sin aportar documento/alternativa válida
- **THEN** el sistema envía un mensaje empático final y suprime respuestas por 1 hora; el avance del perfil se preserva

#### Scenario: Reanudar tras la pausa
- **WHEN** pasó 1 hora desde `paused_until` y el candidato escribe
- **THEN** el bot reanuda desde donde quedó el perfil
