from __future__ import annotations

import os

import pytest

from app.knowledge.current_turn import (
    build_current_turn_ack,
    is_age_disqualified,
    next_question_from_missing_facts,
)
from app.knowledge.guard_asked_field import asked_field_keys_for_guard
from app.lead_memory.profile_extractor import extract_profile_facts_as_dict as facts
from app.chatwoot_note_sync import calculate_candidate_labels, render_candidate_note
from app.settings import AGE_DISQUALIFICATION_LIMIT

_NO_GROQ = not os.getenv("GEMINI_API_KEY")  # Gemini es el proveedor único


def _ctx(f):
    return {"lead": {}, "facts": f, "last_message": {}, "conversation": {}}


def test_funnel_order_city_then_age_then_unit_then_license_then_apto_then_years_then_docs():
    assert "nombre" in next_question_from_missing_facts({}).lower()

    q = next_question_from_missing_facts({"candidate.name": "Juan Pérez"})
    assert "ciudad" in q.lower()

    q = next_question_from_missing_facts({"candidate.name": "Juan Pérez", "candidate.city": "Torreon"})
    assert "edad" in q.lower() or "años tiene" in q.lower()
    assert asked_field_keys_for_guard(
        {"candidate.name": "Juan Pérez", "candidate.city": "Torreon"}
    ) == ["candidate.age"]

    q = next_question_from_missing_facts({
        "candidate.name": "Juan Pérez", "candidate.city": "Torreon", "candidate.age": "45",
    })
    assert "tracto full" in q.lower() and "sencillo" in q.lower()

    q = next_question_from_missing_facts({
        "candidate.name": "Juan Pérez",
        "candidate.city": "Torreon",
        "candidate.age": "45",
        "experience.vehicle_type": "full",
    })
    assert "licencia federal" in q.lower()
    assert "vence" in q.lower()

    q = next_question_from_missing_facts({
        "candidate.name": "Juan Pérez",
        "candidate.city": "Torreon",
        "candidate.age": "45",
        "experience.vehicle_type": "full",
        "license.category": "E",
        "license.expiration_text": "vence en 1 año",
    })
    assert "apto" in q.lower()
    assert "vence" in q.lower()

    q = next_question_from_missing_facts({
        "candidate.name": "Juan Pérez",
        "candidate.city": "Torreon",
        "candidate.age": "45",
        "experience.vehicle_type": "full",
        "license.category": "E",
        "license.expiration_text": "vence en 1 año",
        "medical.apto_expiration_text": "vence en 1 año",
    })
    assert "años de experiencia" in q.lower()

    q = next_question_from_missing_facts({
        "candidate.name": "Juan Pérez",
        "candidate.city": "Torreon",
        "candidate.age": "45",
        "experience.vehicle_type": "full",
        "license.category": "E",
        "license.expiration_text": "vence en 1 año",
        "medical.apto_expiration_text": "vence en 1 año",
        "experience.years": "10 años",
    })
    assert "cartas" in q.lower() or "imss" in q.lower()


def test_age_at_limit_is_disqualified():
    # Límite: AGE_DISQUALIFICATION_LIMIT = 57 (settings.py); 57+ = no apto.
    assert is_age_disqualified({"candidate.age": "57"})
    assert is_age_disqualified({"candidate.age": "60"})
    assert not is_age_disqualified({"candidate.age": "56"})
    assert not is_age_disqualified({"candidate.age": "49"})


def test_age_disqualified_reply_is_non_empty():
    # El mensaje lo genera el LLM (persona_config); solo verificamos que no sea vacío
    # y que no contenga una pregunta de funnel.
    reply = next_question_from_missing_facts({
        "candidate.city": "Torreon",
        "candidate.age": "57",
    })
    assert reply  # no vacío
    # No debe continuar con pregunta de funnel (tipo de unidad, licencia, etc.)
    assert "tracto full" not in reply.lower()
    assert "licencia" not in reply.lower() or "años" not in reply.lower()


def test_age_under_limit_continues():
    under_limit = AGE_DISQUALIFICATION_LIMIT - 1
    q = next_question_from_missing_facts({
        "candidate.name": "Juan Pérez", "candidate.city": "Torreon", "candidate.age": str(under_limit),
    })
    assert "tracto full" in q.lower()


