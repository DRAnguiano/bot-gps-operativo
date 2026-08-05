## 1. Supresión de razonamiento condicionada al modelo

- [x] 1.1 Helper `_reasoning_suppression_suffix(model)` en `app/indexer.py`: devuelve `" /no_think"` si el modelo es qwen reasoning (`"qwen" in model.lower()`), `""` en caso contrario.
- [x] 1.2 Inyectar el sufijo en la ruta de generación (`call_groq_llm` / `call_llm` / `call_groq_with_system`) sobre el system message o el prompt, una sola vez (idempotente), usando `GROQ_MODEL` activo.
- [x] 1.3 Verificar que NO se inyecta en `call_groq_json` (extracción/clasificación en 70b), solo en generación de prosa.

## 2. Respuesta embebida por el cleaner

- [x] 2.1 En `knowledge_orchestrator._generate_rag_answer` (o donde `_resolve_embedded_question` arma el `answer`), pasar la respuesta por `clean_reply` antes de devolverla.

## 3. Pruebas

- [x] 3.1 Test: con `GROQ_MODEL` qwen, el suffix es `" /no_think"`; con 70b/otro, `""`.
- [x] 3.2 Cubierto: `_resolve_embedded_question` ahora pasa por `clean_reply` (probado en `tests/test_reply_cleaner.py`).
- [x] 3.3 Verificado: `/no_think` produce respuesta limpia sin `<think>` (turno friendly/RAG). El "compuesto contesta el pago" resultó ser un gap de routing MODEL-AGNOSTIC (qwen y 70b fallan idéntico) → se cierra en contrato aparte.

## 4. Validación y verificación

- [x] 4.1 `openspec validate qwen-disable-reasoning` sin errores; suite en verde en contenedor.
- [ ] 4.2 Verificación en vivo (número nuevo): mensaje compuesto (dato + "cuánto pagan") → contesta el pago y avanza el funnel, sin artefactos; confirmar menor latencia.
