"""Tests para el change cumulative-ack-repetition-and-renewal-proof-not-detected.

Cubre:
- Bug 1: build_current_turn_ack confirma SOLO facts nuevos del turno (el caller
  filtra contra saved_facts y pasa pre_current_facts ya depurado).
- Bug 2: validate_extraction surface signals.renewal_proof como fact, y la
  confirmación contextual mapea "Si"/"no" a documents.renewal_proof según la
  última pregunta del bot. Regresión del bucle del funnel.
"""
from __future__ import annotations

from app.knowledge.current_turn import (
    build_current_turn_ack,
    _extract_context_confirmation_facts,
    _next_funnel_question_or_none,
    _renewal_question_for_short_expiry,
)
from app.knowledge.turn_extractor import (
    FieldValue,
    TurnExtraction,
    validate_extraction,
)
from app.knowledge.turn_intent_classifier import TurnIntentSignals
from app.knowledge.text_normalizer import normalize_text


# ---------------------------------------------------------------------------
# Bug 1 — ack solo confirma facts nuevos del turno
# ---------------------------------------------------------------------------

def test_ack_confirms_only_fresh_fact():
    """Caller ya filtró: pre_current_facts=solo el dato nuevo (licencia). Sin eco de
    datos (feedback 2026-07-03): el ack no repite NINGÚN valor, ni el nuevo ni el previo."""
    saved = {
        "candidate.city": "Torreón",
        "candidate.age": "38",
        "experience.vehicle_type": "full",
    }
    fresh = {"license.category": "E"}
    merged = {**saved, **fresh}
    reply = build_current_turn_ack(
        "tipo E", merged, "¿Qué tipo de licencia federal tiene?",
        pre_current_facts=fresh,
    )
    # No re-confirma ningún dato, ni el fresco ni los previos
    assert "tipo E" not in reply
    assert "Torreón" not in reply
    assert "Edad anotada" not in reply
    assert "tracto full" not in reply
    assert "?" in reply  # trae la siguiente pregunta del funnel


def test_ack_empty_fresh_falls_back_to_generic_prefix():
    """Si nada es nuevo este turno, no se re-confirma nada previo."""
    saved = {"candidate.city": "Torreón", "candidate.age": "38"}
    reply = build_current_turn_ack(
        "ok", {**saved}, "¿algo?", pre_current_facts={},
    )
    assert "Torreón" not in reply
    assert "Edad anotada" not in reply


def test_two_consecutive_turns_do_not_accumulate():
    """Simula el flujo del caller: cada turno filtra fresh contra saved acumulado."""
    saved: dict = {}

    def turn(new_facts: dict, msg: str, last_q: str) -> str:
        fresh = {k: v for k, v in new_facts.items() if saved.get(k) != v}
        merged = {**saved, **new_facts}
        reply = build_current_turn_ack(msg, merged, last_q, pre_current_facts=fresh)
        saved.update(new_facts)
        return reply

    r1 = turn({"candidate.city": "Torreón"}, "Torreón", "¿ciudad?")
    assert "Torreón" not in r1  # sin eco de datos (feedback 2026-07-03)

    # Turno 2: extractor parrotea ciudad + aporta edad. El ack no repite ningún valor.
    r2 = turn({"candidate.city": "Torreón", "candidate.age": "38"}, "38", "¿edad?")
    assert "38" not in r2
    assert "Torreón" not in r2  # no se re-confirma ciudad


# ---------------------------------------------------------------------------
# Bug 2 — validate_extraction surface renewal_proof
# ---------------------------------------------------------------------------

def _facts_dict(out: list[dict]) -> dict:
    return {f"{r['fact_group']}.{r['fact_key']}": r["fact_value"] for r in out}


def test_validate_extraction_surfaces_renewal_proof_si():
    ext = TurnExtraction(
        fields={},
        signals=TurnIntentSignals(renewal_proof="si"),
    )
    facts = _facts_dict(validate_extraction(ext, {}))
    assert facts.get("documents.renewal_proof") == "si"


