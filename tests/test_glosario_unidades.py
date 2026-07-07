"""Glosario ampliado de unidades (gemini-natural-recruiter, Bloque 1).

Reglas de negocio 2026-07-07 (conv 163): doble articulado/doble→full; caja seca→sencillo
(validado por el resumen de confirmación); "recién renovada" NO es plazo de vencimiento.
Deterministas: sin LLM ni BD (la extracción se construye como la emitiría el LLM según
los few-shots).
"""
from __future__ import annotations

from app.knowledge.normalize_domain_values import normalize_vehicle
from app.knowledge.turn_extractor import FieldValue, TurnExtraction, validate_extraction
from app.knowledge.turn_intent_classifier import TurnIntentSignals
from app.knowledge.current_turn import next_question_from_missing_facts


# ── catálogo: doble articulado / doble / caja seca ────────────────────────────

def test_doble_articulado_es_full():
    res = normalize_vehicle("manejo doble articulado")
    assert res is not None and res.value == "full" and res.status == "confirmed"


def test_doble_solo_es_full():
    res = normalize_vehicle("traigo doble")
    assert res is not None and res.value == "full"


def test_caja_seca_es_sencillo():
    res = normalize_vehicle("manejo caja seca")
    assert res is not None and res.value == "sencillo" and res.status == "confirmed"


def test_terminos_previos_intactos():
    assert normalize_vehicle("fulero").value == "full"
    assert normalize_vehicle("quinta rueda").value is None  # sigue needs_clarification
    assert normalize_vehicle("torton").status == "non_target"


# ── L2: "renovada" no es plazo; los demás campos del turno sobreviven ────────

def _facts_dict(out):
    return {f"{r['fact_group']}.{r['fact_key']}": r["fact_value"] for r in out}


def test_conv163_e_doble_articulado_recien_renovada():
    # Extracción como la emitiría el LLM según el few-shot del prompt.
    ext = TurnExtraction(
        fields={
            "license.category": FieldValue(value="E", explicit_marker=True),
            "experience.vehicle_type": FieldValue(value="doble articulado", explicit_marker=True),
        },
        signals=TurnIntentSignals(),
    )
    facts = _facts_dict(validate_extraction(ext, {}))
    assert facts.get("license.category") == "E"
    assert facts.get("experience.vehicle_type") == "full"  # mapeado por catálogo
    assert "license.expiration_text" not in facts


def test_renovada_como_plazo_se_descarta_sin_perder_categoria():
    # Aunque el LLM emitiera "recién renovada" como plazo, L2 lo descarta y conserva
    # el resto del turno.
    ext = TurnExtraction(
        fields={
            "license.category": FieldValue(value="E", explicit_marker=True),
            "license.expiration_text": FieldValue(value="recién renovada", explicit_marker=True),
        },
        signals=TurnIntentSignals(),
    )
    facts = _facts_dict(validate_extraction(ext, {}))
    assert facts.get("license.category") == "E"
    assert "license.expiration_text" not in facts


def test_apto_renovado_tambien_se_descarta_como_plazo():
    ext = TurnExtraction(
        fields={"medical.apto_expiration_text": FieldValue(value="renovada", explicit_marker=True)},
        signals=TurnIntentSignals(),
    )
    facts = _facts_dict(validate_extraction(ext, {}))
    assert "medical.apto_expiration_text" not in facts


# ── regresión funnel (bug conv 163): NO re-pregunta tipo ni unidad ────────────

def test_funnel_tras_doble_articulado_pregunta_solo_plazo():
    facts = {
        "candidate.name": "José Luis Guerra",
        "candidate.city": "Cadereyta",
        "candidate.age": "33",
        "experience.vehicle_type": "full",   # mapeado de "doble articulado"
        "license.category": "E",             # dado en el mismo turno
        # sin license.expiration_text ("recién renovada" no es plazo)
    }
    q = next_question_from_missing_facts(facts)
    assert "vence su licencia" in q.lower()          # pregunta SOLO el plazo
    assert "tipo de licencia" not in q.lower()        # NO re-pregunta el tipo
    assert "full o" not in q.lower()                  # NO re-pregunta la unidad
