"""B10 — decisión operativa unificada (deterministas, sin Groq/DB).

Respuesta visible, nota y labels derivan de la misma decisión por turno. El caso canónico:
un mensaje corto ("5") que responde el campo pendiente (experiencia) NO debe desalinear la
nota ("preguntó por documentos") ni registrar un interés tópico espurio. La señal de verdad
es `facts_written` (qué se registró este turno), no el intent (que puede venir mal
clasificado para una respuesta corta).
"""
from __future__ import annotations

import app.orchestrators.knowledge_orchestrator as KO
from app.chatwoot_note_sync import render_candidate_note


# ── resumen de memoria basado en lo registrado, no en el intent tópico ─────────

def test_registered_summary_experience_not_documents():
    s = KO._registered_fact_summary(["experience.years"])
    assert s is not None
    assert "experiencia" in s.lower()
    assert "documento" not in s.lower()


def test_registered_summary_first_core_fact_wins():
    s = KO._registered_fact_summary(["candidate.city", "experience.years"])
    assert "ciudad" in s.lower()


def test_registered_summary_none_without_core_fact():
    assert KO._registered_fact_summary([]) is None
    assert KO._registered_fact_summary(["interest.requirements_documents"]) is None


# ── no registrar interés tópico cuando el turno respondió el funnel ────────────

def test_topical_interest_not_recorded_when_core_fact_written():
    # "5" respondió experiencia → no es una pregunta de documentos.
    assert KO._should_record_topical_interest("requirements_documents", ["experience.years"]) is False


def test_topical_interest_recorded_when_no_core_fact():
    # Pregunta tópica real (sin registrar dato núcleo) sí se registra.
    assert KO._should_record_topical_interest("requirements_documents", []) is True
    assert KO._should_record_topical_interest("payment_compensation", ["interest.payment"]) is True


# ── consistencia visible: la nota no dice "preguntó por documentos" ────────────

def test_note_no_pregunto_documentos_cuando_registro_experiencia():
    ctx = {
        "lead": {},
        "facts": {"experience.years": "5 años", "candidate.city": "Torreón"},
        "last_message": {"message": "5"},
        "conversation": {},
    }
    note = render_candidate_note(ctx, ["bot_activo"])
    # "5" registró experiencia (aparece en "Lo que ya sabemos"); el documento
    # laboral NO se marca como respondido/preguntado — sigue en "Falta confirmar".
    assert "Experiencia: 5 años" in note
    assert "Preguntó" not in note
    assert "Documento laboral" in note.split("⚠️ Falta confirmar")[-1]
