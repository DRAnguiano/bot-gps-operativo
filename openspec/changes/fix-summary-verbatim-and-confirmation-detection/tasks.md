# Tasks — fix-summary-verbatim-and-confirmation-detection

## 1. Resumen verbatim (D1)

- [x] 1.1 En `generate_funnel_transition_reply` (`current_turn.py`): guard estructural al
      inicio — si `question` contiene el encabezado de resumen ("le confirmo sus datos
      registrados") o viñetas de datos ("\n·"), regresar `fallback` sin llamar al LLM.
      → Refinado por feedback del usuario: los marcadores NO son literales duplicados;
      son constantes compartidas SUMMARY_HEADER/SUMMARY_BULLET, fuente única con
      `build_funnel_summary` (cualquier candidato/datos → mismo esqueleto).
- [x] 1.2 Tests en `tests/test_funnel_llm_transitions.py`: pregunta-resumen → fallback
      verbatim y LLM NO invocado (con flag ON); pregunta atómica sigue reformulándose.
      → Resumen construido con el builder REAL sobre 2 juegos de datos distintos +
      regresión de fuente única (header/bullet presentes en la salida del builder).

## 2. Detección de confirmación (D2 + D3)

- [x] 2.1 En `tasks_chatwoot.py` (~línea 393): capturar `last_bot_message` conservando la
      cola — cap defensivo 2000 chars desde el FINAL (`[-2000:]`), no `[:500]`.
- [x] 2.2 Auditar los consumidores de `last_bot_message` que alimentan prompts LLM:
      `extract_turn` ahora acota internamente a la cola (`[-500:]`);
      `build_current_turn_ack` solo hace detección regex → texto completo correcto.
- [x] 2.3 En `current_turn.py`: `_TOPIC_SUMMARY_CONFIRM` ampliado a
      "es correcto|son correctos|confirmo sus datos".
- [x] 2.4 Tests en `tests/test_compound_summary_confirmation.py`: resumen (builder real,
      datos arbitrarios) en la cola de un mensaje >500 chars + afirmación compuesta →
      confirmado; variante plural → confirmado; regresión anclada a la línea de captura
      del worker (head-truncate no reaparece). → 26 passed (sub-suites).

## 3. Higiene del corpus (D4)

- [x] 3.1 En `data/03_seguridad_antidoping.md:54`: eliminada la coletilla "llámenos de
      8:00 a 17:30 hrs para cualquier duda" (la respuesta termina en la política).
      Barrido hecho: los "llámenos" de `02_documentos_requisitos.md` (docs vencidos,
      escuelita) son derivación genuina y se quedan; `00_politicas_generales.md` es la
      regla misma, no una coletilla.
- [x] 3.2 Reindexado (build_index en hr_rag_api, volumen compartido): 4 chunks de
      03_seguridad_antidoping.md, "8:00" ausente en todos (verificado vía get de la
      colección).

## 4. Verificación y despliegue

- [x] 4.1 Suite completa en verde → 965 passed, 63 deselected (958 + 7 nuevos).
- [ ] 4.2 Commit + build + force-recreate + push; verificar el código nuevo en la imagen
      corriendo.
- [ ] 4.3 Verificación en vivo: perfil completo en un mensaje → el resumen llega COMPLETO
      con la lista de datos; responder "sí + pregunta de negocio" → pregunta respondida,
      `funnel.summary_confirmed` en BD y el turno siguiente avanza (no re-emite resumen);
      pregunta de doping mid-funnel → respuesta sin coletilla de horario.
