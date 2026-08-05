"""live-business-rule-enforcement — guards deterministas del camino vivo (Fase 2).

Estos tests fijan el contrato de `openspec/changes/live-business-rule-enforcement`:
reglas de negocio que antes SOLO obligaban al shadow classifier ahora aplican en el
**camino vivo** (`knowledge_orchestrator`) vía guards deterministas (no el seed Neo4j).

Funciones bajo prueba (implementadas en Fase 2):
  - `knowledge_orchestrator._apply_business_rule_overrides(message, contract) -> contract`
      guard léxico determinista: B1/US y reingreso → requires_human; torton/rabón/reparto
      → señal escuelita y sin vehicle_type full/sencillo.
  - `knowledge_orchestrator._enforce_vigencia_lexicon(text) -> text`
      nunca deja "caduca/caducidad" en la respuesta al candidato.
  - `profile_extractor.detect_laredo_ambiguity(message) -> bool`
      "Laredo" residencia ambigua (Tamaulipas vs Texas), excepto en pregunta de ruta.
"""
from __future__ import annotations

import pytest

import app.orchestrators.knowledge_orchestrator as KO
import app.lead_memory.profile_extractor as PE


def _baseline_contract() -> dict:
    """Contrato vivo neutro, como saldría de Neo4j para un mensaje sin término sensible."""
    return {
        "route": "profile",
        "intent": "candidate_profile_signal",
        "risk_level": "low",
        "requires_human": False,
        "requires_rag": False,
    }


# ---------------------------------------------------------------------------
# A1 — B1 / Estados Unidos → handoff en el camino vivo
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("message", [
    "busco vacante B1 o para Estados Unidos",
    "quiero trabajar en USA",
    "tengo visa y quiero cruzar a EUA",
    "me interesa la ruta americana",
])
def test_b1_us_sets_requires_human_live(message):
    out = KO._apply_business_rule_overrides(message, _baseline_contract())
    assert out["requires_human"] is True


def test_b1_handoff_survives_neo4j_fallback():
    # El guard es determinista: aplica aunque el contrato venga del fallback de Neo4j
    # (sin route/intent reconocidos).
    fallback = {"route": "fallback", "intent": "unknown", "risk_level": "low", "requires_human": False}
    out = KO._apply_business_rule_overrides("busco vacante B1", fallback)
    assert out["requires_human"] is True


# ---------------------------------------------------------------------------
# A2 — Reingreso → handoff; "ya conseguí otro trabajo" NO es reingreso
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("message", [
    "ya trabajé con ustedes hace dos años",
    "quiero volver a trabajar con la empresa",
])
def test_reingreso_sets_requires_human_live(message):
    out = KO._apply_business_rule_overrides(message, _baseline_contract())
    assert out["requires_human"] is True


def test_dropoff_is_not_reingreso():
    out = KO._apply_business_rule_overrides("ya conseguí otro trabajo", _baseline_contract())
    assert out["requires_human"] is False


# ---------------------------------------------------------------------------
# A3 — Torton/rabón/reparto → escuelita, sin vehicle_type full/sencillo
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("message", [
    "manejé torton varios años",
    "trabajé en rabón y pipa",
    "hago reparto local",
])
def test_non_objective_experience_marks_escuelita_not_vehicle_type(message):
    out = KO._apply_business_rule_overrides(message, _baseline_contract())
    signals = out.get("business_signals") or []
    assert "considerar_escuelita_transmontes" in signals
    assert out["requires_human"] is True
    # No debe confirmar la unidad objetivo desde experiencia no-objetivo.
    assert out.get("explicit_vehicle_type") not in ("full", "sencillo")


@pytest.mark.external_llm
def test_cecati_signal_sets_handoff_without_funnel():
    # Sin turn_signals inyectado, cae a classify_turn_intent (LLM) para no_road_experience.
    out = KO._apply_business_rule_overrides("no tengo experiencia, quiero aprender", _baseline_contract())
    assert "cecati_sugerido" in (out.get("business_signals") or [])
    assert out["requires_human"] is True
    assert out["route"] == "human_handoff"


@pytest.mark.parametrize("intent,signals", [
    ("candidate_profile_signal", ["cecati_sugerido"]),
    ("candidate_profile_signal", ["considerar_escuelita_transmontes"]),
])
def test_no_apto_signals_skip_funnel_nudge(intent, signals):
    contract = {**_baseline_contract(), "intent": intent, "business_signals": signals}
    nudge, asked = KO._build_funnel_nudge("no tengo experiencia", contract, {"facts": []})
    assert nudge is None
    assert asked == []


# ---------------------------------------------------------------------------
# A4 — La respuesta nunca emite "caduca"/"caducidad"
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw", [
    "Tu licencia caduca el próximo mes.",
    "Revisa la caducidad de tu apto médico.",
])
def test_output_never_emits_caduca(raw):
    cleaned = KO._enforce_vigencia_lexicon(raw)
    low = cleaned.lower()
    assert "caduca" not in low and "caducidad" not in low
    assert any(w in low for w in ("vence", "vencimiento", "vigencia"))


# ---------------------------------------------------------------------------
# A5 — Laredo: residencia ambigua → desambiguar; ruta/explícito no dispara
# ---------------------------------------------------------------------------

def test_laredo_residence_is_ambiguous():
    assert PE.detect_laredo_ambiguity("soy de Laredo") is True


def test_nuevo_laredo_explicit_is_not_ambiguous():
    assert PE.detect_laredo_ambiguity("vivo en Nuevo Laredo, Tamaulipas") is False


def test_laredo_in_route_question_is_not_ambiguous():
    # Pregunta de ruta, sin marcador de residencia → no desambiguar (lo cubre el guard de geo).
    assert PE.detect_laredo_ambiguity("¿qué rutas tienen para Nuevo Laredo?") is False


def test_laredo_texas_sets_requires_human_live():
    out = KO._apply_business_rule_overrides("soy de Laredo Texas, del lado americano", _baseline_contract())
    assert out["requires_human"] is True


# ---------------------------------------------------------------------------
# B9 — costo al candidato / datos sensibles → respuesta controlada segura
# ---------------------------------------------------------------------------

import pytest  # noqa: E402


@pytest.mark.parametrize("message", [
    "¿tengo que pagar algo por el curso?",
    "me piden un depósito para empezar",
    "¿cuánto cuesta la inscripción?",
    "necesitan mi número de cuenta o clabe?",
])
def test_sensitive_or_paid_request_returns_safe_reply(message):
    out = KO._apply_business_rule_overrides(message, _baseline_contract())
    tmpl = out.get("reply_template") or {}
    assert tmpl.get("id") == "sensitive_paid_guard"
    assert out["requires_human"] is False          # no handoff; el bot aclara y sigue
    assert out.get("requires_rag") is False


@pytest.mark.parametrize("message", [
    "¿cuánto pagan a la semana?",
    "¿cuánto me pagan por kilómetro?",
    "¿el sueldo es fijo o por km?",
])
def test_salary_question_is_not_sensitive_paid(message):
    # "cuánto pagan / me pagan / sueldo" es salario (va por RAG), NO el guard de costo.
    out = KO._apply_business_rule_overrides(message, _baseline_contract())
    assert (out.get("reply_template") or {}).get("id") != "sensitive_paid_guard"
    assert out.get("reason") != "deterministic_sensitive_paid_guard"