@pytest.mark.external_llm
@pytest.mark.skipif(_NO_GROQ, reason="requiere GROQ_API_KEY — profile_extractor usa LLM T=0")
def test_expiration_extraction_relative_and_date():
    d = facts("mi licencia vence el 31 de diciembre de 2027")
    assert d["license.expiration_text"] == "31 de diciembre de 2027"

    d = facts("el apto se me vence como en dos meses")
    assert d["medical.apto_expiration_text"] == "vence en 2 meses"


def test_vigente_without_expiration_reprompts_time():
    q = next_question_from_missing_facts({
        "candidate.name": "Juan Pérez",
        "candidate.city": "Torreon",
        "candidate.age": "45",
        "experience.vehicle_type": "full",
        "license.category": "E",
        "license.status": "vigente",
    })
    assert "en cuánto tiempo se le vence su licencia" in q.lower()


def test_short_expiry_triggers_fixed_renewal_branch():
    base = {
        "candidate.name": "Juan Pérez",
        "candidate.city": "Torreon",
        "candidate.age": "45",
        "experience.vehicle_type": "full",
        "license.category": "E",
        "license.expiration_text": "vence en 18 días",
    }
    # Vencimiento próximo → ofrece la alternativa de comprobante de pago (Bloque 2).
    assert "comprobante de pago" in next_question_from_missing_facts(base).lower()

    no_paper = {**base, "documents.renewal_proof": "no"}
    q = next_question_from_missing_facts(no_paper)
    assert "en cuanto lo tenga" in q.lower()
    assert "seguimos" in q.lower()


def test_age_discard_visible_in_note_without_review_labels_or_bot_activo():
    f = {"candidate.age": str(AGE_DISQUALIFICATION_LIMIT), "candidate.city": "Torreon"}
    labels = calculate_candidate_labels(_ctx(f))
    assert "bot_activo" not in labels
    assert "requiere_revision_ch" not in labels
    # Descarte por edad SHALL tener rastro de label (Bloque 5): descartado_edad.
    assert labels == ["descartado_edad"]
    note = render_candidate_note(_ctx(f), labels)
    assert "Fuera de Perfil por Edad" in note


# ── Task 1.1: "todo en regla / todo bien" NO confirma vigencia ────────────────

def test_en_regla_no_confirma_licencia_vigente():
    # "mi licencia está en regla" es ambiguo — no debe persistir license.status
    d = facts("mi licencia está en regla")
    assert "license.status" not in d, f"'en regla' no debe confirmar vigencia: {d}"


def test_todo_en_regla_no_confirma_nada():
    # Afirmación global sin fecha/vigencia específica
    d = facts("tengo todo en regla")
    assert "license.status" not in d
    assert "medical.apto_status" not in d


def test_todo_bien_no_confirma_vigencia():
    d = facts("todo bien, licencia y apto")
    assert "license.status" not in d
    assert "medical.apto_status" not in d


@pytest.mark.external_llm
def test_en_regla_con_licencia_y_fecha_si_confirma():
    # Con dato específico de vigencia el registro SÍ debe ocurrir
    d = facts("licencia tipo E vigente, vence en 1 año")
    assert d.get("license.status") == "vigente"
    assert d.get("license.expiration_text") is not None


# ── Task 1.2: documents.proof como fact canónico ──────────────────────────────

def test_cartas_persistidas_como_documents_proof():
    d = facts("sí tengo cartas laborales")
    assert d.get("documents.proof") == "cartas", f"esperaba cartas, got: {d}"


def test_imss_persistido_como_documents_proof():
    d = facts("tengo mis semanas del IMSS")
    assert d.get("documents.proof") == "semanas_imss", f"esperaba semanas_imss, got: {d}"


def test_semanas_cotizadas_es_semanas_imss():
    d = facts("cuento con semanas cotizadas")
    assert d.get("documents.proof") == "semanas_imss"