def test_validate_extraction_surfaces_renewal_proof_no():
    ext = TurnExtraction(fields={}, signals=TurnIntentSignals(renewal_proof="no"))
    facts = _facts_dict(validate_extraction(ext, {}))
    assert facts.get("documents.renewal_proof") == "no"


def test_validate_extraction_no_renewal_signal_no_fact():
    ext = TurnExtraction(fields={}, signals=TurnIntentSignals(renewal_proof=None))
    facts = _facts_dict(validate_extraction(ext, {}))
    assert "documents.renewal_proof" not in facts


def test_validate_extraction_renewal_alongside_field():
    """Un campo normal + la señal de renovación conviven."""
    ext = TurnExtraction(
        fields={"license.category": FieldValue(value="E", explicit_marker=True)},
        signals=TurnIntentSignals(renewal_proof="si"),
    )
    facts = _facts_dict(validate_extraction(ext, {}))
    assert facts.get("license.category") == "E"
    assert facts.get("documents.renewal_proof") == "si"


# ---------------------------------------------------------------------------
# Bug 2 — confirmación contextual mapea renovación
# ---------------------------------------------------------------------------

_RENEWAL_Q = (
    "Para continuar con su licencia federal, como alternativa aceptamos el "
    "comprobante de pago de su renovación o trámite. ¿Ya cuenta con ese comprobante?"
)


def test_context_confirm_si_renewal():
    facts = _extract_context_confirmation_facts(normalize_text("Si"), _RENEWAL_Q)
    assert facts.get("documents.renewal_proof") == "si"


def test_context_confirm_ya_tengo_renewal():
    facts = _extract_context_confirmation_facts(
        normalize_text("ya tengo comprobante de renovación"), _RENEWAL_Q
    )
    assert facts.get("documents.renewal_proof") == "si"


def test_context_confirm_no_renewal():
    facts = _extract_context_confirmation_facts(normalize_text("no"), _RENEWAL_Q)
    assert facts.get("documents.renewal_proof") == "no"


def test_context_confirm_todavia_no_renewal():
    facts = _extract_context_confirmation_facts(normalize_text("todavía no"), _RENEWAL_Q)
    assert facts.get("documents.renewal_proof") == "no"


def test_context_confirm_si_without_renewal_question_no_fact():
    """'Si' a otra pregunta no inventa renewal_proof."""
    facts = _extract_context_confirmation_facts(
        normalize_text("Si"), "¿Su apto médico está vigente?"
    )
    assert "documents.renewal_proof" not in facts


# ---------------------------------------------------------------------------
# Bug 2 — regresión del bucle del funnel
# ---------------------------------------------------------------------------

def test_funnel_stops_asking_renewal_when_proof_si():
    facts = {
        "license.expiration_text": "3 meses",
        "documents.renewal_proof": "si",
    }
    q = _renewal_question_for_short_expiry(facts)
    assert q is None  # ya no pregunta por el comprobante


def test_funnel_soft_close_when_proof_no():
    facts = {
        "license.expiration_text": "3 meses",
        "documents.renewal_proof": "no",
    }
    q = _renewal_question_for_short_expiry(facts)
    assert q is not None
    assert facts.get("funnel.status") == "vencido_sin_tramite"


def test_full_funnel_advances_past_renewal_with_proof():
    """Con comprobante 'si', el funnel avanza al siguiente campo (apto), no re-pregunta."""
    facts = {
        "candidate.name": "Joaquin Ramos",
        "candidate.city": "Torreón",
        "candidate.age": "38",
        "experience.vehicle_type": "full",
        "license.category": "E",
        "license.expiration_text": "3 meses",
        "documents.renewal_proof": "si",
    }
    q = _next_funnel_question_or_none(facts)
    assert q is not None
    assert "comprobante de renovación" not in q
    assert "apto" in normalize_text(q)  # siguiente campo pendiente
