## ADDED Requirements

### Requirement: Respuestas naturales por LLM ante negativas/laterales/absurdas
Cuando el candidato no aporta un valor válido para el dato pedido (niega, divaga o responde algo irrelevante), el sistema SHALL generar el reply con el LLM (persona de Mundo): acuse con tacto + política/alternativa si aplica + re-encauce al dato pendiente. NO SHALL forzar el mensaje enlatado, y SHALL preservar el dato pendiente. Aplica a todas las preguntas del funnel (licencia, apto, unidad, documentos, experiencia, ciudad).

#### Scenario: Respuesta absurda re-encauzada
- **WHEN** el bot pregunta la experiencia y el candidato dice "solo tengo experiencia con videos de tiktok"
- **THEN** el LLM responde natural (con tacto) y vuelve a pedir el dato pendiente; NO repite el enlatado ni marca el dato respondido

#### Scenario: Negativa respondida con empatía
- **WHEN** el candidato niega tener un requisito ("no tengo cartas")
- **THEN** el LLM responde empático, ofrece la alternativa si existe, y re-encauza — sin sonar robótico
