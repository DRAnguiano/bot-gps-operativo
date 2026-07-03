> Orden: fixes de bajo riesgo primero (redundancia, "años años"), luego respuestas
> LLM naturales, luego la guardia de insistencia (la más novedosa). Cada bloque con test.

## 1. Fixes de bajo riesgo (verificados en conv 160)

- [ ] 1.1 Cierre sin redundancia: cuando el comprobante laboral ya está cumplido (cartas O IMSS), acuse específico y NO emitir el recordatorio genérico.
- [ ] 1.2 Fix "20 anos años" — normalizar el ack de experiencia para no duplicar "años".
- [ ] 1.3 Tests: cartas→"con cartas es suficiente" (sin recordatorio); ack de años sin duplicar.

## 2. Alternativas por requisito (D3)

- [ ] 2.1 Comprobante laboral cartas↔IMSS: si falta una, ofrecer la otra (local ZM Laguna).
- [ ] 2.2 Licencia/apto no vigente → aceptar comprobante de pago de renovación/trámite.
- [ ] 2.3 Tests: sin IMSS→ofrece cartas y viceversa; apto no vigente→acepta comprobante de pago.

## 3. Respuestas naturales por LLM (D1)

- [ ] 3.1 Rama de negativa/lateral/absurda: generar reply con la persona de Mundo (acuse + política/alternativa + re-encauce), preservando el dato pendiente; aplica a todas las preguntas del funnel.
- [ ] 3.2 Detección de "no es valor válido para el dato pedido" (reusar señales del extractor).
- [ ] 3.3 Guardrails: no inventar política; mantener vigencia-léxico; no marcar el dato como respondido.
- [ ] 3.4 Tests: "experiencia con videos de tiktok"→responde natural + re-pide; negativa→empático + alternativa.

## 4. Guardia de ruego/insistencia + pausa 1h (D4/D5)

- [ ] 4.1 Detector de ruego (LLM): familia/necesidad, apiádese, trabajo gratis, "lo consigo cuando me paguen", fotos irrelevantes.
- [ ] 4.2 Estado por lead: `insistence_count`, `paused_until` (V2); disparo al "no tengo requisito" sin alternativa.
- [ ] 4.3 Insistencias 1..5 → respuesta empática LLM; reset si aporta dato válido.
- [ ] 4.4 5ª insistencia → mensaje empático final + `paused_until=now+1h`; `delivery_policy=suppress` mientras dure; preservar avance.
- [ ] 4.5 Reanudar tras 1h desde donde quedó.
- [ ] 4.6 Tests: 5 ruegos→pausa; reset por dato válido; no responde durante la hora; reanuda después.

## 5. Nota/labels (opcional según open questions)

- [ ] 5.1 (Si se decide) label `pausado_por_insistencia` para Capital Humano; reflejar requisito-cumplido-por-alternativa en la nota.

## 6. Validación

- [ ] 6.1 `openspec validate empathetic-funnel-and-insistence-guard` sin errores.
- [ ] 6.2 Resolver open questions del design con el usuario antes de implementar el bloque 4.
- [ ] 6.3 Suite en verde en contenedor; prueba en prod del flujo completo (negativa→alternativa→ruego→pausa).
