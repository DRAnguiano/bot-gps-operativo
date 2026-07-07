## ADDED Requirements

### Requirement: Resumen de confirmación al cierre del funnel
Al completarse el último dato del funnel conversacional, el sistema SHALL mostrar al
candidato un resumen determinista de sus datos registrados (ciudad, edad, unidad,
licencia y vigencia, experiencia, comprobante laboral) y SHALL preguntar "¿Es
correcto?" ANTES del cierre. Una afirmación SHALL continuar al cierre normal; una
corrección SHALL actualizar el fact señalado (pipeline de correcciones existente) y
re-confirmar solo el dato cambiado. El resumen SHALL emitirse una sola vez
(`funnel.summary_confirmed`).

#### Scenario: Confirmación afirmativa cierra
- **WHEN** el candidato responde "sí, es correcto" al resumen
- **THEN** el funnel cierra normal (paso de documentos) y no se repite el resumen

#### Scenario: Corrección actualiza y re-confirma
- **WHEN** el candidato responde "la ciudad es Lerdo, lo demás sí"
- **THEN** el fact de ciudad se actualiza y el bot re-confirma solo ese dato

#### Scenario: Red de seguridad contra errores de transcripción
- **WHEN** un dato quedó mal por una transcripción/extracción errónea (p. ej. "futbol")
- **THEN** el candidato lo ve en el resumen y puede corregirlo antes del cierre
