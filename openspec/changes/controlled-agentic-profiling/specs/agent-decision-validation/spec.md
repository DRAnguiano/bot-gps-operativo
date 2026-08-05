## ADDED Requirements

### Requirement: Frontera de autoridad del modelo validada en código
El sistema SHALL impedir, por construcción del validador (no solo por prompt), que
el modelo: marque `perfil_listo` directamente; escriba etiquetas críticas
directamente; apruebe o rechace candidatos; invente políticas, rutas, pagos o
requisitos; sobrescriba datos previos sin evidencia; o ejecute acciones CRM sin
pasar por los validadores. Etiquetas y `perfil_listo` SHALL derivarse
exclusivamente de `calculate_candidate_labels` y `profile_funnel_complete` sobre
facts certificados.

#### Scenario: El agente no puede marcar perfil_listo
- **WHEN** un AgentDecision declara el perfil completo con campos requeridos
  faltantes en los facts certificados
- **THEN** perfil_listo no se emite y la discrepancia queda logueada

#### Scenario: Handoff solo-activar
- **WHEN** el agente recomienda NO derivar a humano en un caso donde los overrides
  deterministas (B1, reingreso, edad) ya exigen revisión humana
- **THEN** la revisión humana se mantiene (la recomendación solo puede activar,
  nunca desactivar)

### Requirement: Validación de proposed_facts antes de persistir
Todo `proposed_fact` SHALL pasar, en orden: (1) evidencia textual literal presente
en el mensaje del turno — si no, se descarta y se loguea `[AGENT_FACT_REJECTED]`;
(2) confidence ≥ `AGENT_FACT_MIN_CONFIDENCE`; (3) la Capa 2 existente
(`validate_extraction`: catálogos de unidad, licencia B/E, edad, vigencias) — el
MISMO camino de persistencia del extractor actual, sin bypass; (4) chequeo de
contradicción: un valor distinto al fact previo sin marcador explícito de
corrección SHALL NOT sobrescribir y SHALL registrarse como uncertainty_flag.

#### Scenario: Fact sin evidencia se descarta
- **WHEN** el agente propone `candidate.city=Torreón` y "Torreón" no aparece en el
  mensaje del turno
- **THEN** el fact no persiste y queda trazado como rechazado

#### Scenario: Contradicción sin corrección explícita no pisa
- **WHEN** el agente propone `experience.vehicle_type=sencillo` y el fact previo es
  `full`, sin que el candidato haya expresado corrección
- **THEN** el fact previo se conserva y la ambigüedad aparece como uncertainty_flag
  en la Nota IA

#### Scenario: Catálogos de Capa 2 aplican igual al agente
- **WHEN** el agente propone `license.category=A`
- **THEN** aplica la misma regla vigente (A no satisface el requisito; se preserva
  como category_raw)
