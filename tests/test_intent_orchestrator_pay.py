"""Fase 5.2/5.3 — pay_question fail-closed en el orquestador multi-intent.

Contrato: para intents con `requires_human_if_no_authorized_source` (pay_question),
sin fuente autorizada suficiente (0 chunks del filtro preferred_sources o error de
retrieval) o sin generación del LLM teniendo fuente, el bot NO inventa cifras:
deriva a Capital Humano (_HANDOFF_REPLY) y corta como handoff. Los demás intents
RAG conservan el fallback telefónico (no deconstruir).

Deterministas: sin Groq, sin Chroma, sin DB — retrieve/call_llm se monkeypatchean.
"""
from __future__ import annotations

import app.knowledge.intent_orchestrator as IO
from app.knowledge.intent_enricher import enrich_classification


# ── helpers ───────────────────────────────────────────────────────────────────

def _pay_question(**overrides) -> dict:
    q = {
        "intent": "pay_question",
        "evidence": "cuanto pagan",
        "is_admission": False,
        "requires_rag": True,
        "requires_human": False,
        "risk_level": "medium",
        "requires_human_if_no_authorized_source": True,
        "preferred_sources": ["01_pago_prestaciones.md"],
    }
    q.update(overrides)
    return q


def _logistics_question() -> dict:
    return {
        "intent": "logistics_question",
        "evidence": "que rutas manejan",
        "requires_rag": True,
        "requires_human": False,
        "risk_level": "low",
        "preferred_sources": ["04_bases_rutas.md"],
    }


def _enriched_with(question: dict) -> dict:
    return {
        "message_type": "simple",
        "primary_intent": question["intent"],
        "secondary_intents": [],
        "questions": [question],
        "answers_to_persist": [],
        "requires_human": False,
        "max_risk_level": question.get("risk_level", "low"),
    }


def _ctx_empty(error: str | None = None) -> dict:
    ctx = {
        "items": [], "context_text": "", "sources": [], "timing_ms": 0.0,
        "source_filter_used": ["01_pago_prestaciones.md"],
    }
    if error:
        ctx["error"] = error
    return ctx


def _ctx_with_source() -> dict:
    return {
        "items": [{"text": "el pago es por kilómetro", "source": "01_pago_prestaciones.md"}],
        "context_text": "el pago es por kilómetro según tabulador",
        "sources": ["01_pago_prestaciones.md"],
        "timing_ms": 1.0,
        "source_filter_used": ["01_pago_prestaciones.md"],
    }


# ── pay sin fuente autorizada → derivar a CH, sin inventar ────────────────────

def test_pay_sin_fuente_deriva_a_ch_sin_llamar_llm(monkeypatch):
    llm_calls: list = []
    monkeypatch.setattr(IO, "retrieve_preferred_context", lambda *a, **k: _ctx_empty())
    monkeypatch.setattr(IO, "call_llm", lambda prompt: llm_calls.append(prompt) or "NO DEBE LLAMARSE")

    result = IO.plan_and_respond(_enriched_with(_pay_question()), "¿cuánto pagan el kilómetro?")

    assert result["handoff"] is True
    assert result["handoff_reason"] == "no_authorized_source"
    assert result["response_text"] == IO._HANDOFF_REPLY
    assert "human_handoff" in result["recommended_action_order"]
    assert llm_calls == []  # fail-closed: sin fuente, el LLM ni se invoca


def test_pay_error_de_retrieval_tambien_deriva(monkeypatch):
    monkeypatch.setattr(IO, "retrieve_preferred_context", lambda *a, **k: _ctx_empty(error="ConnectionError: chroma down"))
    monkeypatch.setattr(IO, "call_llm", lambda prompt: "NO DEBE LLAMARSE")

    result = IO.plan_and_respond(_enriched_with(_pay_question()), "¿cuánto pagan?")

    assert result["handoff"] is True
    assert result["response_text"] == IO._HANDOFF_REPLY


