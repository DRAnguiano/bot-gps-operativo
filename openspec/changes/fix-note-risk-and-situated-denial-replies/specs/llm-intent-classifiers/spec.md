# llm-intent-classifiers — delta

## MODIFIED Requirements

### Requirement: Coloquialismos sin contexto de seguridad no son admisión

El clasificador multi-intent SHALL marcar `safety_intent` con admisión únicamente cuando el mensaje refiere realmente a sustancias, alcohol o seguridad operativa; expresiones coloquiales del habla del candidato (p. ej. "se arma", "deme chance", "está la onda", "el show") sin ese contexto SHALL NOT clasificarse como admisión, y el prompt del clasificador SHALL incluir contraejemplos coloquiales que lo enseñen.

#### Scenario: Entusiasmo coloquial por demostrar experiencia

- **WHEN** el candidato ofrece evidencia de su trabajo con lenguaje coloquial (p. ej. "le mando fotos de mis tractos y todo el show pa que vea que sí se arma")
- **THEN** el turno no se clasifica como admisión de seguridad ni escala a riesgo alto

#### Scenario: Admisión real se conserva

- **WHEN** el mensaje refiere consumo de sustancias o conducta insegura de forma reconocible
- **THEN** la clasificación de admisión y la política de riesgo/derivación operan como hasta ahora
