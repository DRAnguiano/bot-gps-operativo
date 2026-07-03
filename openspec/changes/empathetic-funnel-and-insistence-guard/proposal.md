## Why

El perfilamiento hoy es **robótico** ante respuestas no-estándar y **redundante** al cerrar. Observado en prod (conv 160, 2026-07-03):

- El candidato dio *"tengo cartas laborales, no tengo semanas IMSS"* → el sistema detectó bien que **cartas O IMSS basta** y marcó `perfil_listo`, PERO respondió el genérico *"sube tus documentos: licencia, apto, cartas… nos comunicaremos contigo"* — **redundante**: ya cumple, debió decir *"con las cartas laborales es suficiente, continuamos"*.
- Ante una **negativa** ("no tengo X") o una respuesta **absurda/lateral** ("solo tengo experiencia con videos de tiktok"), hoy se **fuerza la pregunta enlatada** del funnel en vez de responder natural con el LLM.
- No hay manejo de **alternativas** por requisito (cartas↔IMSS; licencia/apto no vigente → comprobante de pago/trámite).
- No hay defensa ante **ruego/insistencia** ("ándele acépteme, tengo familia, trabajo gratis…", fotos de camiones/hijos): el sistema debería responder empático y, tras insistencia sostenida, **pausar** sin quemar recursos ni ceder la política.

## What Changes

- **Respuestas naturales (LLM) para negativas y respuestas laterales en TODAS las preguntas del funnel** (licencia, apto, unidad, documentos, experiencia, ciudad): en vez del mensaje enlatado, el LLM responde con tacto y **re-encauza** al dato pendiente, sin sonar robótico. Ante absurdo/irrelevante: responde natural + vuelve a pedir el dato.
- **Cierre sin redundancia**: cuando el requisito ya está cumplido (p. ej. cartas **O** IMSS), acusar específico ("con las cartas laborales es suficiente, continuamos") y NO repetir el recordatorio genérico de "sube tus documentos / nos comunicaremos".
- **Alternativas por requisito** (dominio):
  - **Comprobante laboral**: cartas laborales membretadas **O** semanas cotizadas del IMSS. Si falta una, ofrecer la otra (aplica a local ZM Laguna).
  - **Licencia / apto médico no vigente**: la alternativa aceptada es el **comprobante de pago** de renovación/trámite.
  - **Los demás datos** son obligatorios (sin alternativa).
- **Guardia de ruego/insistencia + pausa de 1h**:
  - Se activa cuando el candidato dice que **NO tiene** un documento requerido.
  - Se cuentan los **mensajes del candidato** posteriores; mientras insiste/ruega (familia, apiádate, trabajo gratis, "lo consigo cuando me paguen", fotos irrelevantes), el LLM responde **empático** ("entiendo; en cuanto tenga sus documentos vigentes continuamos").
  - Si en cualquier momento **aporta un documento válido** → se reanuda normal (reset del contador).
  - Tras la **5ª insistencia** sin documento válido → **un** mensaje empático final y **el bot deja de responder por 1 hora**, preservando el avance del perfil. Al reanudar (tras la hora), retoma donde quedó.
- **Fix menor**: "20 anos años" (duplicación de "años" en el ack de experiencia).

## Capabilities

### New Capabilities
- `empathetic-funnel-responses`: negativas/laterales/absurdas respondidas por LLM con re-encauce, en todas las preguntas del funnel.
- `document-alternatives`: alternativas aceptadas por requisito (cartas↔IMSS; licencia/apto → comprobante de pago).
- `insistence-guard`: detección de ruego + pausa de 1h tras 5 insistencias sin documento válido; preserva estado.

### Modified Capabilities
- `chatwoot-ai-note` / `chatwoot-label-taxonomy`: reflejar estado de pausa/insistencia y requisito-cumplido-por-alternativa.
- `message-orchestration`: el cierre no repite recordatorios cuando el requisito ya está cumplido.

## Impact

- **Código**: `app/knowledge/current_turn.py` (respuestas de funnel, alternativas, cierre), `app/orchestrators/knowledge_orchestrator.py` (rama de negativa/lateral con LLM, guardia de insistencia), `app/tasks_chatwoot.py` (pausa/supresión de respuesta), nuevo detector de ruego, `app/lead_memory` (contador de insistencia + timestamp de pausa).
- **Estado**: nuevo estado por lead: `insistence_count`, `paused_until` (1h). Preserva el avance del perfil durante la pausa.
- **Riesgo**: medio — toca la generación de respuestas del funnel (voz de Mundo) y añade supresión de respuesta (cuidar no dejar mudo un caso legítimo). Mitigación: reset ante documento válido, pausa acotada a 1h, y el ruego se detecta con LLM (no regex frágil).
