## Context

El acuse del turno lo arma `build_current_turn_ack` (`current_turn.py`); la siguiente pregunta del funnel viene de `_next_funnel_question_or_none` en el mismo módulo. La voz del LLM de respuesta la fija `_llm_system_message` (`indexer.py`). El nombre del candidato vive en `candidate.name` (facts). El reto del vocativo es que el orquestador **persiste** el nombre antes de que el guard arme el acuse, por lo que "nombre nuevo de este turno" NO puede detectarse contra los facts ya mergeados/recargados — debe evaluarse contra el snapshot PRE-turno.

## Goals / Non-Goals

**Goals:**
- Acuse cálido con nombre de pila la primera vez que se conoce el nombre, una sola vez.
- Pregunta de unidad natural, sin repetir "full o sencillo".
- Mundo nunca se presenta como "Capital Humano" al candidato.

**Non-Goals:**
- NO cambiar el orden ni los campos del funnel.
- NO tocar las notas internas "Para Capital Humano" (son para el equipo).
- NO alterar extracción, persistencia, enrutamiento ni multi-intención.

## Decisions

**D1 — `name_just_learned` calculado pre-turno.** El caller (worker) calcula `name_just_learned = bool(current_turn_facts.candidate.name) and not known_facts.candidate.name`, donde `known_facts` es el snapshot PRE-turno (antes de que el orquestador persista). Se pasa como parámetro a `build_current_turn_ack`. *Alternativa descartada*: detectar "nombre fresco" dentro del ack contra `pre_current_facts` — falla porque el orquestador ya persistió el nombre, dejando ese set vacío.

**D2 — Vocativo de corto-circuito.** Cuando `name_just_learned` y hay nombre de pila, el acuse es ÚNICAMENTE "Gracias, <nombre>." + la siguiente pregunta del funnel; no se enumeran los demás datos del mismo turno (decisión de producto: el saludo personal manda ese turno). `first_name(facts)` deriva el primer token capitalizado; vacío → se omite el vocativo.

**D3 — Copy de unidad sin redundancia.** Texto fijo en `_next_funnel_question_or_none` para la rama sin licencia conocida: "Le comento, actualmente tenemos vacantes para operador de tracto full y de sencillo. ¿En cuál tiene experiencia?". Mantiene registro de "usted".

**D4 — Persona en `_llm_system_message`.** Instruir explícitamente: "Eres Mundo, del equipo de reclutamiento de Transmontes. Hablas como parte del equipo, nunca como un tercero; nunca te presentes como 'Capital Humano'." Refuerza la regla ya presente en `persona_config` pero que se filtraba por el system message del generador.

## Risks / Trade-offs

- **El vocativo depende de que `candidate.name` esté en los facts del turno** → Mitigación: si no está, `first_name` devuelve vacío y se omite sin fallar; comportamiento degradado a "Gracias, lo dejo registrado.".
- **Cambiar el copy puede romper tests que fijaban el texto anterior** → Mitigación: actualizar los tests de acuse/funnel al nuevo copy.
- **Repetir el vocativo en cada turno sonaría robótico** → Mitigación: `name_just_learned` restringe a la primera vez (D1).

## Migration Plan

1. Añadir el parámetro `name_just_learned` a `build_current_turn_ack` y el corto-circuito del vocativo.
2. Calcular `name_just_learned` en el worker contra `known_facts` pre-turno y pasarlo.
3. Reemplazar el copy de la pregunta de unidad.
4. Ajustar `_llm_system_message`.
5. Tests: vocativo solo la primera vez; copy nuevo; persona sin "Capital Humano".
6. Verificación en vivo y commit.

## Open Questions

- (Ninguna; alcance acotado y código de referencia disponible en el stash.)
