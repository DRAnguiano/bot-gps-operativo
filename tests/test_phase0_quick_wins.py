"""Tests mínimos de Fase 0 (quick wins): F6, F26, F30.

No cubren el pipeline completo; solo verifican los 3 cambios puntuales y que no haya
regresión obvia en los casos vecinos. Se ejecutan sin DB ni red.
"""
from __future__ import annotations

from app.lead_memory.profile_extractor import extract_profile_facts_as_dict
from app.knowledge.intent_enricher import enrich_classification
from app.chatwoot_note_sync import render_candidate_note


# ── F6: "no le veo el problema" ya no es evidencia de apto vigente ──────────────

def test_f6_frase_fragil_no_marca_apto_vigente():
    # El mensaje DEBE contener "apto" para entrar al bloque; así el test discrimina
    # de verdad el cambio (con código viejo "no le veo el problema" marcaba vigente).
    facts = extract_profile_facts_as_dict("tengo mi apto y no le veo el problema")
    assert facts.get("medical.apto_status") != "vigente"
    assert facts.get("document.apto_status") != "vigente"


def test_f6_apto_vigente_explicito_si_se_detecta():
    facts = extract_profile_facts_as_dict("mi apto esta vigente")
    assert facts.get("medical.apto_status") == "vigente"


def test_f6_apto_vence_en_anios_sigue_vigente():
    # No regresión del otro disparador legítimo de vigencia.
    facts = extract_profile_facts_as_dict("el apto vence en 2 anos")
    assert facts.get("medical.apto_status") == "vigente"


# ── F26: la nota privada no contiene Temperatura ───────────────────────────────

def _nota_minima() -> str:
    context = {"lead": {}, "conversation": {}, "facts": {}, "last_message": {}}
    return render_candidate_note(context, labels=[], fallback_last_message="full")


def test_f26_nota_sin_temperatura():
    nota = _nota_minima()
    assert "Temperatura" not in nota
    assert "🌡️" not in nota


def test_f26_nota_conserva_secciones_clave():
    # No regresión: las secciones operativas vigentes (chatwoot-ai-note) siguen
    # presentes. "Perfil confirmado"/"Embudo" son del contrato deprecado.
    nota = _nota_minima()
    for seccion in ("👤 Contacto", "📌 Estado del candidato", "⏭️ Siguiente acción"):
        assert seccion in nota


# ── F30: política de pay_question alineada con la spec ─────────────────────────

def _enriquecer_pay():
    classification = {
        "message_type": "simple",
        "primary_intent": "pay_question",
        "secondary_intents": [],
        "answers": [],
        "questions": [{"intent": "pay_question", "evidence": "cuanto pagan", "is_admission": False}],
    }
    return enrich_classification(classification)


def test_f30_pay_question_policy():
    enriched = _enriquecer_pay()
    q = enriched["questions"][0]
    assert q["risk_level"] == "medium"
    assert q["requires_rag"] is True
    assert q["requires_human"] is False
    assert q["requires_human_if_no_authorized_source"] is True
    # El agregado booleano NO debe forzar handoff por una pregunta de pago.
    assert enriched["requires_human"] is False
    assert enriched["max_risk_level"] == "medium"


def test_f30_safety_admission_sigue_requiriendo_humano():
    # No regresión: la admisión de consumo sigue escalando a humano.
    classification = {
        "message_type": "simple",
        "primary_intent": "safety_intent",
        "secondary_intents": [],
        "answers": [],
        "questions": [{"intent": "safety_intent", "evidence": "antes consumia", "is_admission": True}],
    }
    enriched = enrich_classification(classification)
    assert enriched["requires_human"] is True
    assert enriched["max_risk_level"] == "high"