def test_sin_cartas_persiste_ninguno_para_ofrecer_alternativa():
    # Bloque 2 (D3): la negativa SÍ persiste "ninguno" para poder ofrecer la
    # alternativa (IMSS↔cartas según residencia) — antes no persistía nada.
    d = facts("no tengo cartas")
    assert d.get("documents.proof") == "ninguno"


# ── Task 1.3: tramite_comprobante ─────────────────────────────────────────────

@pytest.mark.external_llm
def test_licencia_vencida_con_comprobante_marca_tramite():
    d = facts("mi licencia está vencida pero tengo comprobante de cita")
    assert d.get("license.tramite_comprobante") == "true", f"got: {d}"


@pytest.mark.external_llm
def test_apto_vencido_con_cita_marca_tramite():
    d = facts("el apto está vencido ya pagué la cita")
    assert d.get("medical.tramite_comprobante") == "true", f"got: {d}"


def test_vencido_sin_comprobante_no_marca_tramite():
    d = facts("mi licencia está vencida")
    assert d.get("license.tramite_comprobante") is None


# ── Tasks 2.1 / 2.4 / 2.5: funnel como ciclo — inferencia y documento ────────

def test_funnel_skips_already_provided_facts():
    # 2.1: funnel no re-pregunta edad ni unidad ni experiencia ya dadas
    f = {
        "candidate.name": "Juan Pérez",
        "candidate.age": "35",
        "experience.vehicle_type": "full",
        "experience.years": "10 años",
    }
    q = next_question_from_missing_facts(f)
    assert "ciudad" in q.lower(), f"esperaba preguntar ciudad, got: {q!r}"
    assert "edad" not in q.lower()
    assert "tracto full" not in q.lower()
    assert "años de experiencia" not in q.lower()


def test_funnel_licencia_b_ofrece_sencillo():
    # 2.4: con licencia B, la pregunta de unidad debe orientar a sencillo
    f = {
        "candidate.name": "Juan Pérez",
        "candidate.city": "Torreon",
        "candidate.age": "45",
        "license.category": "B",
        "license.expiration_text": "vence en 1 año",
        "medical.apto_expiration_text": "vence en 1 año",
        "experience.years": "5 años",
    }
    q = next_question_from_missing_facts(f)
    assert "sencillo" in q.lower(), f"B debe ofrecer sencillo, got: {q!r}"
    assert "full" not in q.lower(), f"B no debe ofrecer full, got: {q!r}"


def test_funnel_licencia_e_ofrece_ambas():
    # 2.4: con licencia E, la pregunta de unidad debe ofrecer full o sencillo
    f = {
        "candidate.name": "Juan Pérez",
        "candidate.city": "Torreon",
        "candidate.age": "45",
        "license.category": "E",
        "license.expiration_text": "vence en 1 año",
        "medical.apto_expiration_text": "vence en 1 año",
        "experience.years": "5 años",
    }
    q = next_question_from_missing_facts(f)
    assert "full" in q.lower() and "sencillo" in q.lower(), f"E debe ofrecer ambas, got: {q!r}"


def test_funnel_documento_local_acepta_imss():
    # 2.5: candidato local de ZM Laguna — pregunta debe incluir IMSS
    f = {
        "candidate.name": "Juan Pérez",
        "candidate.city": "Torreon",
        "candidate.age": "45",
        "experience.vehicle_type": "full",
        "license.category": "E",
        "license.expiration_text": "vence en 1 año",
        "medical.apto_expiration_text": "vence en 1 año",
        "experience.years": "10 años",
    }
    q = next_question_from_missing_facts(f)
    assert "imss" in q.lower(), f"local debe ofrecer IMSS, got: {q!r}"


def test_funnel_documento_foraneo_exige_cartas_membretadas():
    # 2.5: candidato foráneo — pregunta debe exigir cartas membretadas
    f = {
        "candidate.name": "Juan Pérez",
        "candidate.city": "Monterrey",
        "candidate.age": "45",
        "experience.vehicle_type": "full",
        "license.category": "E",
        "license.expiration_text": "vence en 1 año",
        "medical.apto_expiration_text": "vence en 1 año",
        "experience.years": "10 años",
    }
    q = next_question_from_missing_facts(f)
    assert "membretada" in q.lower(), f"foráneo debe pedir membretadas, got: {q!r}"
    assert "imss" not in q.lower(), f"foráneo no debe mencionar IMSS, got: {q!r}"


