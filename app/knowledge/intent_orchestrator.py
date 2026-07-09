"""Orquestador de acciones multi-intent (Fase 3).

Toma la clasificación enriquecida (intent_enricher) + los facts conocidos del lead
y produce:
  - recommended_action_order
  - facts_to_persist (listos para que la Fase 4 los escriba)
  - response_text (genera RAG para preguntas + siguiente pregunta del funnel)

Aislado: NO persiste en Postgres ni envía a Chatwoot. Solo planea y genera texto.
La conexión real al flujo es la Fase 4 (detrás de feature flag).

El funnel de 6 preguntas es la fuente única definida en
docs/esquema_perfilamiento_v1.md (§1). Reemplaza la lógica dispersa de
_FUNNEL_STEPS, next_question_from_missing_facts y el SYSTEM_PROMPT.
"""
from __future__ import annotations

from typing import Any

from app.indexer import call_llm
from app.knowledge.context_builder import build_generation_prompt, retrieve_preferred_context
from app.knowledge.current_turn import (
    license_requirement_question,
    residency_document_question,
    vehicle_vacancy_question,
)
from app.knowledge.memory_guard import apply_memory_guard

# ── Funnel de 6 preguntas (esquema v1 §1) ────────────────────────────────────
# Cada paso: la pregunta canónica + función que decide si el campo está completo.

def _has(facts: dict[str, Any], key: str) -> bool:
    return bool(facts.get(key))


def _is_local(facts: dict[str, Any]) -> bool:
    # Fuente única de residencia: catálogo ZM Laguna (sin listas hardcodeadas).
    if facts.get("location.is_local_laguna") == "true":
        return True
    from app.knowledge.geo_utils import is_zm_laguna_canonical, normalize_zm_laguna_city
    city = normalize_zm_laguna_city(facts.get("candidate.city") or "")
    return is_zm_laguna_canonical(city)


def _residency_prompt_note(facts: dict[str, Any] | None) -> str:
    """Nota determinista de residencia para inyectar al prompt RAG/LLM.

    Si hay ciudad o señal `location.is_local_laguna`, entrega la clasificación
    ya resuelta (local/foráneo) desde el catálogo. Si no hay dato, instruye al
    LLM a no afirmar residencia. Evita que el LLM deduzca "foráneo" del nombre
    crudo de una ciudad que sí es local (p. ej. Chávez → Francisco I. Madero).
    """
    facts = facts or {}
    city = (facts.get("candidate.city") or "").strip()
    has_signal = facts.get("location.is_local_laguna") in {"true", "false"} or bool(city)
    if not has_signal:
        return (
            "Residencia del candidato: SIN DETERMINAR. No afirmes si es local o "
            "foráneo, ni qué documentos aplican por residencia."
        )
    estado = "LOCAL de la ZM Laguna (Comarca Lagunera)" if _is_local(facts) else "FORÁNEO"
    ubic = f" (ciudad declarada: {city})" if city else ""
    return f"Residencia del candidato: {estado}{ubic}."


def _vehicle_type_question(facts: dict[str, Any]) -> str:
    return vehicle_vacancy_question(facts)


def _document_question(facts: dict[str, Any]) -> str:
    return residency_document_question(facts)


