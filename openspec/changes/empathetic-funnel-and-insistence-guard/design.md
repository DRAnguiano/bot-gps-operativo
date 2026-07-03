## Context

El funnel usa mensajes enlatados para acuse y siguiente pregunta. Ante negativas, respuestas laterales o absurdas responde robótico o fuerza la pregunta. No hay alternativas por requisito ni defensa ante ruego. Reglas de negocio confirmadas por el usuario (2026-07-03).

## Decisions

**D1 — Respuestas naturales por LLM en negativas/laterales/absurdas (todas las preguntas del funnel).** Cuando el candidato NO responde el dato pedido con un valor válido (niega, divaga, o dice algo irrelevante), el reply lo genera el **LLM con la persona de Mundo**: acusa con tacto, aporta la política/alternativa si aplica, y **re-encauza** al dato pendiente. NO se fuerza el mensaje enlatado. El dato pendiente se **preserva** (no se marca respondido). Aplica a: licencia, apto, unidad, documentos, experiencia, ciudad. *Alternativa descartada*: banco de mensajes fijos por caso (robótico, no escala).

**D2 — Cierre sin redundancia (requisito cumplido por alternativa).** Comprobante laboral = cartas laborales membretadas **O** semanas cotizadas del IMSS. Si el candidato aporta UNO, el requisito está **cumplido**: acuse específico ("con las cartas laborales es suficiente, continuamos") y NO se emite el recordatorio genérico de "sube tus documentos / nos comunicaremos". El recordatorio de documentos solo aparece cuando realmente faltan.

**D3 — Alternativas por requisito.**
| Requisito | Aceptado | Alternativa si falta | ¿Obligatorio? |
|---|---|---|---|
| Comprobante laboral | cartas membretadas O semanas IMSS | ofrecer la otra (local ZM Laguna) | sí (una de las dos) |
| Licencia federal vigente | licencia vigente | **comprobante de pago** (renovación/trámite) | sí |
| Apto médico vigente | apto vigente | **comprobante de pago** (renovación/trámite) | sí |
| Ciudad, unidad, experiencia | el dato | — | sí (sin alternativa) |

Si no tiene ni el documento ni la alternativa → entra la guardia de insistencia (D4).

**D4 — Guardia de ruego/insistencia + pausa 1h.**
- **Disparo**: el candidato dice que NO tiene un documento/requisito y NO aporta alternativa.
- **Contador `insistence_count`** por lead: incrementa con cada mensaje del candidato que **insiste/ruega** sin aportar dato válido. Señales de ruego (detectadas por LLM, no regex): apelar a familia/necesidad, pedir que se le apiaden, ofrecer trabajar gratis, "lo consigo cuando me paguen", enviar fotos irrelevantes (camiones, hijos), etc.
- **Durante insistencias 1..5**: el LLM responde **empático** manteniendo la política ("entiendo su situación; en cuanto tenga sus documentos vigentes continuamos con gusto").
- **Reset**: si en cualquier momento aporta un **documento/alternativa válida** → `insistence_count=0` y sigue el funnel normal.
- **Tras la 5ª insistencia** sin dato válido → **un** mensaje empático final + `paused_until = now + 1h`. Mientras `paused_until` esté vigente, el bot **NO responde** al candidato (`delivery_policy=suppress`), preservando todo el avance del perfil. Pasada la hora, se reanuda al siguiente mensaje desde donde quedó.

**D5 — Persistencia de estado de pausa.** `insistence_count` y `paused_until` viven en el estado del lead (V2). La pausa es por lead, no global. El avance del perfil NO se pierde durante la pausa.

**D6 — Fix menor.** El ack de experiencia duplica "años" ("20 anos años"): normalizar para no repetir la unidad.

## Risks / Trade-offs

- **Silenciar un caso legítimo** (falso positivo de ruego) → Mitigación: el reset por dato válido es inmediato; la pausa es corta (1h); el ruego lo detecta el LLM con contexto, no un regex.
- **Respuestas LLM en el funnel** (voz/consistencia) → reusar la persona de Mundo + guardrails de vigencia; validar que no invente política.
- **Costo LLM extra** en negativas → acotado (solo cuando no hay valor válido); no en el camino feliz.

## Decisiones resueltas (usuario, 2026-07-03)

1. **Conteo de las 5 = SOLO insistencias/tonterías.** Solo cuentan mensajes de ruego o tonterías **no relacionadas con el perfilamiento**. Si el candidato pregunta cosas legítimas (dudas de pago, rutas, etc.) → NO cuenta y se responde normal (no avanza el contador ni pausa).
2. **Durante la pausa: solo silencio** (tras el mensaje empático final).
3. **Al reanudar tras 1h: el bot ESPERA** a que el candidato se vuelva a comunicar (sin mensaje proactivo).
4. **Documentos = etapa contratada aparte (2 fases):** (a) perfilamiento por TEXTO (esta propuesta), (b) VISIÓN entiende los documentos enviados (liga con #17). En la fase visión: la Nota IA lista los documentos (INE, Licencia, …) y al subir uno el bot acusa específico ("gracias por subir tu INE, ahora falta la licencia…"). El **comprobante de pago** (licencia/apto no vigente) se **menciona** en fase texto; su verificación por imagen es fase visión.
5. **Label de pausa = `insistencia`** (el usuario lo añade en Chatwoot; se agrega a `OFFICIAL_LABELS`).
6. **Requisitos duros → derivan a Capital Humano** (no entran a la guardia de insistencia):
   - Operadores de **otras vacantes** → derivar + label (`requiere_agente`/`requiere_revision_ch`).
   - **B1** → igual, derivar + `considerar_operador_b1`.
   - **Edad** fuera de perfil → **descarte directo** con su label (**`descartado_edad`**, NUEVO — hoy cierra sin label).

## Labels nuevos a coordinar
- **`insistencia`** — pausa por ruego. (usuario lo crea en Chatwoot; código lo agrega a `OFFICIAL_LABELS` + display).
- **`descartado_edad`** — descarte por edad (hoy no existe label; la edad solo cierra el stage).
