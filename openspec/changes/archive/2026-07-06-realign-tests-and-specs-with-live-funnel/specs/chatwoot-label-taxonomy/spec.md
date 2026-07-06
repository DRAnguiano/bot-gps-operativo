## ADDED Requirements

### Requirement: Labels de insistencia y descarte por edad

El catálogo oficial SHALL incluir `insistencia` y `descartado_edad`.

`insistencia` SHALL emitirse mientras el lead tenga una pausa por insistencia activa
(`funnel.paused_until` en el futuro, fijada por la guardia de ruego tras 5 insistencias
sin dato válido) para que Capital Humano vea el caso; al expirar la pausa el label SHALL
dejar de emitirse en la siguiente proyección.

`descartado_edad` SHALL emitirse cuando el candidato queda fuera de perfil por edad
(≥ límite configurado) y SHALL ser terminal (remueve `bot_activo`). El descarte por edad
SHALL NOT quedar sin rastro de label (comportamiento previo: cierre con lista vacía).

#### Scenario: Pausa por insistencia activa
- **WHEN** la guardia de insistencia pausó al lead y la pausa sigue vigente
- **THEN** la proyección de labels incluye `insistencia`

#### Scenario: Pausa expirada
- **WHEN** la pausa por insistencia ya expiró
- **THEN** la proyección de labels NO incluye `insistencia`

#### Scenario: Descarte por edad con rastro
- **WHEN** el candidato declara una edad en o sobre el límite configurado
- **THEN** la proyección de labels es `descartado_edad` (terminal, sin `bot_activo`)
