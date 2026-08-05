## ADDED Requirements

### Requirement: Guardia anti-spam por volumen/ritmo (agnóstica de contenido)
El sistema SHALL limitar el volumen de mensajes procesados por lead en una ventana corta. Si un lead supera un umbral configurable (p. ej. N mensajes en T segundos) o envía mensajes mientras un turno del mismo lead sigue procesando, el sistema SHALL coalescer los mensajes en un solo turno y/o aplicar un cooldown breve, sin generar una respuesta LLM por cada mensaje. Mensajes idénticos repetidos SHALL descartarse como duplicados. Un flood sostenido SHALL activar la pausa temporal (mismo mecanismo que la guardia de insistencia).

#### Scenario: Ráfaga coalescida sin una llamada LLM por mensaje
- **WHEN** un lead envía 8 mensajes en 15 segundos
- **THEN** el sistema los procesa como un solo turno combinado (debounce), sin gastar una generación LLM por mensaje ni gatillar 429

#### Scenario: Duplicados descartados
- **WHEN** un lead envía el mismo mensaje repetido varias veces seguidas
- **THEN** se descartan los duplicados y se procesa una sola vez

#### Scenario: Flood sostenido → pausa
- **WHEN** un lead mantiene un flood anormal más allá del umbral
- **THEN** se aplica una pausa temporal (silencio) preservando el estado, como en la guardia de insistencia
