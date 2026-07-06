## 1. Vocativo por nombre de pila

- [x] 1.1 Añadir parámetro `name_just_learned: bool = False` a `build_current_turn_ack` (`current_turn.py`) y el corto-circuito: si `name_just_learned` y hay `first_name(facts)`, devolver "Gracias, <nombre>." + `next_question_from_missing_facts(facts)`, sin los demás confirms.
- [x] 1.2 En el worker (`tasks_chatwoot.py`), calcular `name_just_learned = bool(_current_turn_facts.get("candidate.name")) and not _known_facts.get("candidate.name")` contra el snapshot PRE-turno y pasarlo a `build_current_turn_ack`.
- [x] 1.3 Confirmar que `first_name` vacío → se omite el vocativo sin fallar.

## 2. Copy de unidad sin redundancia

- [x] 2.1 En `_next_funnel_question_or_none` (`current_turn.py`), rama sin licencia conocida: reemplazar el texto por "Le comento, actualmente tenemos vacantes para operador de tracto full y de sencillo. ¿En cuál tiene experiencia?".

## 3. Persona del LLM

- [x] 3.1 En `_llm_system_message` (`indexer.py`): "Eres Mundo, del equipo de reclutamiento de Transmontes. Hablas como parte del equipo, nunca como un tercero; nunca te presentes como 'Capital Humano'."
- [x] 3.2 Verificar que las notas internas "Para Capital Humano" quedan intactas (no son al candidato).
- [x] 3.3 Corregir `ASSISTANT_PUBLIC_INTRO` (env del intro de primer reply): decía "asistente de Capital Humano" y sobreescribía el default correcto del código. Ahora "Hola, soy Mundo, del equipo de reclutamiento de Transmontes." — esta era la fuente real del saludo con "Capital Humano" al candidato.

## 4. Pruebas y verificación

- [x] 4.1 Test: nombre nuevo de turno → acuse "Gracias, <nombre>." + siguiente pregunta; nombre ya conocido → sin vocativo.
- [x] 4.2 Test: copy de unidad nuevo (una sola mención de full/sencillo).
- [x] 4.3 Test: `_llm_system_message` no contiene "asistente de Capital Humano".
- [x] 4.4 Actualizar tests existentes que fijaban el copy anterior del funnel.
- [x] 4.5 `openspec validate` sin errores; tests del cambio 5/5 en verde. NOTA: 3 tests pre-existentes de `test_current_turn_ack.py` fallan por el bug "20 años años" (experience.years extraído con unidad por el extractor 70b) — confirmado idéntico en HEAD puro, fuera de alcance de este cambio; va a su propio fix.
- [ ] 4.6 Verificación en vivo (número nuevo): primer dato del nombre → "Gracias, David"; pregunta de unidad sin redundancia; saludo sin "Capital Humano".
