> Orden: fixes de bajo riesgo primero (redundancia, "años años"), luego respuestas
> LLM naturales, luego la guardia de insistencia (la más novedosa). Cada bloque con test.

## 1. Fixes de bajo riesgo (verificados en conv 160)

- [x] 1.1 Cierre sin redundancia: `_profile_complete_closing` más ligero (sin "nos comunicaremos siempre que sigas interesado" ni recordatorio pesado). ADEMÁS se quitó TODO el eco de datos del funnel (3 rutas: guard `build_current_turn_ack`, ROUTE1, orquestador `_build_profile_ack_reply`) → conector variado + siguiente pregunta; el saludo con nombre se conserva.
- [x] 1.2 Fix "20 anos años" — subsumido: el eco de años se eliminó por completo.
- [x] 1.3 Tests: conector variado + pregunta sin eco (verificado en vivo "Gracias, Juan. ¿En qué ciudad…?").

## 2. Alternativas por requisito (D3)

- [x] 2.1 Comprobante laboral cartas↔IMSS: ya funcionaba vía `residency_document_question` (local ofrece IMSS↔cartas; foráneo cartas) — verificado determinista.
- [x] 2.2 Licencia/apto no vigente → comprobante de pago: `RENEWAL_PROOF_QUESTION/REPLY` re-redactadas ("comprobante de pago de su renovación o trámite", válido para vencido y por-vencer); `_expiry_within_three_months` ahora detecta "venció/se venció"; nudge del orquestador replica el check (alineado con el guard).
- [x] 2.3 Tests: vencida→comprobante; +comprobante SI→continúa; NO→cierre suave; vigente→apto (sin regresión); apto vencido→comprobante. Verificado determinista + smoke en vivo.

## 3. Respuestas naturales por LLM (D1)

- [x] 3.1 `_build_natural_reencauce` (persona Mundo): acuse con tacto + alternativa conocida si aplica + re-encauce; short-circuit del nudge; dato pendiente se preserva. Hook en el `else` de ROUTE1 (orquestador).
- [x] 3.2 Detección vía `resolve_route1` reason ∈ {negation, no_number, needs_clarification, ambiguous} + NO `has_business_question` (esa la maneja el multi-intent).
- [x] 3.3 Guardrails: prompt "no inventes políticas/cifras"; alternativas solo las conocidas (Bloque 2); "nunca uses 'caduca'" + `_enforce_vigencia_lexicon`; ROUTE1 no confirma → campo NO se marca respondido.
- [x] 3.4 Tests verificados: "experiencia con videos de tiktok"→re-encauce natural, years NO persiste; "no tengo cartas"→empático+alternativa; "llevo 20 años"→confirma normal (sin regresión); business-question mid-funnel→multi-intent (no reencauce).
  - Nota de cobertura: absurdo/lateral y negativa-sin-fact → reencauce LLM. Negativa donde el extractor sí fija un fact (p. ej. `documents.proof=ninguno`) la resuelve el GUARD ofreciendo la alternativa (Bloque 2) — resultado correcto, no LLM-flowery. Full-natural para ese caso queda como refinamiento (o lo cubre la guardia de insistencia B4).

## 4. Guardia de ruego/insistencia + pausa 1h (D4/D5)

- [x] 4.1 Detección: reusa el disparo del reencauce (ROUTE1 no-confirmado + NO `has_business_question`) — cubre ruego/tontería/negativa. El detector LLM dedicado de "ruego" no fue necesario: cualquier no-respuesta sostenida cuenta (las dudas legítimas ya se excluyen por business-question).
- [x] 4.2 Estado por lead en `rh_lead_facts_v2` (grupo `funnel`): `insistence_count`, `paused_until`. Módulo `app/knowledge/insistence_guard.py` (degradación segura).
- [x] 4.3 Insistencias 1..5 → respuesta empática (Bloque 3); reset (`reset_insistence`) al confirmar dato válido (ROUTE1). Dudas legítimas NO cuentan (excluidas por `has_business_question`).
- [x] 4.4 5ª insistencia → `_build_natural_reencauce(final=True)` (cierre empático sin re-preguntar) + `set_pause` (now+1h). El worker `tasks_chatwoot` corta ANTES de la extracción si `is_paused` → sin respuesta y SIN gastar LLM; avance preservado en facts.
- [x] 4.5 Reanudar: pasada la hora, `is_paused=False` → el siguiente mensaje se procesa normal.
- [x] 4.6 Tests verificados: 5 insistencias→count 1..5, 5ª pausa+mensaje final empático; reset por "llevo 20 años"→0; expiración de pausa→reanuda; módulo determinista (read/write/pause/reset).
  - Pendiente menor: label `insistencia` al pausar → va en Bloque 5.

## 4b. Guardia anti-spam (D7, agnóstica de contenido)

- [ ] 4b.1 Umbral por lead: N mensajes en T segundos (config) → coalescer en un solo turno; descartar duplicados idénticos.
- [ ] 4b.2 NO generar una respuesta LLM por cada mensaje de una ráfaga (evita 429/latencia).
- [ ] 4b.3 Flood sostenido → pausa temporal (reusa mecanismo de D4) + label opcional.
- [ ] 4b.4 Tests: 8 msgs/15s → 1 turno; duplicados descartados; flood → pausa.

## 5. Labels nuevos + derivaciones

- [ ] 5.1 Añadir `insistencia` y `descartado_edad` a `OFFICIAL_LABELS` + display (usuario los crea en Chatwoot en paralelo).
- [ ] 5.2 Aplicar `insistencia` al entrar en pausa; `descartado_edad` en el descarte por edad (hoy cierra sin label).
- [ ] 5.3 Requisitos duros → derivar (`requiere_agente`/`requiere_revision_ch`), B1 → `considerar_operador_b1`; NO entran a la guardia de insistencia.

## 6. Validación

- [ ] 6.1 `openspec validate empathetic-funnel-and-insistence-guard` sin errores.
- [ ] 6.2 Resolver open questions del design con el usuario antes de implementar el bloque 4.
- [ ] 6.3 Suite en verde en contenedor; prueba en prod del flujo completo (negativa→alternativa→ruego→pausa).
