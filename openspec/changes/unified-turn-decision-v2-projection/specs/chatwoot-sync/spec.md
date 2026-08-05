## ADDED Requirements

### Requirement: Nota, labels y stage coinciden y se proyectan desde V2
La nota IA, los labels y el stage en Chatwoot SHALL derivarse del estado de V2 vía el outbox, y SHALL ser consistentes entre sí para un mismo lead/turno.

#### Scenario: perfil_listo coherente
- **WHEN** el lead alcanza `perfil_listo` según `funnel_state_planner`
- **THEN** el stage de V2, los labels y la nota en Chatwoot reflejan `perfil_listo` de forma coincidente (sin uno en un estado y otro en otro)

#### Scenario: labels reflejan V2 tras reingreso
- **WHEN** se reproyecta un lead que regresó
- **THEN** los labels aplicados corresponden a los facts/stage de V2 (faltantes reales), no a un cálculo paralelo obsoleto
