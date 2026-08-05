"""B2 — dominio sencillo/full/escuelita + eliminación de fifth_wheel.

Cubre: pregunta del funnel, ack visible, nota privada, blocker, scheduler,
funnel nudge variants, followup template display.
Deterministas, sin LLM ni DB.
"""
from __future__ import annotations

import os
import pytest

_NO_GROQ = not os.getenv("GEMINI_API_KEY")  # Gemini es el proveedor único

from app.knowledge.current_turn import build_current_turn_ack, next_question_from_missing_facts
from app.chatwoot_note_sync import render_candidate_note, calculate_candidate_labels
from app.followup.templates import _CAMPO_DISPLAY, render_template
from app.lead_memory.profile_extractor import extract_profile_facts_as_dict


# ── helpers ───────────────────────────────────────────────────────────────────

def _note(facts, lead=None):
    ctx = {"lead": lead or {}, "facts": facts, "last_message": {}, "conversation": {}}
    labels = calculate_candidate_labels(ctx)
    return render_candidate_note(ctx, labels)


# ── pregunta del funnel ───────────────────────────────────────────────────────

def test_funnel_pregunta_tracto_full_o_sencillo():
    """Si falta vehicle_type, la pregunta visible habla de tracto full o sencillo."""
    facts = {
        "candidate.name": "Juan Pérez",
        "candidate.city": "Torreón",
        "candidate.age": "45",
        "license.category": "E",
        "experience.years": "5 años",
    }
    q = next_question_from_missing_facts(facts)
    assert "tracto full" in q.lower() or "sencillo" in q.lower()
    assert "quinta rueda/full" not in q


def test_funnel_no_pregunta_vehicle_type_si_ya_esta():
    facts = {
        "candidate.name": "Juan Pérez",
        "candidate.city": "Torreón",
        "candidate.age": "45",
        "license.category": "E",
        "experience.years": "5 años",
        "experience.vehicle_type": "full",
    }
    q = next_question_from_missing_facts(facts)
    assert "tracto full o sencillo" not in q.lower()


# ── ack visible al candidato ──────────────────────────────────────────────────

def test_ack_sencillo_no_escuelita():
    # Sin eco de datos (feedback 2026-07-03): el ack no repite "sencillo"; solo
    # importa que no derive a escuelita.
    reply = build_current_turn_ack("manejo sencillo")
    assert "escuelita" not in reply.lower()


def test_ack_sencillo_no_quinta_rueda_full():
    reply = build_current_turn_ack("manejo sencillo")
    assert "quinta rueda/full" not in reply.lower()


def test_ack_full_no_escuelita():
    # Sin eco de datos: el ack no repite "tracto full"; solo importa que no derive
    # a escuelita.
    reply = build_current_turn_ack("manejo full")
    assert "escuelita" not in reply.lower()


def test_ack_quinta_rueda_sin_vehicle_type_no_escuelita():
    """Si el candidato dice quinta rueda sin aclarar full/sencillo, no debe decir escuelita."""
    reply = build_current_turn_ack("soy operador de quinta rueda")
    assert "escuelita" not in reply.lower()


def test_extractor_torton_persiste_non_target_sin_vehicle_type():
    facts = extract_profile_facts_as_dict("maneje torton varios anos")
    assert facts["experience.non_target_vehicle_type"] == "torton"
    assert "experience.vehicle_type" not in facts


@pytest.mark.external_llm
@pytest.mark.skipif(_NO_GROQ, reason="road_experience ahora via TIPC — requiere GROQ_API_KEY")
def test_extractor_sin_experiencia_persiste_road_experience_none():
    facts = extract_profile_facts_as_dict("no tengo experiencia en carretera")
    assert facts["experience.road_experience"] == "none"
    assert "experience.vehicle_type" not in facts


@pytest.mark.external_llm
@pytest.mark.skipif(_NO_GROQ, reason="requiere GEMINI_API_KEY — extractor usa LLM")
def test_extractor_trailer_persiste_vehicle_type_pending():
    facts = extract_profile_facts_as_dict("manejo trailer")
    assert facts["experience.vehicle_type_pending"] == "trailer"
    assert "experience.vehicle_type" not in facts


def test_extractor_b1_y_reingreso_persisten_facts():
    b1 = extract_profile_facts_as_dict("busco vacante B1 para Estados Unidos")
    reingreso = extract_profile_facts_as_dict("ya trabaje con ustedes y quiero volver")
    assert b1["experience.b1_us_intent"] == "sí"
    assert reingreso["candidate.reingreso"] == "sí"


# ── sencillo como unidad confirmada (ack prefix) ─────────────────────────────

def test_ack_sencillo_prefix_neutral():
    """El prefijo de ack para sencillo debe ser neutral, sin 'evalúa' ni 'valida viabilidad'."""
    reply = build_current_turn_ack("manejo sencillo")
    assert "evalúa" not in reply.lower()
    assert "valida viabilidad" not in reply.lower()
    assert "capital humano" not in reply.lower()


# ── nota privada — display ────────────────────────────────────────────────────

def test_nota_full_muestra_tracto_full():
    note = _note({"experience.vehicle_type": "full"})
    assert "Tracto full" in note
    assert "escuelita" not in note.lower()
    assert "fifth_wheel" not in note.lower()


def test_nota_sencillo_no_escuelita():
    note = _note({"experience.vehicle_type": "sencillo"})
    assert "escuelita" not in note.lower()
    assert "Sencillo" in note


def test_nota_sencillo_no_valida_viabilidad():
    note = _note({"experience.vehicle_type": "sencillo"})
    assert "valida viabilidad" not in note.lower()
    # "Para Capital Humano" is always the HR section header — the key is that
    # sencillo does NOT produce a handoff instruction ("canalizar", "escuelita")
    assert "canalizar" not in note.lower()
    assert "escuelita" not in note.lower()


