## Why

El modelo de generación (`qwen/qwen3-32b`) es un modelo *reasoning*: emite un bloque `<think>…</think>` antes de responder. Cuando ese razonamiento excede `GROQ_MAX_TOKENS` (500), la respuesta se **trunca dentro del pensamiento** y llega **vacía o como `<think>` crudo** al candidato — se observó perdiendo respuestas de negocio en mensajes compuestos (la multi-intención detecta bien la pregunta, pero qwen no alcanza a contestarla). Medición: con `/no_think` qwen responde directo en **41 tokens / 0.4s** (vs 313 tokens / 0.9s razonando, con riesgo de truncado). El razonamiento no aporta a nuestras tareas (respuestas ancladas en contexto RAG o comentarios friendly cortos) y solo consume TPD y arriesga truncado.

## What Changes

- **Desactivar el modo reasoning de qwen en generación** mediante el interruptor documentado `/no_think`, aplicado de forma **centralizada** en la ruta de llamada al LLM de respuesta, **condicionado al modelo** (solo cuando el generador es un modelo qwen reasoning; sin efecto en 70b u otros). Resultado: respuestas directas, sin truncado, menos tokens, más rápidas.
- **Enrutar la respuesta embebida multi-intención por el limpiador unificado** (`_generate_rag_answer` / `_resolve_embedded_question`) para que cualquier artefacto residual (`<think></think>` vacío, `> `) se limpie igual que el resto de rutas.

## Capabilities

### New Capabilities
- (Ninguna)

### Modified Capabilities
- `message-orchestration`: las respuestas generadas por el LLM son directas y completas (sin bloques de razonamiento ni respuestas truncadas); la respuesta a la pregunta embebida de un mensaje compuesto se genera y limpia de forma consistente.

## Impact

- **Código afectado**: `app/indexer.py` (ruta de llamada de generación — `call_groq_llm`/`call_llm`/`call_groq_with_system`: inyección condicional de `/no_think` para modelos qwen), `app/orchestrators/knowledge_orchestrator.py` (`_generate_rag_answer` / respuesta embebida pasa por `_clean_reply`).
- **Efecto**: se recupera la respuesta de negocio en mensajes compuestos (cabo multi-intent #3); se elimina el riesgo de `<think>` truncado en friendly/RAG; ~8× menos tokens de salida por respuesta → más margen de TPD.
- **Riesgo**: bajo; `/no_think` es un no-op para modelos no-qwen (condicionado). Las respuestas siguen ancladas en contexto (fidelidad probada).
- **No cierra el cabo #2** (vocativo en mensajes compuestos) — ese va en su propio cambio.
