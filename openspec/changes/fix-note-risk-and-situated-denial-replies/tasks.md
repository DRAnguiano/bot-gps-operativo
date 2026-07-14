# Tasks — fix-note-risk-and-situated-denial-replies

## 1. Nota IA: riesgo del turno, sin línea redundante (D1 + D2)

- [x] 1.1 En `chatwoot_note_sync.py`: eliminar la línea "⚠️ Riesgo: Alto" del bloque de
      nota de riesgo (4.6).
- [x] 1.2 Decidir el tipo de nota de riesgo por la señal del TURNO actual (risk_level del
      result del orquestador), no por `lead.get("risk_level")` pegado; el label
      `riesgo_alto` de la conversación puede conservarse como marca histórica.
- [x] 1.3 Tests: turno con riesgo alto → nota de riesgo sin línea "Riesgo: Alto"; turno
      posterior con riesgo bajo del mismo lead (lead con risk histórico high) → nota de
      perfilamiento normal.

## 2. Clasificador: coloquialismos no son admisión (D3)

- [x] 2.1 Añadir contraejemplos coloquiales al prompt del clasificador multi-intent
      (caso vivo "todo el show pa k vea que si se arma" + "deme chance" / "está la
      onda"): `is_admission` exige referencia real a sustancias/alcohol/seguridad.
- [x] 2.2 Test estructural: el prompt contiene los contraejemplos y la regla; la
      admisión real (ejemplo existente) permanece en el prompt.

## 3. Vigencias con dígitos (D4)

- [x] 3.1 Canonicalización determinista en el chokepoint de persistencia de facts:
      números en palabras (uno–doce) → dígitos, SOLO dentro del patrón de duración
      ("N año(s)/mes(es)/semana(s)/día(s)") en claves `*.expiration_text`.
- [x] 3.2 Tests: "dos años" → "2 años"; "vence en un mes" → "vence en 1 mes"; fecha
      "31 de diciembre de 2027" intacta; "vencido" intacto.

## 4. Acuse de denegación situado, sin apilamiento (D5)

- [x] 4.1 Rutar los acuses predefinidos de denegación/postergación por
      `_generate_situated_reply` con instrucción situada (mensaje del candidato,
      qué falta, voz usted singular, sin promesas) y el texto actual como fallback:
      deflection de requires_human (knowledge_orchestrator.py:271) y plantillas
      "lo anotamos" (~1107/1112).
- [x] 4.2 Dedupe en el join de composición: nunca dos acuses concatenados; la pregunta
      pendiente aparece a lo más una vez por respuesta (si el acuse generado ya la
      contiene, no se re-adjunta la literal).
- [x] 4.3 Tests: denegación con circunstancia → un solo acuse + una sola pregunta;
      generación falla → fallback enlatado + pregunta, una vez cada uno; el caso vivo
      de tres fragmentos apilados (4302) no puede reproducirse (estructural del join).

## 5. Verificación y despliegue

- [x] 5.1 Suite completa en verde (`-m "not external_llm"`): 982 passed, 63 deselected (2026-07-13).
- [ ] 5.2 Commit + build + force-recreate + push; verificar el código nuevo en la
      imagen corriendo.
- [ ] 5.3 Verificación en vivo (WhatsApp): funnel con "se arma"/coloquialismos → sin
      nota de riesgo; vigencia dicha en palabras → resumen y nota con dígitos;
      denegación de documento → un acuse natural + una pregunta, sin fragmentos.
