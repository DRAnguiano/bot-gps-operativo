"""Captura pasiva del campo preguntado por el current_turn guard (Fase B).

Espejo EXACTO de la cascada de ``current_turn.next_question_from_missing_facts``:
decide el campo canónico activo por los **mismos facts faltantes y los mismos
predicados** que el guard usa para elegir su pregunta. NO parsea el texto de la
pregunta. Si el guard pregunta algo mixto (tipo+vigencia de licencia) o advisory
(apto), devuelve ``[]`` (criterio conservador, igual que el funnel nudge).

IMPORTANTE: este módulo duplica los predicados del guard a propósito (espejo
literal). Si ``next_question_from_missing_facts`` cambia su lógica, este helper
DEBE actualizarse en sincronía (lo blinda ``test_guard_asked_field`` con un test
de alineación). Refactor futuro a single source of truth queda documentado y
fuera de este bloque.

Puro: sin BD, sin writes, sin mutar la entrada.
"""
from __future__ import annotations

from typing import Any


def asked_field_keys_for_guard(facts: dict[str, Any]) -> list[str]:
    """Devuelve las asked_field_keys canónicas del campo que el guard preguntaría.

    Mismo orden y predicados que ``next_question_from_missing_facts``:
    - ``candidate.name`` faltante                         → ``["candidate.name"]``
    - ``candidate.city`` faltante                         → ``["candidate.city"]``
    - ``candidate.age`` faltante                          → ``["candidate.age"]``
    - ``experience.vehicle_type`` faltante                → ``["experience.vehicle_type"]``
    - ``license.category`` faltante                       → ``[]`` (tipo+vencimiento)
    - ``license.expiration_text`` faltante                → ``[]`` (vigencia advisory)
    - ``medical.apto_expiration_text`` faltante           → ``[]`` (vigencia advisory)
    - ``experience.years`` faltante                       → ``["experience.years"]``
    - documento laboral faltante                          → ``["documents.proof"]``
    - perfil completo / descarte por edad                 → ``[]``
    """
    if not facts.get("candidate.name"):
        return ["candidate.name"]
    if not facts.get("candidate.city"):
        return ["candidate.city"]
    if not facts.get("candidate.age"):
        return ["candidate.age"]
    try:
        from app.settings import AGE_DISQUALIFICATION_LIMIT
        if int(str(facts.get("candidate.age") or "").strip()) >= AGE_DISQUALIFICATION_LIMIT:
            return []
    except (ValueError, ImportError):
        pass
    if not facts.get("experience.vehicle_type"):
        return ["experience.vehicle_type"]
    # Pregunta MIXTA tipo+vencimiento. Conservador → [].
    if not facts.get("license.category"):
        return []
    # Vigencias/trámite: advisory hasta cutover canónico → [].
    if not facts.get("license.expiration_text"):
        return []
    if not facts.get("medical.apto_expiration_text"):
        return []
    if not facts.get("experience.years"):
        return ["experience.years"]
    if not (
        facts.get("documents.labor_letters")
        or facts.get("documents.labor_letters_status")
        or facts.get("documents.proof")
    ):
        return ["documents.proof"]
    return []