FUNNEL_STEPS: list[dict[str, Any]] = [
    {
        "field": "candidate.name",
        "question": "¿Me podría decir su nombre y apellido, por favor?",
        "complete": lambda f: _has(f, "candidate.name"),
    },
    {
        "field": "candidate.city",
        "question": "¿Desde qué ciudad o estado nos escribe?",
        "complete": lambda f: _has(f, "candidate.city"),
    },
    {
        "field": "candidate.age",
        "question": "¿Cuántos años tiene?",
        "complete": lambda f: _has(f, "candidate.age"),
    },
    {
        "field": "license",
        "question": "¿Qué tipo de licencia federal tiene y cuándo vence?",
        "complete": lambda f: _has(f, "license.category") and _has(f, "license.expiration_text"),
    },
    {
        "field": "experience.vehicle_type",
        "question": None,  # generated dynamically by next_funnel_question
        "complete": lambda f: _has(f, "experience.vehicle_type"),
    },
    {
        "field": "medical.apto_expiration_text",
        "question": "¿Cuándo vence su apto médico?",
        "complete": lambda f: _has(f, "medical.apto_expiration_text"),
    },
    {
        "field": "experience.years",
        "question": "¿Cuántos años de experiencia tiene como operador?",
        "complete": lambda f: _has(f, "experience.years"),
    },
    {
        "field": "documents.proof",
        "question": None,  # generated dynamically by next_funnel_question
        "complete": lambda f: (
            f.get("documents.proof") in {"cartas", "semanas_imss"}
            or f.get("documents.labor_letters_status") in {"available", "sí", "si"}
        ),
    },
]


def next_funnel_question(
    facts: dict[str, Any],
    forbidden_questions: list[str] | None = None,
) -> str | None:
    """Devuelve la siguiente pregunta del funnel, o None si el núcleo está completo.

    ``forbidden_questions``: campos que NO deben preguntarse aunque el predicado
    los vea incompletos (dato ya confirmado en turno previo). Se saltan sin emitir.
    """
    forbidden = set(forbidden_questions or ())
    for step in FUNNEL_STEPS:
        if step["field"] in forbidden:
            continue
        if step["complete"](facts):
            continue
        # dynamic questions (2.4 / 2.5)
        if step["field"] == "experience.vehicle_type":
            return _vehicle_type_question(facts)
        if step["field"] == "license":
            return license_requirement_question(facts)
        if step["field"] == "documents.proof":
            return _document_question(facts)
        return step["question"]
    return None


def core_completeness(facts: dict[str, Any]) -> int:
    """Cuántos de los 6 campos núcleo están completos (para el status del lead)."""
    return sum(1 for step in FUNNEL_STEPS if step["complete"](facts))


# ── Respuestas a signals (voz de equipo, esquema v1 §6) ──────────────────────

_SIGNAL_REPLIES: dict[str, str] = {
    "greeting": "Hola, soy Mundo del equipo de reclutamiento de Transmontes. "
                "Con gusto le platico de la vacante de operador de tracto full o sencillo. "
                "Le haré unas preguntas breves para conocer su perfil; si antes tiene dudas "
                "de pago, rutas o requisitos, pregúnteme con confianza. Al completar sus "
                "datos podrá subir su documentación y lo canalizamos con un agente de "
                "reclutamiento. ¿En qué ciudad se encuentra?",
    "on_route": "10-4, sin problema. Cuando tenga oportunidad seguimos por aquí.",
    "farewell": "Gracias, que tenga buen día y maneje con cuidado. Aquí seguimos cuando guste retomar.",
    "dropoff": "Gracias por avisarnos. Si más adelante quiere retomar, con gusto lo apoyamos.",
    "meta_confusion": "Claro, dígame qué parte no quedó clara y la repasamos.",
    "reingreso": "Los reingresos los revisamos directamente aquí. ¿Me da su nombre completo y el motivo por el que salió?",
    "out_of_scope": "Por este medio manejamos solo las vacantes de operador sencillo y full. Para otra área, le paso con un compañero.",
    "complaint": "Una disculpa por la demora, no debió pasar. ¿Sigue interesado en la vacante? Le damos seguimiento de inmediato.",
}

_HANDOFF_REPLY = "Ese punto lo revisa nuestro equipo directamente. Lo dejo anotado para que le den seguimiento."