def test_vehicle_question_with_license_b_targets_sencillo():
    f = {
        "candidate.name": "Juan Pérez",
        "candidate.city": "Torreón",
        "candidate.age": "45",
        "license.category": "B",
    }
    q = next_question_from_missing_facts(f)
    assert "licencia tipo b" in q.lower()
    assert "sencillo" in q.lower()
    assert "full" not in q.lower()


def test_vehicle_question_with_license_e_mentions_sencillo_and_full():
    f = {
        "candidate.name": "Juan Pérez",
        "candidate.city": "Torreón",
        "candidate.age": "45",
        "license.category": "E",
    }
    q = next_question_from_missing_facts(f)
    assert "licencia tipo e" in q.lower()
    assert "sencillo" in q.lower()
    assert "full" in q.lower()


def test_license_question_for_full_requires_e():
    f = {
        "candidate.name": "Juan Pérez",
        "candidate.city": "Torreón",
        "candidate.age": "45",
        "experience.vehicle_type": "full",
    }
    q = next_question_from_missing_facts(f)
    assert "tipo e" in q.lower()
    assert "cuándo vence" in q.lower()


def test_license_question_for_sencillo_accepts_b_or_e():
    f = {
        "candidate.name": "Juan Pérez",
        "candidate.city": "Torreón",
        "candidate.age": "45",
        "experience.vehicle_type": "sencillo",
    }
    q = next_question_from_missing_facts(f)
    assert "tipo b o e" in q.lower()
    assert "cuándo vence" in q.lower()


def test_document_requirement_note_local():
    from app.knowledge.current_turn import residency_document_requirement_note
    note = residency_document_requirement_note({"candidate.city": "Torreón"})
    assert "imss" in note.lower()
    assert "foraneo" not in note.lower()


def test_document_requirement_note_foraneo():
    from app.knowledge.current_turn import residency_document_requirement_note
    note = residency_document_requirement_note({"candidate.city": "Monterrey"})
    assert "membretada" in note.lower()
    assert "imss" not in note.lower()


def test_document_requirement_note_unknown_residency_is_conditional():
    from app.knowledge.current_turn import residency_document_requirement_note
    note = residency_document_requirement_note({})
    assert "si es local" in note.lower()
    assert "si es foráneo" in note.lower()


# ── Task 2.3: no re-saludar ni re-preguntar dato ya confirmado ────────────────

def test_greeting_first_time_sends_full_presentation():
    # 2.3: primera visita — saludo completo con presentación de Mundo. El nombre es
    # el primer campo del funnel (antes que ciudad).
    from app.orchestrators.knowledge_orchestrator import _greeting_reply
    reply = _greeting_reply({"facts": []})
    assert "mundo" in reply.lower(), f"primer turno debe incluir 'Mundo': {reply!r}"
    assert "nombre" in reply.lower(), f"primer turno debe pedir nombre: {reply!r}"


def test_greeting_returning_skips_city_if_already_given():
    # 2.3: candidato con nombre y ciudad registrados — vuelta no debe re-pedirlos,
    # pasa al siguiente campo pendiente (edad).
    from app.orchestrators.knowledge_orchestrator import _greeting_reply
    lead_mem = {"facts": [
        {"fact_group": "candidate", "fact_key": "name", "fact_value": "Juan Pérez"},
        {"fact_group": "candidate", "fact_key": "city", "fact_value": "Torreon"},
    ]}
    reply = _greeting_reply(lead_mem)
    assert "ciudad" not in reply.lower(), f"no debe pedir ciudad: {reply!r}"
    assert "años" in reply.lower(), f"debe pedir edad como siguiente campo: {reply!r}"


def test_greeting_returning_no_full_presentation():
    # 2.3: bienvenida de regreso no incluye presentación completa
    from app.orchestrators.knowledge_orchestrator import _greeting_reply
    lead_mem = {"facts": [{"fact_group": "candidate", "fact_key": "city", "fact_value": "Torreon"}]}
    reply = _greeting_reply(lead_mem)
    assert "soy mundo" not in reply.lower(), f"regreso no debe repetir presentación: {reply!r}"


