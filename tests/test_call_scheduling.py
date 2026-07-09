"""B7.4 — call scheduling via LLM T=0 (requiere GROQ_API_KEY, sin agenda real).

Contrato (live-reply, chatwoot-label-taxonomy + message-orchestration):
  - El extractor registra `scheduling.call_requested=true`, `scheduling.call_status=pending`
    y `scheduling.call_window_text` (texto del candidato) ante una solicitud de llamada.
  - `llamada_pendiente` SHALL emitirse SOLO desde la decisión determinista cuando
    `perfil_listo` o `requiere_agente` están activos y el candidato pidió llamada.
    Antes de perfil listo / handoff → `seguimiento` (no `llamada_pendiente`).
  - La validez del horario (`scheduling.call_window_valid`) es B7.5, fuera de este test.

Los tests de detección de solicitud de llamada requieren GROQ_API_KEY
(call_requested usa LLM T=0). Los de labels/notas son deterministas.
"""
from __future__ import annotations

import os

import pytest

_NO_GROQ = not os.getenv("GEMINI_API_KEY")  # Gemini es el proveedor único

import app.lead_memory.profile_extractor as PE
from app.chatwoot_note_sync import (
    OFFICIAL_LABELS,
    calculate_candidate_labels,
    render_candidate_note,
)
from app.knowledge.business_hours import classify_call_window


# ── extractor: detección de solicitud de llamada ──────────────────────────────

@pytest.mark.external_llm
@pytest.mark.skipif(_NO_GROQ, reason="requiere GROQ_API_KEY — call_requested usa LLM T=0")
@pytest.mark.parametrize("message", [
    "quiero que me llamen",
    "me pueden llamar?",
    "prefiero una llamada",
    "mejor llámenme por teléfono",
    "agenden una llamada porfa",
])
def test_call_request_sets_scheduling_facts(message):
    facts = PE.extract_profile_facts_as_dict(message)
    assert facts.get("scheduling.call_requested") == "true"
    assert facts.get("scheduling.call_status") == "pending"


@pytest.mark.external_llm
@pytest.mark.skipif(_NO_GROQ, reason="requiere GROQ_API_KEY — call_requested usa LLM T=0")
@pytest.mark.parametrize("message", [
    "no quiero llamada, mejor escríbanme",
    "no me llamen por favor",
    "¿cuánto pagan?",
    "soy de Torreón y manejo full",
])
def test_no_call_request_no_scheduling_facts(message):
    facts = PE.extract_profile_facts_as_dict(message)
    assert "scheduling.call_requested" not in facts


@pytest.mark.external_llm
@pytest.mark.skipif(_NO_GROQ, reason="requiere GROQ_API_KEY — call_requested usa LLM T=0")
def test_call_window_text_captured():
    facts = PE.extract_profile_facts_as_dict("me pueden llamar mañana a las 4")
    assert facts.get("scheduling.call_requested") == "true"
    window = (facts.get("scheduling.call_window_text") or "").lower().replace("ñ", "n")
    assert "manana" in window or "4" in window


# ── label: emisión gated de llamada_pendiente ─────────────────────────────────

def _ctx(facts=None, requires_human=False, risk_level=None):
    return {
        "lead": {"requires_human": requires_human, "risk_level": risk_level or ""},
        "facts": facts or {},
    }


_PERFIL_LISTO_FACTS = {
    "candidate.name": "Juan Pérez",
    "candidate.age": "35",
    "license.category": "E",
    "license.expiration_text": "vence en 2 años",
    "medical.apto_status": "vigente",
    "medical.apto_expiration_text": "vence en 1 año",
    "experience.vehicle_type": "full",
    "experience.years": "10 años",
    "documents.labor_letters_status": "available",
    "candidate.city": "Torreón",
    "candidate.vacancy_accepted": "sí",
}


def test_llamada_pendiente_con_perfil_listo():
    facts = {**_PERFIL_LISTO_FACTS, "scheduling.call_requested": "true"}
    result = calculate_candidate_labels(_ctx(facts))
    assert "perfil_listo" in result
    assert "llamada_pendiente" in result


def test_llamada_pendiente_con_requiere_agente():
    facts = {"scheduling.call_requested": "true"}
    result = calculate_candidate_labels(_ctx(facts, requires_human=True))
    assert "requiere_agente" in result
    assert "llamada_pendiente" in result


