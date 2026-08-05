"""Tarea 6 — Conversation memory guard del pipeline multi-intent.

Cubre el contrato del spec `multi-intent-pipeline` · "Conversation memory guard":
forbidden_questions desde memoria previa y los tres casos de reclamo de memoria
(reaffirm / process_as_fact / conflict), más la integración en plan_and_respond
(no repreguntar campos ya respondidos).

_is_memory_claim usa LLM T=0 (Groq, fail-safe→False); tests que ejercitan frases
de reclamo reales requieren GROQ_API_KEY y se marcan skipif.
"""
from __future__ import annotations

import os

import pytest

from app.knowledge.memory_guard import (
    apply_memory_guard,
    derive_forbidden_questions,
)
import app.knowledge.intent_orchestrator as IO

_NO_GROQ = not os.getenv("GEMINI_API_KEY")  # Gemini es el proveedor único


def _answer(field: str, value: str, confidence: float = 0.95) -> dict:
    return {"field": field, "value": value, "evidence": value, "confidence": confidence,
            "evidence_ok": True}


def _enriched(answers=None, primary="candidate_answer") -> dict:
    return {
        "message_type": "simple",
        "primary_intent": primary,
        "secondary_intents": [],
        "questions": [],
        "answers_to_persist": answers or [],
        "requires_human": False,
        "max_risk_level": "low",
    }


# ── forbidden_questions (Scenario: Campo ya respondido) ───────────────────────

def test_forbidden_from_known_facts_presence():
    known = {"candidate.city": "Torreón", "experience.vehicle_type": "full",
             "license.type": "E"}
    forbidden = derive_forbidden_questions(known)
    assert "candidate.city" in forbidden
    assert "experience.vehicle_type" in forbidden
    assert "license" in forbidden            # license.type da por respondido "license"
    assert "experience.years" not in forbidden


def test_next_funnel_question_skips_forbidden():
    # candidate.name es el primer paso del funnel; con nombre ya conocido, city es
    # el siguiente.
    facts_with_name = {"candidate.name": "Juan Pérez"}
    assert IO.next_funnel_question(facts_with_name) == FUNNEL_CITY_Q
    # con city prohibido (lo reclama/ya respondió), salta a la siguiente
    nq = IO.next_funnel_question(facts_with_name, ["candidate.city"])
    assert nq != FUNNEL_CITY_Q and nq is not None


FUNNEL_CITY_Q = "¿Desde qué ciudad o estado nos escribe?"


# ── Reclamo de memoria: los tres casos (Scenario: Reclamo de memoria) ─────────

@pytest.mark.external_llm
@pytest.mark.skipif(_NO_GROQ, reason="requiere GROQ_API_KEY — _is_memory_claim usa LLM T=0")
def test_memory_claim_reaffirm_when_prior_matches():
    enriched = _enriched([_answer("experience.vehicle_type", "full")])
    known = {"experience.vehicle_type": "full"}
    mg = apply_memory_guard(enriched, "ya te había dicho que full", known)
    claim = mg["memory_claim"]
    assert claim["resolution"] == "reaffirm"
    assert claim["field"] == "experience.vehicle_type"
    # campo reafirmado entra en forbidden → no se repregunta
    assert "experience.vehicle_type" in mg["forbidden_questions"]


@pytest.mark.external_llm
@pytest.mark.skipif(_NO_GROQ, reason="requiere GROQ_API_KEY — _is_memory_claim usa LLM T=0")
def test_memory_claim_process_as_fact_when_no_prior():
    enriched = _enriched([_answer("experience.vehicle_type", "full")])
    mg = apply_memory_guard(enriched, "ya te había dicho que full", known_facts={})
    assert mg["memory_claim"]["resolution"] == "process_as_fact"


@pytest.mark.external_llm
@pytest.mark.skipif(_NO_GROQ, reason="requiere GROQ_API_KEY — _is_memory_claim usa LLM T=0")
def test_memory_claim_conflict_when_prior_differs():
    enriched = _enriched([_answer("experience.vehicle_type", "full")])
    known = {"experience.vehicle_type": "sencillo"}
    mg = apply_memory_guard(enriched, "ya te había dicho que full", known)
    assert mg["memory_claim"]["resolution"] == "conflict"


def test_no_claim_without_claim_phrase():
    enriched = _enriched([_answer("documents.proof", "cartas")])
    mg = apply_memory_guard(enriched, "si tengo cartas", known_facts={})
    assert mg["memory_claim"] is None


def test_claim_phrase_without_core_answer_is_noop():
    # frase de reclamo pero sin answer núcleo extraído → no hay nada que resolver
    mg = apply_memory_guard(_enriched([]), "ya te había dicho", known_facts={})
    assert mg["memory_claim"] is None


# ── Integración en plan_and_respond ───────────────────────────────────────────
# plan_and_respond llama a classify_message (LLM real, sin mock) — sin guard previo.

@pytest.mark.external_llm
def test_plan_reaffirm_does_not_reask_and_does_not_rewrite():
    enriched = _enriched([_answer("experience.vehicle_type", "full")])
    known = {"experience.vehicle_type": "full"}
    plan = IO.plan_and_respond(enriched, "ya te había dicho que full", known)
    assert "reaffirm_from_memory" in plan["recommended_action_order"]
    # no reescribe el fact reclamado
    assert all(a["field"] != "experience.vehicle_type" for a in plan["facts_to_persist"])
    # no vuelve a preguntar la unidad
    assert "full o sencillo" not in plan["response_text"].lower()
    assert "¿ha manejado sencillo, full" not in plan["response_text"].lower()


@pytest.mark.external_llm
def test_plan_conflict_asks_neutral_confirmation_no_funnel_stack():
    enriched = _enriched([_answer("experience.vehicle_type", "full")])
    known = {"experience.vehicle_type": "sencillo"}
    plan = IO.plan_and_respond(enriched, "ya te había dicho que full", known)
    assert "register_memory_conflict" in plan["recommended_action_order"]
    assert "emit_funnel_question" not in plan["recommended_action_order"]
    # no sobrescribe
    assert all(a["field"] != "experience.vehicle_type" for a in plan["facts_to_persist"])
    assert "confirma" in plan["response_text"].lower()


def test_plan_does_not_repeat_answered_questions():
    # "si tengo cartas": registra documents.proof y NO repite lo ya respondido.
    enriched = _enriched([_answer("documents.proof", "cartas")])
    known = {
        "candidate.name": "Juan Pérez",
        "candidate.age": "35",
        "candidate.city": "Torreón",
        "experience.vehicle_type": "full",
        # FUNNEL_STEPS ("license") requiere category+expiration_text; ("medical")
        # requiere apto_expiration_text — no los alias license.type/apto_status.
        "license.category": "E", "license.expiration_text": "vence en 1 año",
        "medical.apto_expiration_text": "vence en 1 año",
        "experience.years": "10",
    }
    plan = IO.plan_and_respond(enriched, "si tengo cartas", known)
    text = plan["response_text"].lower()
    assert "ciudad" not in text
    assert "full o sencillo" not in text and "sencillo, full" not in text
    assert "años" not in text
    # núcleo completo tras registrar cartas
    assert "mark_profile_ready" in plan["recommended_action_order"]
