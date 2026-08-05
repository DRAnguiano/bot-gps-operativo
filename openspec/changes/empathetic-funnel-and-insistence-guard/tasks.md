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

- [x] 4b.1 Ráfagas cortas: ya cubiertas por el debounce (~6s coalesce + dedupe por message_id). Flood sostenido: nuevo módulo `app/knowledge/anti_spam.py` — ventana deslizante Redis por lead (12 turnos/60s, config por env `ANTISPAM_FLOOD_*`).
- [x] 4b.2 Cooldown 300s al exceder el umbral: el worker corta ANTES de la extracción → cero llamadas LLM durante el flood.
- [x] 4b.3 Flood sostenido → cooldown temporal (mismo patrón suppress que D4). Label no necesario: el cooldown es corto (5 min) y auto-expira; la pausa larga con label es la de insistencia.
- [x] 4b.4 Verificado: flood dispara en el turno 13 (>12); cooldown suprime; expira limpio; degradación segura ante error de Redis.

## 5. Labels nuevos + derivaciones

- [x] 5.1 `insistencia` y `descartado_edad` en `OFFICIAL_LABELS` + display; `descartado_edad` también TERMINAL. (Usuario los crea en Chatwoot en paralelo — RECORDATORIO pendiente.)
- [x] 5.2 `calculate_candidate_labels`: pausa activa (`funnel.paused_until` futuro, leído de facts) → `insistencia`; descarte por edad → `["descartado_edad"]` (antes cerraba sin label).
- [x] 5.3 Verificado: B1 ya deriva (`considerar_operador_b1` + `requiere_agente`/`requiere_revision_ch`); edad se descarta ANTES del funnel (no entra a la guardia de insistencia).

## 6. Validación

- [x] 6.1 `openspec validate empathetic-funnel-and-insistence-guard` sin errores.
- [x] 6.2 Open questions resueltas con el usuario (2026-07-03) — ver design "Decisiones resueltas".
- [ ] 6.3 Suite en verde en contenedor; prueba en prod del flujo completo (negativa→alternativa→ruego→pausa). PENDIENTE: correr suite completa + validación en prod real.
