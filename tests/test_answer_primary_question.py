"""answer_primary_question (multi-intent al path vivo).

Cuando el candidato manda un mensaje compuesto (responde su perfil Y hace una
pregunta — p.ej. "tengo licencia E y full, ¿qué rutas manejan?"), el path vivo
clasificaba como perfil y SOLO avanzaba el funnel, dejando la pregunta sin
responder (la respondía únicamente el shadow). Estos tests fijan que el path vivo
resuelve la pregunta embebida con fundamento (RAG) y hereda el fail-closed de
`_generate_rag_answer` (derivar a Capital Humano para intents sin fuente
autorizada). Deterministas: el pipeline multi-intent va mockeado (sin Groq/Chroma).
"""
from __future__ import annotations

import app.knowledge.intent_classifier as IC
import app.knowledge.intent_enricher as IE
import app.knowledge.intent_orchestrator as IO
import app.orchestrators.knowledge_orchestrator as KO


def _patch_pipeline(monkeypatch, *, questions, answer, derive=False, enriched=None):
    monkeypatch.setattr(
        IC, "classify_message", lambda msg, last_bot_question=None: {"questions": questions}
    )
    monkeypatch.setattr(
        IE, "enrich_classification", lambda c: (enriched or {"questions": questions})
    )

    # Firma EXPLÍCITA (no *args/**kwargs) para conservar detección de futuros
    # cambios de contrato de `_generate_rag_answer(question, message, facts=None)`.
    def _mock_generate_rag_answer(q, msg, facts=None):
        return answer, derive

    monkeypatch.setattr(IO, "_generate_rag_answer", _mock_generate_rag_answer)


# ── gate barato (no invoca el pipeline si no hay señal de pregunta) ────────────
# Fase 2/D5: el gate ahora es el detector ÚNICO has_business_question (mismo que el
# guard del worker), no el antiguo KO._looks_like_question (eliminado).

def test_has_business_question_detects_punctuation_and_business_terms():
    from app.knowledge.current_turn import has_business_question

    assert has_business_question("tengo full, ¿qué rutas manejan?")
    assert has_business_question("me dicen las rutas")          # término de negocio
    assert not has_business_question("si, soy de Torreon y llevo tres anios")


def test_pipeline_delivers_facts_to_rag_generator(monkeypatch):
    """Contrato Fase 5.2: `_resolve_embedded_question` pasa los facts (persistidos +
    del turno) como 3er argumento a `_generate_rag_answer`. Captura el arg recibido."""
    captured = {}

    monkeypatch.setattr(
        IC, "classify_message", lambda msg, last_bot_question=None: {"questions": []}
    )
    monkeypatch.setattr(
        IE,
        "enrich_classification",
        lambda c: {"questions": [{"intent": "route_question", "requires_rag": True}]},
    )

    def _capturing(q, msg, facts=None):
        captured["facts"] = facts
        return "Rutas del corredor norte.", False

    monkeypatch.setattr(IO, "_generate_rag_answer", _capturing)

    lead_memory = {"facts": [{"fact_group": "license", "fact_key": "category", "fact_value": "E"}]}
    out = KO._resolve_embedded_question(
        "tengo licencia E, que rutas manejan?",
        {"route": "profile", "requires_rag": False},
        lead_memory,
    )
    assert out is not None
    assert captured["facts"] == {"license.category": "E"}


def test_gate_skips_pipeline_when_no_question_signal(monkeypatch):
    # Si no hay señal de pregunta, no debe ni invocar el clasificador (costo).
    def _boom(*a, **k):
        raise AssertionError("classify_message no debe llamarse sin señal de pregunta")

    monkeypatch.setattr(IC, "classify_message", _boom)
    out = KO._resolve_embedded_question(
        "si, soy de Torreon y llevo tres anios", {"route": "profile"}, None
    )
    assert out is None


# ── resolución de la pregunta embebida ────────────────────────────────────────

def test_compound_message_resolves_embedded_question(monkeypatch):
    _patch_pipeline(
        monkeypatch,
        questions=[{"intent": "route_question", "requires_rag": True,
                    "preferred_sources": ["04_bases_rutas.md"]}],
        answer="Nuestras rutas habituales corren el corredor Torreon-Monterrey.",
    )
    out = KO._resolve_embedded_question(
        "tengo licencia E y experiencia en full, que rutas manejan?",
        {"route": "profile", "requires_rag": False},
        None,
    )
    assert out is not None
    assert "rutas habituales" in out["answer"]
    assert out["derive_to_human"] is False
    assert out["intent"] == "route_question"


def test_pay_question_without_source_derives_to_human(monkeypatch):
    # fail-closed: intent condicional sin fuente autorizada → deriva, no inventa.
    _patch_pipeline(
        monkeypatch,
        questions=[{"intent": "pay_question", "requires_rag": True,
                    "requires_human_if_no_authorized_source": True,
                    "preferred_sources": ["01_pago_prestaciones.md"]}],
        answer=IO._HANDOFF_REPLY,
        derive=True,
    )
    out = KO._resolve_embedded_question(
        "tengo full, cuanto pagan por viaje?",
        {"route": "profile", "requires_rag": False},
        None,
    )
    assert out is not None
    assert out["derive_to_human"] is True


def test_no_answerable_question_returns_none(monkeypatch):
    # El mensaje pasa el gate (tiene término de negocio) pero el clasificador no
    # halla una pregunta RAG → no se antepone nada.
    _patch_pipeline(monkeypatch, questions=[], answer="")
    out = KO._resolve_embedded_question(
        "tengo licencia tipo E vigente", {"route": "profile", "requires_rag": False}, None
    )
    assert out is None


def test_skips_when_route_is_already_rag(monkeypatch):
    # Si la ruta principal ya es RAG, la pregunta es el intent primario y ya se
    # responde por el camino normal: no duplicar.
    def _boom(*a, **k):
        raise AssertionError("no debe clasificar si la ruta ya es RAG")

    monkeypatch.setattr(IC, "classify_message", _boom)
    out = KO._resolve_embedded_question(
        "que rutas manejan?", {"route": "rag", "requires_rag": True}, None
    )
    assert out is None


def test_skips_when_already_human_handoff(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("no debe clasificar si ya hay handoff")

    monkeypatch.setattr(IC, "classify_message", _boom)
    out = KO._resolve_embedded_question(
        "cuanto pagan?", {"route": "profile", "requires_human": True}, None
    )
    assert out is None


def test_only_rag_questions_are_considered(monkeypatch):
    # Una question sin requires_rag (p.ej. small talk clasificado como pregunta)
    # no debe disparar generacion RAG.
    _patch_pipeline(
        monkeypatch,
        questions=[{"intent": "smalltalk_question", "requires_rag": False}],
        answer="algo",
    )
    out = KO._resolve_embedded_question(
        "todo bien? oye y de rutas?", {"route": "profile", "requires_rag": False}, None
    )
    assert out is None
