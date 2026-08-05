## Context

La generación de respuestas (friendly, RAG, respuesta embebida) pasa por `call_llm`→`call_groq_llm` (y `call_groq_with_system`) en `app/indexer.py`, con `GROQ_MODEL=qwen/qwen3-32b`. qwen3 es reasoning: antepone `<think>…</think>`. Con `GROQ_MAX_TOKENS=500`, si el razonamiento es largo se trunca y no queda respuesta. qwen3 soporta el interruptor suave `/no_think` en el prompt: emite un `<think></think>` vacío y responde directo (verificado en Groq). El limpiador unificado (`reply_cleaner`) ya elimina `<think></think>` cerrado, así que con `/no_think` la salida llega limpia.

Medición (prompt RAG de pago): normal 313 tok / 0.9s (riesgo truncado); `/no_think` 41 tok / 0.4s, respuesta fiel y concisa.

## Goals / Non-Goals

**Goals:**
- Respuestas de generación directas, sin razonamiento truncado ni artefactos.
- Recuperar la respuesta embebida de mensajes compuestos (que qwen sí conteste).
- Menos tokens/latencia; condicionado al modelo (no romper 70b/otros).

**Non-Goals:**
- NO cambiar el modelo de generación (sigue qwen).
- NO tocar extracción/clasificación (esas van en 70b y no generan prosa).
- NO resolver el vocativo en compuestos (cabo #2, cambio aparte).

## Decisions

**D1 — `/no_think` centralizado y condicionado al modelo.** En la ruta de llamada de generación (`indexer.py`), si el modelo activo es un modelo qwen reasoning (`"qwen" in GROQ_MODEL`), inyectar el interruptor `/no_think` (en el system message o al final del prompt). Un helper `_reasoning_suppression_suffix(model)` devuelve `" /no_think"` para qwen y `""` para el resto. *Alternativa descartada*: subir `GROQ_MAX_TOKENS` — solo enmascara el truncado, gasta tokens en razonamiento que el cleaner descarta y no ayuda al TPD (medido).

**D2 — Respuesta embebida por el cleaner.** `_generate_rag_answer` (o el punto donde `_resolve_embedded_question` arma el `answer`) SHALL pasar por `clean_reply`, igual que `_answer_rag_message`/`_answer_friendly_message`, para que cualquier `<think></think>` vacío o `> ` residual se elimine.

**D3 — Idempotencia y seguridad.** Inyectar `/no_think` una sola vez; no duplicar si ya está. No afecta el contenido salvo suprimir el razonamiento.

## Risks / Trade-offs

- **Menor "profundidad" de respuesta sin razonamiento** → Mitigación: las tareas están ancladas en contexto (RAG) o son comentarios cortos (friendly); la fidelidad se probó intacta y la concisión favorece WhatsApp.
- **Groq/qwen deja de honrar `/no_think` en el futuro** → Mitigación: el cleaner ya elimina `<think></think>`; si volviera a razonar, la salida sigue limpia (peor caso: más tokens, no artefacto).

## Migration Plan

1. Helper `_reasoning_suppression_suffix(model)` + inyección condicional en la ruta de generación.
2. Pasar la respuesta embebida multi-intent por `clean_reply`.
3. Tests: qwen → prompt lleva `/no_think`; no-qwen → sin cambio; respuesta embebida se limpia.
4. Verificación en vivo: mensaje compuesto (dato + "cuánto pagan") → contesta el pago y avanza el funnel, sin `<think>`.

## Open Questions

- (Ninguna; `/no_think` verificado en Groq y el cleaner ya cubre el `<think></think>` vacío.)