def test_greeting_returning_profile_complete_no_full_greeting():
    # 2.3: candidato con perfil completo — no repite GREETING_REPLY completo
    from app.orchestrators.knowledge_orchestrator import _greeting_reply, GREETING_REPLY
    lead_mem = {"facts": [
        {"fact_group": "candidate", "fact_key": "city", "fact_value": "Torreon"},
        {"fact_group": "candidate", "fact_key": "age", "fact_value": "35"},
        {"fact_group": "experience", "fact_key": "vehicle_type", "fact_value": "full"},
        {"fact_group": "license", "fact_key": "category", "fact_value": "E"},
        {"fact_group": "license", "fact_key": "expiration_text", "fact_value": "1 año"},
        {"fact_group": "medical", "fact_key": "apto_expiration_text", "fact_value": "1 año"},
        {"fact_group": "experience", "fact_key": "years", "fact_value": "10"},
        {"fact_group": "documents", "fact_key": "proof", "fact_value": "cartas"},
    ]}
    reply = _greeting_reply(lead_mem)
    assert reply != GREETING_REPLY, "no debe ser idéntico al saludo inicial"
    assert "soy mundo" not in reply.lower(), f"no debe repetir presentación: {reply!r}"


# ── Pre-handoff condicional: tests por rama ───────────────────────────────────

def test_escuelita_sin_licencia_pregunta_licencia():
    # 2.1: escuelita sin licencia B/E → pregunta licencia
    from app.knowledge.current_turn import next_prehandoff_question
    q = next_prehandoff_question("escuelita", {})
    assert q is not None, "sin licencia debe preguntar"
    assert "licencia" in q.lower() and ("b" in q.lower() or "e" in q.lower()), f"debe mencionar B/E: {q!r}"


def test_escuelita_con_licencia_b_handoff():
    # 2.3: escuelita con licencia B → no pregunta (handoff puede proceder)
    from app.knowledge.current_turn import next_prehandoff_question
    q = next_prehandoff_question("escuelita", {"license.category": "B"})
    assert q is None, f"con licencia B debe retornar None: {q!r}"


def test_escuelita_con_licencia_e_handoff():
    # 2.3: escuelita con licencia E → None (handoff)
    from app.knowledge.current_turn import next_prehandoff_question
    q = next_prehandoff_question("escuelita", {"license.category": "E"})
    assert q is None, f"con licencia E debe retornar None: {q!r}"


def test_b1_sin_unidad_pregunta_unidad():
    # 3.1: B1 sin vehicle_type → pregunta unidad
    from app.knowledge.current_turn import next_prehandoff_question
    q = next_prehandoff_question("b1", {})
    assert q is not None and ("full" in q.lower() or "sencillo" in q.lower()), f"debe preguntar unidad: {q!r}"


def test_b1_con_todos_datos_handoff():
    # 3.3: B1 con unidad + licencia + apto → handoff
    from app.knowledge.current_turn import next_prehandoff_question
    facts = {
        "experience.vehicle_type": "full",
        "license.category": "E",
        "license.expiration_text": "1 año",
        "medical.apto_expiration_text": "1 año",
    }
    q = next_prehandoff_question("b1", facts)
    assert q is None, f"con datos completos debe retornar None: {q!r}"


def test_reingreso_sin_tipo_vacante_pregunta():
    # 4.1: reingreso sin tipo_vacante → pregunta
    from app.knowledge.current_turn import next_prehandoff_question
    q = next_prehandoff_question("reingreso", {})
    assert q is not None and ("operador" in q.lower() or "vacante" in q.lower()), f"debe preguntar tipo: {q!r}"


def test_reingreso_con_tipo_vacante_handoff():
    # 4.3: reingreso con tipo_vacante confirmado → None
    from app.knowledge.current_turn import next_prehandoff_question
    q = next_prehandoff_question("reingreso", {"reingreso.tipo_vacante": "operador"})
    assert q is None, f"con tipo_vacante debe retornar None: {q!r}"
