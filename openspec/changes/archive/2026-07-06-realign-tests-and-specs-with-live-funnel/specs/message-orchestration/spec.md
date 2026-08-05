## MODIFIED Requirements

### Requirement: Acuse del funnel sin eco de datos

Al registrar datos de perfil aportados por el candidato, el sistema SHALL responder con un
conector breve y VARIADO (p. ej. "Va." / "Perfecto." / "Listo.") seguido de la siguiente
pregunta del funnel, y SHALL NOT repetir (eco) el valor de los datos recién aportados
("licencia tipo E vigente", "20 años de experiencia, anotado"). Esto subsume la regla
anti-duplicación previa: sin eco no hay dato repetido en dos formas.

Excepción única: la primera vez que se conoce el nombre del candidato
(`name_just_learned`), el acuse SHALL ser el saludo con nombre de pila ("Gracias,
<nombre>.") más la siguiente pregunta — única confirmación que menciona un dato.

Cuando el perfil conversacional queda completo, el cierre SHALL ser ligero: acusar el
avance e indicar el siguiente paso (documentos) una sola vez, SHALL NOT repetir
recordatorios de proceso ni condicionar el contacto ("siempre que sigas interesado").

#### Scenario: Dato registrado sin eco
- **WHEN** el candidato aporta un dato del funnel (unidad, licencia, años, ciudad…)
- **THEN** el reply es un conector breve + la siguiente pregunta del funnel
- **AND** el reply NO contiene el valor del dato recién aportado

#### Scenario: Saludo con nombre la primera vez
- **WHEN** el sistema conoce el nombre del candidato por primera vez en el turno
- **THEN** el acuse es "Gracias, <nombre de pila>." + la siguiente pregunta del funnel

#### Scenario: Conector variado, no enlatado
- **WHEN** se generan acuses en turnos consecutivos
- **THEN** el conector varía (no es una frase fija repetida turno a turno)

### Requirement: Confirmación contextual corta resuelve el campo según la última pregunta

El sistema SHALL resolver de forma determinista (sin LLM) el campo de perfil
correspondiente a la última pregunta cerrada del bot cuando el candidato responde con una
confirmación o negación corta ("Sí", "ya tengo", "no", "todavía no"). Esto incluye apto
médico, vigencia de licencia, cartas laborales y el comprobante de pago de renovación o
trámite (la alternativa vigente cuando licencia/apto no están vigentes).

En particular, cuando la última pregunta del bot fue por el comprobante de pago de la
renovación/trámite, una confirmación corta SHALL fijar `documents.renewal_proof = "si"` y
una negación corta SHALL fijar `documents.renewal_proof = "no"` (cierre suave por
vencido-sin-trámite en lugar de re-preguntar).

#### Scenario: Confirmación al comprobante de pago
- **WHEN** el bot preguntó por el comprobante de pago de la renovación y el candidato
  responde "Sí" o "ya tengo el comprobante"
- **THEN** el sistema fija `documents.renewal_proof = "si"` y el funnel no re-pregunta

#### Scenario: Negación al comprobante de pago
- **WHEN** el bot preguntó por el comprobante de pago y el candidato responde "no" o
  "todavía no"
- **THEN** el sistema fija `documents.renewal_proof = "no"` y aplica el cierre suave por
  vencido-sin-trámite
