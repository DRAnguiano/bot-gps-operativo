# empathetic-funnel-reencauce

## MODIFIED Requirements

### Requirement: El re-encauce natural se ejecuta sin errores de scope

El sistema SHALL ejecutar la rama de re-encauce natural (respuesta empática generada ante negativa/lateral/ambigua a un campo del funnel) sin errores de nombre: los facts de contexto se construyen dentro del scope de `handle_message` (persistidos + validados del turno). Un error dentro de la rama SHALL quedar cubierto por un test de regresión que falle si la rama vuelve a morir en silencio.

#### Scenario: Respuesta ambigua al campo preguntado produce re-encauce

- **GIVEN** el funnel preguntó un campo y el candidato responde algo ambiguo sin pregunta de negocio
- **WHEN** route1 clasifica la respuesta como no persistible (ambigua/negativa/lateral)
- **THEN** se genera un re-encauce natural (texto no vacío) en lugar de re-preguntar en seco
- **AND** el log NO contiene `[ROUTE1] omitido por error`

#### Scenario: Insistencia y re-encauce avanzan juntos

- **GIVEN** un candidato que responde evasivamente varias veces seguidas
- **WHEN** el contador de insistencia incrementa
- **THEN** cada incremento va acompañado de su mensaje de re-encauce (nunca contador sin mensaje)