# Reclamo de memoria (memory_guard, tarea 6.3). El fact previo coincide con lo
# que el candidato dice haber dicho: se reafirma sin reescribir ni repreguntar.
_MEMORY_REAFFIRM_REPLY = "Sí, ya lo tengo anotado, gracias por confirmarlo."
# El fact previo difiere del valor reclamado: no se sobrescribe; se pide
# confirmación neutral para resolver el conflicto.
_MEMORY_CONFLICT_REPLY = (
    "Tengo registrado algo distinto en ese dato. Para no equivocarnos, "
    "¿me confirma cuál es el correcto?"
)

# Signals que NO deben continuar con la pregunta del funnel.
# greeting incluido: la presentación ya invita ("¿le interesa la vacante?"); no
# encimar una pregunta de perfil en el primer contacto.
_NO_FUNNEL_SIGNALS = {"greeting", "on_route", "farewell", "dropoff", "out_of_scope", "complaint", "reingreso"}


def _generate_rag_answer(
    question: dict[str, Any], message: str, facts: dict[str, Any] | None = None
) -> tuple[str, bool]:
    """Genera la respuesta a una pregunta usando el RAG existente.

    Devuelve (texto, derive_to_human). Fase 5.2, fail-closed: para intents con
    `requires_human_if_no_authorized_source` (pay_question), si no hay chunks de
    la fuente autorizada — o el LLM no genera respuesta teniéndola — el bot NO
    inventa: deriva a Capital Humano con el handoff genérico. Los demás intents
    RAG conservan el fallback telefónico.
    """
    from app.knowledge.business_hours import is_business_hours

    en_horario = is_business_hours()
    conditional = bool(question.get("requires_human_if_no_authorized_source"))
    context = retrieve_preferred_context(
        message, preferred_sources=question.get("preferred_sources") or []
    )
    if not context.get("items"):
        if conditional:
            return _HANDOFF_REPLY, True
        # Política de horario: en horario el equipo confirma (no se pide llamar);
        # fuera de horario se refiere a llamar a oficina.
        if en_horario:
            return ("Ese dato lo confirma nuestro equipo; lo dejo anotado para que se lo verifiquen.", False)
        return ("Para ese dato le recomiendo llamarnos de 8:00 a 17:30 hrs y se lo confirmamos.", False)

    contract = {
        "intent": question.get("intent"),
        "route": "rag",
        "risk_level": question.get("risk_level", "low"),
        "recognized_terms": [question.get("intent")],
        "preferred_sources": question.get("preferred_sources") or [],
        "policies": [],
    }
    hours_note = (
        "Horario de atención: ACTIVO (hay personal). El equipo contacta al candidato."
        if en_horario
        else "Horario de atención: FUERA DE HORARIO. Puede referir a llamar a oficina (8:00–17:30)."
    )
    system_facts_note = f"{_residency_prompt_note(facts)}\n{hours_note}"
    prompt = build_generation_prompt(
        message=message,
        knowledge_contract=contract,
        context_text=context.get("context_text") or "",
        residency_note=system_facts_note,
    )
    answer = (call_llm(prompt) or "").strip()
    if conditional and not answer:
        return _HANDOFF_REPLY, True
    return answer, False


