# fact-value-canonicalization — delta

## MODIFIED Requirements

### Requirement: Duraciones de vigencia con dígitos

Los facts de vigencia/duración (`license.expiration_text`, `medical.apto_expiration_text` y equivalentes) SHALL persistirse con los números en dígitos cuando el candidato los exprese en palabras dentro de una expresión de duración (p. ej. "dos años" → "2 años", "un mes" → "1 mes"); la normalización es determinista, acotada a números en palabras dentro del patrón de duración, y MUST NOT alterar fechas ni textos que no siguen ese patrón.

#### Scenario: Duración en palabras

- **WHEN** cualquier ruta de extracción produce una vigencia expresada como número en palabras ("vence en dos años")
- **THEN** el fact persistido contiene el número en dígitos ("2 años" / "vence en 2 años") y el resumen y la nota lo muestran así

#### Scenario: Fecha explícita intacta

- **WHEN** la vigencia es una fecha ("31 de diciembre de 2027") o un texto sin patrón de duración ("vencido")
- **THEN** el valor se persiste sin modificación