def test_nota_pendiente_si_no_vehicle_type():
    note = _note({})
    # Note renderer shows missing fields as "No disponible" since note redesign
    assert "No disponible" in note or "Pendiente" in note
    assert "quinta rueda/full" not in note
    assert "fifth_wheel" not in note.lower()


# ── blocker: sencillo no genera blocker de unidad ────────────────────────────

def test_sencillo_no_genera_blocker_de_unidad():
    """vehicle_type=sencillo: blocker no menciona unidad pendiente."""
    note = _note({
        "experience.vehicle_type": "sencillo",
        "experience.years": "5 años",
        "license.category": "E",
        "medical.apto_status": "vigente",
        "documents.submission_status": "pending_candidate_will_send",
        "candidate.city": "Torreón",
    })
    assert "tracto full o sencillo" not in note.lower()
    assert "escuelita" not in note.lower()


def test_sin_vehicle_type_blocker_menciona_tipo_unidad():
    """years presente pero sin vehicle_type: blocker debe mencionar tipo de unidad."""
    note = _note({
        "experience.years": "5 años",
        "license.category": "E",
        "medical.apto_status": "vigente",
        "documents.labor_letters_status": "available",
        "candidate.city": "Torreón",
    })
    assert "tracto full o sencillo" in note.lower()
    assert "escuelita" not in note.lower()
    assert "valida viabilidad" not in note.lower()
    assert "fifth_wheel" not in note.lower()


def test_years_no_satisface_vehicle_type_blocker():
    """experience.years solo no completa vehicle_type — sigue faltando unidad."""
    note = _note({"experience.years": "8 años"})
    assert "tracto full o sencillo" in note.lower()


def test_fifth_wheel_legacy_no_satisface_vehicle_type():
    """fifth_wheel legacy presente pero sin vehicle_type: sigue faltando unidad."""
    note = _note({
        "experience.fifth_wheel": "sí",
        "experience.years": "5 años",
        "license.category": "E",
        "medical.apto_status": "vigente",
        "documents.labor_letters_status": "available",
        "candidate.city": "Torreón",
    })
    assert "tracto full o sencillo" in note.lower()


def test_sencillo_completo_no_blocker_unidad():
    """vehicle_type=sencillo + perfil completo: NO blocker de unidad."""
    note = _note({
        "experience.vehicle_type": "sencillo",
        "experience.years": "8 años",
        "license.category": "E",
        "medical.apto_status": "vigente",
        "documents.labor_letters_status": "available",
        "candidate.city": "Torreón",
    })
    assert "tracto full o sencillo" not in note.lower()
    assert "escuelita" not in note.lower()
    assert "valida viabilidad" not in note.lower()
    assert "canalizar" not in note.lower()


def test_full_completo_no_blocker_unidad():
    """vehicle_type=full + perfil completo: NO blocker de unidad."""
    note = _note({
        "experience.vehicle_type": "full",
        "experience.years": "10 años",
        "license.category": "E",
        "medical.apto_status": "vigente",
        "documents.labor_letters_status": "available",
        "candidate.city": "Torreón",
    })
    assert "tracto full o sencillo" not in note.lower()


# ── no referencias a fifth_wheel en nota ─────────────────────────────────────

@pytest.mark.parametrize("vt", ["full", "sencillo", ""])
def test_nota_nunca_muestra_fifth_wheel(vt):
    facts = {"experience.vehicle_type": vt} if vt else {}
    note = _note(facts)
    assert "fifth_wheel" not in note.lower()
    assert "quinta rueda/full" not in note


# ── funnel nudge variants (orchestrator) ─────────────────────────────────────

def test_funnel_nudge_variants_no_quinta_rueda_full():
    """Todas las variantes del nudge de vehicle_type usan 'tracto full o sencillo'."""
    import app.orchestrators.knowledge_orchestrator as KO
    funnel_steps = KO._FUNNEL_STEPS
    vt_step = next(s for s in funnel_steps if "experience.vehicle_type" in s.get("keys", set()))
    for variant in vt_step["variants"]:
        assert "quinta rueda/full" not in variant, f"Variante con dominio incorrecto: {variant}"
        assert "tracto full" in variant.lower() or "sencillo" in variant.lower()


def test_funnel_nudge_variants_no_escuelita():
    import app.orchestrators.knowledge_orchestrator as KO
    vt_step = next(s for s in KO._FUNNEL_STEPS if "experience.vehicle_type" in s.get("keys", set()))
    for variant in vt_step["variants"]:
        assert "escuelita" not in variant.lower()


# ── followup template display ─────────────────────────────────────────────────

def test_campo_display_no_quinta_rueda_full():
    """_CAMPO_DISPLAY no contiene el key legacy 'experiencia quinta rueda/full'."""
    assert "experiencia quinta rueda/full" not in _CAMPO_DISPLAY


def test_campo_display_tiene_tipo_unidad():
    """_CAMPO_DISPLAY mapea correctamente el nuevo key de vehicle_type."""
    assert "tipo de unidad: tracto full o sencillo" in _CAMPO_DISPLAY
    display = _CAMPO_DISPLAY["tipo de unidad: tracto full o sencillo"]
    assert "quinta rueda/full" not in display
    assert "escuelita" not in display.lower()


def test_render_template_tipo_unidad():
    """render_template con campo_faltante de vehicle_type produce texto correcto."""
    plantilla = "Hola {nombre}, falta su {campo_faltante}."
    result = render_template(plantilla, "Juan", "tipo de unidad: tracto full o sencillo")
    assert "quinta rueda/full" not in result
    assert "tipo de unidad" in result.lower()