def plan_and_respond(
    enriched: dict[str, Any],
    message: str,
    known_facts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Planea acciones y genera el texto de respuesta. No persiste ni envía."""
    known_facts = dict(known_facts or {})
    primary = enriched.get("primary_intent")
    questions = enriched.get("questions") or []
    answers = enriched.get("answers_to_persist") or []

    action_order: list[str] = []
    response_parts: list[str] = []

    # memory_guard (tarea 6): forbidden_questions desde memoria previa + resolución
    # de reclamo de memoria ("ya te había dicho que full"). Se corre sobre la
    # memoria PREVIA (known_facts), no sobre merged.
    mg = apply_memory_guard(enriched, message, known_facts)
    claim = mg["memory_claim"]

    # En reaffirm/conflict NO se reescribe el fact reclamado (spec 6.3): se filtra
    # de los facts a persistir; process_as_fact sí fluye normal.
    facts_to_persist = answers
    if claim and claim["resolution"] in {"reaffirm", "conflict"}:
        facts_to_persist = [a for a in answers if a.get("field") != claim["field"]]

    # facts proyectados (multi-intent registra en silencio → afectan el funnel)
    merged = {**known_facts, **{a["field"]: a["value"] for a in facts_to_persist}}
    if facts_to_persist:
        action_order.append("persist_answers_silently")

    # 1. Handoff (riesgo / escalamiento) — corta el flujo
    if enriched.get("requires_human") or primary in {"reingreso", "out_of_scope", "complaint"}:
        action_order.append("human_handoff")
        reply = _SIGNAL_REPLIES.get(primary, _HANDOFF_REPLY)
        return {
            "recommended_action_order": action_order,
            "facts_to_persist": facts_to_persist,
            "response_text": reply,
            "core_completeness": core_completeness(merged),
            "handoff": True,
        }

    # 2. Responder preguntas (RAG) — prioriza la primera; ofrece la segunda
    if questions:
        action_order.append("answer_primary_question")
        answer_text, derive_to_human = _generate_rag_answer(questions[0], message, merged)
        # Fase 5.2 — fail-closed: intent condicional sin fuente autorizada (o sin
        # generación). No inventar; derivar a Capital Humano y cortar como handoff
        # (sin encimar pregunta de funnel sobre la derivación).
        if derive_to_human:
            action_order.append("human_handoff")
            return {
                "recommended_action_order": action_order,
                "facts_to_persist": facts_to_persist,
                "response_text": answer_text,
                "core_completeness": core_completeness(merged),
                "handoff": True,
                "handoff_reason": "no_authorized_source",
            }
        response_parts.append(answer_text)
        if len(questions) > 1:
            action_order.append("offer_secondary_question")
            response_parts.append("Si gusta, también le platico sobre lo otro que preguntó.")

    # 3. Signal sin pregunta (saludo, on_route, etc.)
    elif primary in _SIGNAL_REPLIES:
        response_parts.append(_SIGNAL_REPLIES[primary])

    # 3.5 Reclamo de memoria (tarea 6.3). reaffirm: reafirma y sigue el funnel
    # saltando el campo; conflict: confirmación neutral y NO encima pregunta de
    # funnel; process_as_fact: nada especial (el dato ya fluye como answer).
    if claim and claim["resolution"] == "reaffirm":
        action_order.append("reaffirm_from_memory")
        response_parts.append(_MEMORY_REAFFIRM_REPLY)
    elif claim and claim["resolution"] == "conflict":
        action_order.append("register_memory_conflict")
        response_parts.append(_MEMORY_CONFLICT_REPLY)

    # 4. Siguiente pregunta del funnel (salvo signals que no continúan, o cuando
    # un conflicto de memoria ya pidió confirmación). Respeta forbidden_questions.
    conflict_pending = bool(claim and claim["resolution"] == "conflict")
    if primary not in _NO_FUNNEL_SIGNALS and not conflict_pending:
        nq = next_funnel_question(merged, mg["forbidden_questions"])
        if nq:
            action_order.append("emit_funnel_question")
            response_parts.append(nq)
        else:
            action_order.append("mark_profile_ready")
            if not response_parts:
                response_parts.append(
                    "Con eso ya tenemos su información completa. Nuestro equipo la revisa "
                    "y le contactamos para continuar."
                )

    # Fallback si nada produjo texto (ej. acknowledgement con núcleo completo)
    if not response_parts:
        response_parts.append("Anotado, aquí seguimos con su proceso.")

    return {
        "recommended_action_order": action_order,
        "facts_to_persist": facts_to_persist,
        "response_text": "\n\n".join(p for p in response_parts if p),
        "core_completeness": core_completeness(merged),
        "forbidden_questions": mg["forbidden_questions"],
        "memory_claim": claim,
        "handoff": False,
    }
