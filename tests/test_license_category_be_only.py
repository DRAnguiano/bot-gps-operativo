"""Licencia federal: solo B/E aplican a estos puestos (bug en vivo 2026-07-07).

A es irrelevante para tracto full/sencillo; se preserva como category_raw (mismo
patrón que vehicle_type_raw) en vez de tratarse como respuesta válida. El texto
candidato-facing tampoco debe ofrecer A como opción.
"""
from __future__ import annotations

from app.knowledge.turn_extractor import FieldValue, TurnExtraction, validate_extraction
from app.knowledge.turn_intent_classifier import TurnIntentSignals


def _facts_dict(out):
    return {f"{r['fact_group']}.{r['fact_key']}": r["fact_value"] for r in out}


def test_license_b_promotes_normally():
    ext = TurnExtraction(
        fields={"license.category": FieldValue(value="B", explicit_marker=True)},
        signals=TurnIntentSignals(),
    )
    facts = _facts_dict(validate_extraction(ext, {}))
    assert facts.get("license.category") == "B"


def test_license_e_promotes_normally():
    ext = TurnExtraction(
        fields={"license.category": FieldValue(value="E", explicit_marker=True)},
        signals=TurnIntentSignals(),
    )
    facts = _facts_dict(validate_extraction(ext, {}))
    assert facts.get("license.category") == "E"


def test_license_a_does_not_satisfy_requirement():
    ext = TurnExtraction(
        fields={"license.category": FieldValue(value="A", explicit_marker=True)},
        signals=TurnIntentSignals(),
    )
    facts = _facts_dict(validate_extraction(ext, {}))
    assert "license.category" not in facts
    assert facts.get("license.category_raw") == "A"


def test_funnel_question_text_never_offers_a():
    from app.orchestrators.knowledge_orchestrator import _FUNNEL_STEPS

    for step in _FUNNEL_STEPS:
        if "license.category" in step.get("keys", set()):
            for variant in step["variants"]:
                assert "A, B" not in variant and "A o " not in variant and " A," not in variant, variant


def test_reencauce_desc_never_offers_a():
    from app.orchestrators.knowledge_orchestrator import _REENCAUCE_FIELD_DESC

    desc = _REENCAUCE_FIELD_DESC["license.category"]
    assert "A, B" not in desc and "A o " not in desc


def test_followup_template_never_offers_a():
    from app.followup.templates import _CAMPO_DISPLAY

    display = _CAMPO_DISPLAY["tipo de licencia"]
    assert "A, B" not in display and "A o " not in display
