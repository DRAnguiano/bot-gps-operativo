# funnel-llm-transitions

## MODIFIED Requirements

### Requirement: Voz gramatical única en las transiciones generadas

El prompt de la transición generada del funnel SHALL fijar la voz de Mundo: primera persona del singular con trato de usted ("¿Me podría indicar...?"), nunca plural corporativo ("indicarnos", "necesitamos") ni tuteo. La validación es por prompt (regla del proyecto: prompt sobre diccionario), sin regex post-generación.

#### Scenario: El prompt instruye la voz

- **GIVEN** el generador de transiciones del funnel
- **WHEN** se construye el prompt de generación
- **THEN** el prompt contiene la instrucción de primera persona del singular y trato de usted