def test_sin_perfil_ni_agente_no_llamada_pendiente_usa_seguimiento():
    facts = {"scheduling.call_requested": "true", "candidate.city": "Torreón"}
    result = calculate_candidate_labels(_ctx(facts))
    assert "llamada_pendiente" not in result
    assert "seguimiento" in result


def test_sin_solicitud_no_llamada_pendiente():
    result = calculate_candidate_labels(_ctx(_PERFIL_LISTO_FACTS))
    assert "llamada_pendiente" not in result


def test_llamada_pendiente_es_label_oficial():
    assert "llamada_pendiente" in OFFICIAL_LABELS


# ══════════════════════════════════════════════════════════════════════════════
# B7.5 — validación de la ventana solicitada vs horario de oficina (8:00–17:30 L–V).
# Función pura, sin reloj: clasifica el texto del candidato como dentro/fuera/no
# interpretable. Conservadora ante ambigüedad real (hora sin meridiano, día sin hora).
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("window", [
    "a las 10",
    "a las 3 de la tarde",   # 15h
    "a las 5 pm",            # 17h (dentro de 17:30)
    "el lunes a las 9",
    "por la manana",
    "a las 16 hrs",
])
def test_window_in_hours(window):
    assert classify_call_window(window) == "true"


@pytest.mark.parametrize("window", [
    "a las 7 de la noche",   # 19h
    "a las 6 pm",            # 18h
    "el sabado a las 10",    # fin de semana
    "el domingo",
    "por la noche",
    "a las 6 am",            # 6h
])
def test_window_out_of_hours(window):
    assert classify_call_window(window) == "false"


@pytest.mark.parametrize("window", [
    "a las 4",               # hora sin meridiano (1-7) ambigua
    "manana a las 4",        # mañana(día) + hora ambigua
    "el lunes",              # día hábil sin hora
    "por la tarde",          # tarde sin hora exacta (cruza 17:30)
    "cuando puedan",         # sin info
])
def test_window_unknown(window):
    assert classify_call_window(window) == "unknown"


# ══════════════════════════════════════════════════════════════════════════════
# B7.6 — integración: extractor fija scheduling.call_window_valid y la nota privada
# refleja dentro/fuera/no interpretable del horario de atención.
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.external_llm
@pytest.mark.skipif(_NO_GROQ, reason="requiere GEMINI_API_KEY — call_requested usa LLM T=0")
def test_extractor_sets_call_window_valid_true():
    facts = PE.extract_profile_facts_as_dict("me pueden llamar mañana a las 3 de la tarde")
    assert facts.get("scheduling.call_requested") == "true"
    assert facts.get("scheduling.call_window_valid") == "true"


@pytest.mark.external_llm
@pytest.mark.skipif(_NO_GROQ, reason="requiere GEMINI_API_KEY — call_requested usa LLM T=0")
def test_extractor_sets_call_window_valid_false():
    facts = PE.extract_profile_facts_as_dict("me pueden llamar a las 7 de la noche")
    assert facts.get("scheduling.call_window_valid") == "false"


@pytest.mark.external_llm
@pytest.mark.skipif(_NO_GROQ, reason="requiere GEMINI_API_KEY — call_requested usa LLM T=0")
def test_extractor_call_window_valid_unknown_sin_ventana():
    facts = PE.extract_profile_facts_as_dict("me pueden llamar?")
    assert facts.get("scheduling.call_requested") == "true"
    assert facts.get("scheduling.call_window_valid") == "unknown"


def _note_with_scheduling(valid: str, window: str = "manana a las 3 de la tarde") -> str:
    ctx = {
        "lead": {},
        "facts": {
            "scheduling.call_requested": "true",
            "scheduling.call_window_text": window,
            "scheduling.call_window_valid": valid,
        },
        "last_message": {},
        "conversation": {},
    }
    return render_candidate_note(ctx, ["bot_activo"])


def test_note_shows_call_window_dentro():
    note = _note_with_scheduling("true")
    assert "📞" in note
    assert "dentro del horario" in note.lower()
    assert "agendada" not in note.lower()  # no promete agenda real


def test_note_shows_call_window_fuera():
    note = _note_with_scheduling("false")
    assert "fuera del horario" in note.lower()


def test_note_shows_call_window_no_interpretable():
    note = _note_with_scheduling("unknown")
    assert "por confirmar" in note.lower()


def test_note_no_call_section_without_request():
    ctx = {"lead": {}, "facts": {}, "last_message": {}, "conversation": {}}
    note = render_candidate_note(ctx, ["bot_activo"])
    assert "📞" not in note
