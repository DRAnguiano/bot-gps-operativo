"""Aflojar respuestas enlatadas (bug en vivo conv 166, 2026-07-07).

Cubre:
- El chiste se detecta por la señal `is_joke_request` del extractor unificado
  (misma llamada LLM del turno — sin llamada dedicada ni substring rígido) y tiene
  prioridad sobre un requires_rag mal clasificado por overlap de aliases.
- _should_use_friendly_llm ampliado: catch-all va a LLM cálido, no a texto enlatado,
  salvo greeting/candidate_profile_signal/requires_clarification (ramas dedicadas).
- Los guardrails de seguridad siguen intactos.
"""
from __future__ import annotations

from app.knowledge.turn_intent_classifier import TurnIntentSignals
from app.orchestrators import knowledge_orchestrator as KO


# ── señal is_joke_request del extractor (no substring, no Term Neo4j) ──────────

def test_joke_signal_lives_in_unified_extractor():
    # La señal existe en el dataclass y default False — el LLM la decide por
    # few-shot en la MISMA llamada del clasificador (cero costo extra).
    s = TurnIntentSignals()
    assert s.is_joke_request is False
    s2 = TurnIntentSignals(is_joke_request=True)
    assert s2.is_joke_request is True


def test_safety_gate_blocks_joke_on_risky_turn():
    # Aunque el extractor marque chiste, un turno de riesgo no va al humor.
    contract = {"requires_human": True, "risk_level": "high"}
    assert KO._is_safe_for_friendly_llm("cuéntame un chiste", contract) is False


# ── _should_use_friendly_llm ampliado ──────────────────────────────────────────

def _contract(**over):
    base = {"route": "info", "intent": "some_faq_intent", "risk_level": "low",
            "requires_human": False, "requires_clarification": False}
    base.update(over)
    return base


def test_widened_catchall_goes_friendly():
    assert KO._should_use_friendly_llm("algo ambiguo", _contract()) is True


def test_greeting_still_excluded_from_widened_catchall():
    assert KO._should_use_friendly_llm("hola", _contract(intent="greeting")) is False


def test_profile_signal_still_excluded_from_widened_catchall():
    assert KO._should_use_friendly_llm(
        "full", _contract(intent="candidate_profile_signal")
    ) is False


def test_requires_clarification_still_excluded():
    assert KO._should_use_friendly_llm(
        "?", _contract(requires_clarification=True)
    ) is False


def test_requires_human_still_blocked_by_safety_gate():
    assert KO._should_use_friendly_llm(
        "algo delicado", _contract(requires_human=True)
    ) is False


def test_high_risk_still_blocked_by_safety_gate():
    assert KO._should_use_friendly_llm(
        "algo riesgoso", _contract(risk_level="high")
    ) is False


# ── conversational_purpose (gemini-full-provider-migration B6) ─────────────────

def test_purpose_parsed_from_extractor_json(monkeypatch):
    import json as _json
    from app.knowledge.turn_intent_classifier import classify_turn_intent
    monkeypatch.setattr(
        "app.gemini_client.dispatch_json",
        lambda *a, **kw: _json.dumps({"conversational_purpose": "queja"}),
    )
    assert classify_turn_intent("así que chiste el proceso").conversational_purpose == "queja"


def test_purpose_invalid_value_degrades_to_none(monkeypatch):
    import json as _json
    from app.knowledge.turn_intent_classifier import classify_turn_intent
    monkeypatch.setattr(
        "app.gemini_client.dispatch_json",
        lambda *a, **kw: _json.dumps({"conversational_purpose": "hackeo"}),
    )
    assert classify_turn_intent("lo que sea").conversational_purpose == "none"


def test_purpose_guidance_reaches_friendly_prompt(monkeypatch):
    # La finalidad orienta el prompt del friendly (respuesta situada, no genérica).
    captured = {}

    def _fake_call_llm(prompt):
        captured["prompt"] = prompt
        return "Entiendo su molestia, su proceso sí avanza con nosotros."

    monkeypatch.setattr(KO, "call_llm", _fake_call_llm)
    out = KO._answer_friendly_message("puro trámite y trámite", _contract(), None, purpose="queja")
    assert "molestia" in captured["prompt"].lower()
    assert out["reply"]


def test_purpose_unknown_keeps_generic_prompt(monkeypatch):
    captured = {}

    def _fake_call_llm(prompt):
        captured["prompt"] = prompt
        return "Aquí andamos."

    monkeypatch.setattr(KO, "call_llm", _fake_call_llm)
    KO._answer_friendly_message("hola", _contract(), None, purpose="none")
    assert "MOLESTIA" not in captured["prompt"]


# ── D8: texto fijo solo como degradación ──────────────────────────────────────

def test_document_ack_generated_with_template_fallback(monkeypatch):
    contract = {"reply_template": {"id": "document_ack", "text": "plantilla fija"}}
    monkeypatch.setattr(
        KO, "_generate_situated_reply",
        lambda situation, fallback, **kw: "acuse generado natural",
    )
    assert KO._controlled_reply_from_contract(contract) == "acuse generado natural"


def test_situated_reply_falls_back_on_llm_failure(monkeypatch):
    def _boom(*a, **kw):
        raise RuntimeError("llm caído")

    monkeypatch.setattr("app.gemini_client.dispatch_generation", _boom)
    out = KO._generate_situated_reply("situación X", fallback="texto fijo")
    assert out == "texto fijo"


def test_situated_reply_falls_back_on_empty(monkeypatch):
    monkeypatch.setattr("app.gemini_client.dispatch_generation", lambda *a, **kw: "")
    out = KO._generate_situated_reply("situación X", fallback="texto fijo")
    assert out == "texto fijo"
