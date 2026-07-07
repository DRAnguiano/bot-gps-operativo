"""Resumen de confirmación al cierre del funnel (gemini-natural-recruiter, D6).

Contrato: specs/funnel-summary-confirmation. Deterministas, sin LLM/BD.
"""
from __future__ import annotations

from app.knowledge.current_turn import (
    build_current_turn_ack,
    build_funnel_summary,
    next_question_from_missing_facts,
    summary_confirmed,
    _extract_context_confirmation_facts,
)
from app.knowledge.text_normalizer import normalize_text
from app.chatwoot_note_sync import calculate_candidate_labels


_COMPLETE = {
    "candidate.name": "José Luis Guerra",
    "candidate.city": "Cadereyta",
    "candidate.age": "33",
    "experience.vehicle_type": "full",
    "experience.years": "10",
    "license.category": "E",
    "license.expiration_text": "vence en 2 años",
    "medical.apto_expiration_text": "vence en 1 año",
    "documents.proof": "cartas",
}


def test_complete_unconfirmed_emits_summary_once():
    q = next_question_from_missing_facts(dict(_COMPLETE))
    assert "¿Es correcto?" in q
    assert "Cadereyta" in q and "full" in q and "cartas laborales" in q


def test_complete_confirmed_emits_closing():
    facts = {**_COMPLETE, "funnel.summary_confirmed": "true"}
    q = next_question_from_missing_facts(facts)
    assert "¿Es correcto?" not in q
    assert "documentos" in q.lower()  # cierre normal (siguiente paso)


def test_incomplete_never_emits_summary():
    facts = {k: v for k, v in _COMPLETE.items() if k != "candidate.city"}
    q = next_question_from_missing_facts(facts)
    assert "¿Es correcto?" not in q
    assert "ciudad" in q.lower()


def test_affirmative_to_summary_confirms():
    summary = build_funnel_summary(_COMPLETE)
    facts = _extract_context_confirmation_facts(normalize_text("sí, es correcto"), summary)
    assert facts.get("funnel.summary_confirmed") == "true"


def test_negative_to_summary_does_not_confirm():
    summary = build_funnel_summary(_COMPLETE)
    facts = _extract_context_confirmation_facts(normalize_text("no, la ciudad está mal"), summary)
    assert "funnel.summary_confirmed" not in facts


def test_correction_after_summary_reconfirms_only_changed():
    summary = build_funnel_summary(_COMPLETE)
    merged = {**_COMPLETE, "candidate.city": "Lerdo"}
    reply = build_current_turn_ack(
        "la ciudad es Lerdo", merged, summary,
        pre_current_facts={"candidate.city": "Lerdo"},
    )
    assert "Queda corregido" in reply
    assert "Lerdo" in reply
    assert "es correcto" in reply.lower()  # re-pregunta confirmable
    assert "Cadereyta" not in reply        # solo el dato cambiado, sin repetir todo


def test_confirmed_via_guard_closes():
    # "sí" al resumen → confirmación contextual + guard → cierre en el mismo turno.
    summary = build_funnel_summary(_COMPLETE)
    ctx = _extract_context_confirmation_facts(normalize_text("si"), summary)
    merged = {**_COMPLETE, **ctx}
    reply = build_current_turn_ack("si", merged, summary, pre_current_facts=ctx)
    assert "documentos" in reply.lower()
    assert "¿Es correcto?" not in reply


def test_perfil_listo_label_not_gated_by_summary():
    # El resumen NO retrasa perfil_listo (los datos ya están completos).
    labels = calculate_candidate_labels({"lead": {}, "facts": dict(_COMPLETE)})
    assert "perfil_listo" in labels


def test_summary_confirmed_helper():
    assert summary_confirmed({"funnel.summary_confirmed": "true"}) is True
    assert summary_confirmed({}) is False
