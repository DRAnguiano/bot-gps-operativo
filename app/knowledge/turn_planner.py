"""Funnel state planner + auditoría por turno del pipeline multi-intent
(Fase 3, sección 8).

Integra las etapas puras ya construidas en un único estado de turno y su traza
de auditoría (spec `multi-intent-pipeline` · "Funnel state planner" / "Auditoría
por turno"):

    memory_guard (6)      → forbidden_questions + reclamo de memoria
    fact_corrections (7)  → estados de fact, correcciones, pendientes, conflictos
    funnel de 6 (orq.)    → completed_fields / missing_fields / next_question

El sistema FIJA `next_question` (la siguiente del funnel de 6 que no esté
completa ni prohibida); el LLM (70B) solo la redacta — NO elige campo (8.2). La
pregunta emitida lleva sus `asked_field_keys` canónicas para que el camino vivo
las persista por el MISMO mecanismo de metadata que ya consume
`lead_memory/last_asked_field.py` (8.7), sin duplicar reader ni inventar otro.

PURO: no lee/escribe Postgres ni llama al LLM. Recibe ``facts_before`` (snapshot
de lead_memory) y los answers del turno; la Fase 4 (cutover) provee los facts
desde Postgres y persiste `facts_after` + la traza.
"""
from __future__ import annotations

from typing import Any

from app.knowledge.fact_corrections import resolve_facts
from app.knowledge.memory_guard import apply_memory_guard
from app.knowledge.intent_orchestrator import FUNNEL_STEPS

# Campos capturados que NO gatean profile_ready ni entran al funnel de 6 (8.4b).
# availability es ruido conversacional para el gate (esquema v1); se registra
# para la nota/labels pero no se pregunta como parte del perfil núcleo. Nombre
# canónico vivo `candidate.availability_status` (el que ya consume calculate_candidate_labels).
NON_CORE_FIELDS = frozenset({"candidate.availability_status"})

# Claves canónicas que el funnel "pregunta" por cada paso. Mismo espacio canónico
# que `last_asked_field.read_*` y `guard_asked_field`; se persisten en
# external_metadata.asked_field_keys (mecanismo reutilizado, no duplicado).
ASKED_FIELD_KEYS: dict[str, list[str]] = {
    "candidate.name":               ["candidate.name"],
    "candidate.city":               ["candidate.city"],
    "candidate.age":                ["candidate.age"],
    "experience.vehicle_type":      ["experience.vehicle_type"],
    "license":                      ["license.type", "license.status"],
    "medical.apto_expiration_text": ["medical.apto_expiration_text"],
    "experience.years":             ["experience.years"],
    "documents.proof":              ["documents.proof"],
}

_CONFIRMATION_QUESTION = (
    "Para no equivocarnos, ¿me confirma cuál es el dato correcto?"
)


def _funnel_split(
    facts: dict[str, Any], forbidden: set[str]
) -> tuple[list[str], list[str], str | None]:
    """completed_fields, missing_fields y el primer campo faltante (next).

    Un campo prohibido (ya respondido / reclamado) cuenta como completado y NO se
    pregunta. El orden del funnel se conserva (prioridad de `next_question`).
    """
    completed: list[str] = []
    missing: list[str] = []
    for step in FUNNEL_STEPS:
        field = step["field"]
        if field in forbidden or step["complete"](facts):
            completed.append(field)
        else:
            missing.append(field)
    next_field = missing[0] if missing else None
    return completed, missing, next_field


def plan_turn(
    facts_before: dict[str, Any] | None,
    answers: list[dict[str, Any]] | None,
    message: str,
    *,
    turn_id: str | None = None,
    enriched: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Estado del funnel + traza de auditoría de un turno. Función pura.

    ``answers`` son los answers persistibles del turno (salida del enricher).
    Devuelve la traza completa del spec "Auditoría por turno":
      facts_before, candidate_corrections, facts_pending_confirmation,
      facts_after, completed_fields, missing_fields, forbidden_questions,
      next_question (+ next_question_field, asked_field_keys) y
      confirmation_question.
    """
    facts_before = dict(facts_before or {})
    answers = list(answers or [])
    enriched = enriched or {"answers_to_persist": answers}

    # 1. memory_guard sobre la memoria PREVIA (forbidden + reclamo de memoria).
    mg = apply_memory_guard(enriched, message, facts_before)
    forbidden = list(mg["forbidden_questions"])

    # 2. Resolver answers contra el estado previo (estados/correcciones/conflictos).
    res = resolve_facts(answers, facts_before, turn_id=turn_id)

    # 3. facts_after: solo los estados que SÍ se aplican (confirmed/inferred/corrected).
    #    needs_confirmation y conflict NO sobrescriben hasta resolverse.
    facts_after = dict(facts_before)
    for f in res["facts_to_apply"]:
        facts_after[f["field"]] = f["value"]

    # 4. Funnel sobre facts_after (los no-núcleo no participan del gate).
    completed, missing, next_field = _funnel_split(facts_after, set(forbidden))
    next_question = None
    asked_field_keys: list[str] = []
    if next_field is not None:
        step = next(s for s in FUNNEL_STEPS if s["field"] == next_field)
        next_question = step["question"]
        asked_field_keys = list(ASKED_FIELD_KEYS.get(next_field, []))

    # 5. confirmation_question: si hay pendientes/conflictos/reclamo en conflicto.
    needs_confirm = (
        res["facts_pending_confirmation"]
        or res["conflicts"]
        or (mg["memory_claim"] and mg["memory_claim"]["resolution"] == "conflict")
    )
    confirmation_question = _CONFIRMATION_QUESTION if needs_confirm else None

    return {
        "facts_before": facts_before,
        "facts_after": facts_after,
        "completed_fields": completed,
        "missing_fields": missing,
        "forbidden_questions": forbidden,
        "next_question_field": next_field,
        "next_question": next_question,
        "asked_field_keys": asked_field_keys,
        "candidate_corrections": res["corrections"],
        "facts_pending_confirmation": res["facts_pending_confirmation"],
        "conflicts": res["conflicts"],
        "confirmation_question": confirmation_question,
        "memory_claim": mg["memory_claim"],
        "profile_ready": next_field is None,
    }