def test_pay_sin_fuente_no_encima_pregunta_de_funnel(monkeypatch):
    # La derivación corta el flujo: no debe aparecer la pregunta de ciudad encima.
    monkeypatch.setattr(IO, "retrieve_preferred_context", lambda *a, **k: _ctx_empty())

    result = IO.plan_and_respond(_enriched_with(_pay_question()), "¿cuánto pagan?", known_facts={})

    assert "¿Desde qué ciudad" not in result["response_text"]
    assert "emit_funnel_question" not in result["recommended_action_order"]


def test_pay_llm_vacio_con_fuente_deriva(monkeypatch):
    monkeypatch.setattr(IO, "retrieve_preferred_context", lambda *a, **k: _ctx_with_source())
    monkeypatch.setattr(IO, "build_generation_prompt", lambda **k: "PROMPT")
    monkeypatch.setattr(IO, "call_llm", lambda prompt: "")  # timeout/error → vacío

    result = IO.plan_and_respond(_enriched_with(_pay_question()), "¿cuánto pagan?")

    assert result["handoff"] is True
    assert result["handoff_reason"] == "no_authorized_source"
    assert result["response_text"] == IO._HANDOFF_REPLY


# ── pay con fuente autorizada → respuesta normal + funnel continúa ───────────

def test_pay_con_fuente_responde_y_continua_funnel(monkeypatch):
    monkeypatch.setattr(IO, "retrieve_preferred_context", lambda *a, **k: _ctx_with_source())
    monkeypatch.setattr(IO, "build_generation_prompt", lambda **k: "PROMPT")
    monkeypatch.setattr(IO, "call_llm", lambda prompt: "El pago es por kilómetro recorrido, según la ruta asignada.")

    result = IO.plan_and_respond(_enriched_with(_pay_question()), "¿cuánto pagan?", known_facts={})

    assert result["handoff"] is False
    assert "handoff_reason" not in result
    assert "El pago es por kilómetro recorrido" in result["response_text"]
    assert "emit_funnel_question" in result["recommended_action_order"]


# ── no deconstruir: intents RAG sin el flag conservan el fallback telefónico ──

def test_logistics_sin_fuente_mantiene_fallback_telefonico(monkeypatch):
    # El copy depende de is_business_hours (fuera de horario → llamada telefónica;
    # en horario → "nuestro equipo confirma"). Se fija fuera de horario para que
    # el test sea determinista sin importar la hora real de ejecución.
    monkeypatch.setattr("app.knowledge.business_hours.is_business_hours", lambda: False)
    monkeypatch.setattr(IO, "retrieve_preferred_context", lambda *a, **k: _ctx_empty())
    monkeypatch.setattr(IO, "call_llm", lambda prompt: "NO DEBE LLAMARSE")

    result = IO.plan_and_respond(_enriched_with(_logistics_question()), "¿qué rutas manejan?")

    assert result["handoff"] is False
    assert "llamarnos de 8:00 a 17:30" in result["response_text"]
    assert "emit_funnel_question" in result["recommended_action_order"]


# ── integración enricher→orquestador (5.3, sin LLM de clasificación) ─────────

def test_pay_end_to_end_enricher_orquestador_sin_fuente(monkeypatch):
    classification = {
        "message_type": "simple",
        "primary_intent": "pay_question",
        "secondary_intents": [],
        "answers": [],
        "questions": [{"intent": "pay_question", "evidence": "cuanto pagan", "is_admission": False}],
    }
    enriched = enrich_classification(classification)
    assert enriched["questions"][0]["requires_human_if_no_authorized_source"] is True
    assert enriched["requires_human"] is False  # la condicional NO fuerza el agregado

    monkeypatch.setattr(IO, "retrieve_preferred_context", lambda *a, **k: _ctx_empty())
    result = IO.plan_and_respond(enriched, "cuanto pagan")

    assert result["handoff"] is True
    assert result["response_text"] == IO._HANDOFF_REPLY
    # Sin cifras inventadas: el handoff genérico no contiene montos.
    assert "$" not in result["response_text"]
