# Design — fix-same-turn-summary-confirmation-consumption

## Context

Evidencia (conv 177): respuesta entregada = doping respondido + "Todo claro, seguimos adelante." + **resumen completo re-emitido** — inmediatamente después de que el candidato lo confirmó en ese mismo mensaje. En BD `funnel.summary_confirmed=true` quedó bien persistido (`source=summary_confirm_compound`), es decir, el defecto ya no es de persistencia sino de **consumo mismo-turno**: el orquestador compone el nudge con `active_facts` = facts persistidos pre-turno + extracción del turno (`pre_validated_facts`), y ninguno de los dos porta la confirmación — esa la computa `_extract_context_confirmation_facts` (determinista, sobre mensaje + último mensaje del bot) en el worker, después de componer.

`_build_funnel_nudge` ya tiene todo lo necesario: recibe `message`, `lead_memory` (de donde ya lee el último mensaje del bot completo para BUG-2/BUG-3) y `turn_signals`.

## Goals / Non-Goals

**Goals:**

- El turno que confirma el resumen (solo o compuesto con pregunta) compone su respuesta con la confirmación ya aplicada: la parte de funnel avanza al cierre, no re-emite el resumen.

**Non-Goals:**

- No se toca la persistencia (fix anterior, funciona).
- No se cambia el detector de confirmación ni sus reglas de negación/corrección.
- No se rediseña el conector del join ("Todo claro, seguimos adelante." es salida del composer/transición; con el nudge correcto la lectura queda coherente — si el tono molesta después, es ajuste de prompt aparte).

## Decisions

**D1 — Merge de la confirmación dentro de `_build_funnel_nudge`, reutilizando el detector existente.**
Tras construir `active_facts` (persistidos + pre_validated), computar `_extract_context_confirmation_facts(normalize_text(message), <último mensaje del bot completo>, _turn_signals=turn_signals)` y mergear ÚNICAMENTE la clave `funnel.summary_confirmed` si viene en el resultado. Racional: (a) es el mismo detector que gobierna la persistencia — una sola semántica de "qué cuenta como confirmación", imposible que composición y persistencia diverjan; (b) acotar el merge a esa clave evita que inferencias de contexto ajenas (p. ej. `medical.apto_status` desde un "sí" corto) entren al nudge por una vía nueva sin contrato propio. Alternativa rechazada: computar la confirmación en el worker y pasarla como parámetro nuevo — más plumbing por el mismo resultado y una firma más ancha.

**D2 — El último mensaje del bot se toma de `lead_memory` sin truncar.**
`_build_funnel_nudge` ya itera `lead_memory["messages"]` para `_last_bot` (normalizado). El detector recibe el texto del mensaje completo — consistente con el fix de "cola, no cabeza" del change anterior; en lead_memory el mensaje vive completo, no hay truncado que aplicar.

**D3 — Cobertura de ambos caminos de composición.**
El merge vive en `_build_funnel_nudge`, que es el único punto donde se decide "qué pregunta sigue" para los joins de RAG/friendly/profile-ack. Con `funnel.summary_confirmed` en `active_facts`, `next_question_from_missing_facts` devuelve el cierre (`_profile_complete_closing`) — el candidato recibe: respuesta a su pregunta + siguiente paso (documentos). El guard path del worker no necesita cambio: `build_current_turn_ack` ya computa la confirmación por sí mismo con `extract_current_turn_facts`.

## Risks / Trade-offs

- **Falso positivo de confirmación** heredaría del detector existente (mismo riesgo que la persistencia ya asume; las guardas de negación/condicional/reclamo aplican idénticas). No se amplía la superficie semántica.
- **Doble cómputo** del detector (nudge + worker): es regex/clasificación ligera, sin LLM en el camino común (`_llm_summary_affirmation` solo se invoca en frases ambiguas, y su resultado puede divergir entre las dos pasadas en casos límite — aceptado: en el peor caso degrada al comportamiento actual, resumen re-emitido una vez y confirmado al turno siguiente).
- **Cierre emitido dos veces** si el siguiente turno también compone nudge: no — el cierre solo se emite cuando el funnel está completo y confirmado; es idempotente en contenido y el flujo de documentos toma el control después.
