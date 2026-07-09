"""QA harness read-only para la matriz de preguntas reales.

Lee tests/fixtures/response_qa/matriz_qa.csv y produce un reporte CSV con el
resultado de cada caso contra el sistema actual.

Modos:
  --mode dry       (default) Solo verifica frases_prohibidas contra
                   agent_answer_historica. Sin LLM, sin DB.
  --mode classify  Llama classify_message() por cada pregunta y compara
                   primary/secondary intents contra route_esperada_sugerida.
                   Requiere GEMINI_API_KEY en entorno.
  --mode full      classify + plan_and_respond. Requiere GEMINI_API_KEY.

Flag shadow:
  --include-business-shadow
                   Activa el shadow del extractor unificado en CUALQUIER modo.
                   Agrega columnas business_* al reporte. Requiere GEMINI_API_KEY.
                   Shadow es read-only: no escribe DB, Chatwoot ni labels.
                   En --mode dry fuerza 1 LLM call/fila (solo extractor).
                   En --mode classify/full agrega ~1 LLM call/fila extra.

mapping_status:
  PASS_STRONG    primary o secondary coincide con intent fuerte de la ruta.
  PASS_WEAK      coincide solo por intent amplio; falta business_route para confirmar.
  REVIEW_MAPPING ningún match; conversacionalmente razonable pero no confirmado.
  CONTRACT_GAP   ruta sin mapping definido.
  ERROR          excepción técnica.

Límites Gemini free observados:
  usar cadencia conservadora aunque el modelo tenga más RPM nominal.
  Default --requests-per-minute 3.0 → sleep_by_rpm=20s → effective 20s

Corrida por bloques:
  --start-index 0  --limit 25 --append --output reports/qa_all.csv
  --start-index 25 --limit 25 --append --output reports/qa_all.csv

READ-ONLY: no escribe en Chatwoot, no muta DB, no envía mensajes reales.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import traceback
from collections import Counter
from pathlib import Path
from typing import Any

# ── Paths ─────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent

# Shadow del extractor unificado — wrapper lazy a nivel módulo.
# El nombre conserva compatibilidad con tests/reportes previos, pero ya NO importa
# el classifier retirado. La fuente del shadow es turn_extractor + Capa 2.
def classify_business_route_shadow(*args, **kwargs):  # type: ignore[misc]
    from app.knowledge.business_route_schema import (  # noqa: PLC0415
        AmbiguityFlag,
        BusinessRouteOutput,
        BusinessSignal,
        ExplicitFact,
        RequestedInfoItem,
    )
    from app.knowledge.turn_extractor import extract_turn, validate_extraction  # noqa: PLC0415

    text = kwargs.get("text")
    if text is None and args:
        text = args[0]
    text = str(text or "")
    conv_cls = kwargs.get("conversational_classification") or {}

    extraction = extract_turn(text)
    facts = validate_extraction(extraction)

    out = BusinessRouteOutput()
    out.conversational_intents = [
        i for i in [
            conv_cls.get("primary_intent"),
            *(conv_cls.get("secondary_intents") or []),
        ] if i
    ]

    for fact in facts:
        key = f"{fact.get('fact_group')}.{fact.get('fact_key')}"
        value = str(fact.get("fact_value") or "")
        out.explicit_facts[key] = ExplicitFact(
            field=key,
            value=value,
            evidence=value,
            confidence=float(fact.get("confidence") or 0.0),
        )

    text_l = text.lower()
    intents = set(out.conversational_intents)

    def add_signal(name: str, evidence: str = "", confidence: float = 0.85) -> None:
        if not out.has_signal(name):
            out.business_signals.append(BusinessSignal(name=name, evidence=evidence, confidence=confidence))

    def add_requested(category: str, evidence: str = "") -> None:
        if category not in {r.category for r in out.requested_info}:
            out.requested_info.append(RequestedInfoItem(category=category, evidence=evidence))

    if "experience.vehicle_type" in out.explicit_facts:
        add_signal("objetivo_full_sencillo", out.explicit_facts["experience.vehicle_type"].evidence, 0.9)
    if "experience.vehicle_type_raw" in out.explicit_facts:
        out.ambiguity_flags.append(AmbiguityFlag(name="vehicle_type_ambiguous", evidence=out.explicit_facts["experience.vehicle_type_raw"].evidence))
    if "sencillo" in text_l:
        add_signal("objetivo_full_sencillo", "sencillo", 0.88)
    if any(
        term in text_l
        for term in (
            "escuelita",
            "torton",
            "carta de recomendación",
            "carta de recomendacion",
            "apto medico",
            "apto médico",
        )
    ):
        add_signal("considerar_escuelita_transmontes", text, 0.86)
    if any(
        term in text_l
        for term in (
            "solicitando",
            "en espera",
            "seguir con el proceso",
            "seguir el proceso",
            "citas",
            "cita",
            "interesado",
            "interesada",
        )
    ):
        add_signal("seguimiento_llamada", text, 0.82)
    if any(
        term in text_l
        for term in (
            "prestaciones",
            "fondo de ahorro",
            "horario",
            "descanso",
            "pagada",
            "paga",
            "pagan",
            "sueldo",
            "salario",
        )
    ):
        add_signal("pago_condiciones", text, 0.84)
    if any(
        term in text_l
        for term in (
            "5ta rueda",
            "quinta rueda",
            "op 5ta rueda",
            "operador 5ta rueda",
        )
    ):
        add_signal("jerga_ambigua_falta_unidad", text, 0.84)
    if extraction.signals.no_road_experience:
        add_signal("cecati_sugerido", "sin experiencia", 0.8)
    if extraction.signals.call_requested or "call_requested" in intents:
        add_signal("seguimiento_llamada", "llamada", 0.8)
    if "reingreso" in intents or any(w in text_l for w in ("reingreso", "trabajé antes", "trabaje antes", "ya trabajé", "ya trabaje")):
        add_signal("reingreso_verificar", "reingreso", 0.9)
        out.requires_human = True
        out.profile_context_action = "escalate_to_human"
    if "b1" in text_l or "visa" in text_l or "estados unidos" in text_l or "usa" in text_l:
        add_signal("considerar_operador_b1", "B1/visa/EEUU", 0.8)
        out.requires_human = True
        out.profile_context_action = "escalate_to_human"

    embedded = (extraction.embedded_question or text).lower()
    if "pay_question" in intents or any(w in embedded for w in ("pago", "pagan", "sueldo", "nómina", "nomina", "viático", "viatico", "kilómetro", "kilometro", "km")):
        add_signal("pago_condiciones", extraction.embedded_question or "", 0.85)
        add_requested("salary", extraction.embedded_question or "")
    if "logistics_question" in intents or any(w in embedded for w in ("ruta", "tramo", "base", "patio", "laredo", "mty", "monterrey", "traslado", "descanso")):
        add_signal("ubicacion_base_traslado", extraction.embedded_question or "", 0.85)
        add_requested("route_details", extraction.embedded_question or "")
    if "documents_question" in intents or any(w in embedded for w in ("documento", "requisito", "licencia", "apto", "cartas", "imss")):
        add_signal("documentos_requisitos", extraction.embedded_question or "", 0.85)
        add_requested("documents_required", extraction.embedded_question or "")
    if "vacancy_question" in intents or any(w in embedded for w in ("vacante", "información", "informacion", "operador especializado")):
        add_signal("vacante_info_general", extraction.embedded_question or "", 0.85)
        add_requested("vacancy_information", extraction.embedded_question or "")

    return out
DEFAULT_INPUT = REPO_ROOT / "tests/fixtures/response_qa/matriz_qa.csv"
DEFAULT_OUTPUT = REPO_ROOT / "reports/qa_response_matrix.csv"

# ── Frases prohibidas globales ─────────────────────────────────────────────────
# Verificación literal; no regex. Cualquier respuesta que contenga una de estas
# frases falla independientemente del modo.

GLOBAL_FORBIDDEN: list[str] = [
    "quinta rueda/full",
    "sencillo (escuelita)",
    "Capital Humano valida viabilidad",
    "disponible_acudir",
    "caduca",
    "caducidad",
    "tenemos convenio con CECATI",
]

# ── Mapping de intents por ruta (evaluación QA — no lógica productiva) ────────
#
# ROUTE_STRONG: intents que solos (primary o secondary) confirman la ruta → PASS_STRONG
# ROUTE_WEAK:   intents que coinciden ampliamente pero necesitan business_route → PASS_WEAK
# None en ROUTE_STRONG = wildcard (otros_rag) → siempre PASS_STRONG
#
# Regla de evaluación:
#  1. any(intent in ROUTE_STRONG[route])  → PASS_STRONG (source=primary|secondary)
#  2. any(intent in ROUTE_WEAK[route])    → PASS_WEAK   (source=primary|secondary)
#  3. ninguno                             → REVIEW_MAPPING
#  4. route no en ninguna tabla           → CONTRACT_GAP

ROUTE_STRONG: dict[str, set[str] | None] = {
    "vacante_info_general": {
        "greeting", "candidate_interest", "vacancy_question", "acknowledgement",
    },
    "ubicacion_base_traslado": {
        "logistics_question", "candidate_answer", "on_route",
    },
    "documentos_requisitos": {
        "documents_question", "document_submission", "candidate_answer",
    },
    "pago_condiciones": {
        "pay_question",
    },
    "objetivo_full_sencillo": {
        "candidate_answer",
    },
    "considerar_escuelita_transmontes": {
        "candidate_answer", "vacancy_question",
    },
    "jerga_ambigua_falta_unidad": {
        "candidate_answer",
    },
    "cecati_sugerido": {
        "candidate_answer", "vacancy_question", "greeting",
    },
    "considerar_operador_b1": {
        "candidate_answer", "candidate_interest",
    },
    "seguimiento_llamada": {
        "candidate_answer", "acknowledgement", "candidate_interest",
    },
    "reingreso_verificar": {
        "reingreso", "candidate_answer", "candidate_interest", "vacancy_question",
    },
    "otros_rag": None,  # wildcard
}

# ROUTE_WEAK: match amplio → PASS_WEAK (no CONTRACT_GAP, pero necesita confirmación)
ROUTE_WEAK: dict[str, set[str]] = {
    "vacante_info_general":             {"documents_question"},
    "ubicacion_base_traslado":          {"vacancy_question"},
    "documentos_requisitos":            {"vacancy_question"},
    "pago_condiciones":                 {"vacancy_question", "candidate_interest"},
    "objetivo_full_sencillo":           {"candidate_interest", "vacancy_question", "logistics_question"},
    "considerar_escuelita_transmontes": set(),   # document_submission solo → REVIEW_MAPPING
    "jerga_ambigua_falta_unidad":       {"vacancy_question", "logistics_question"},
    "cecati_sugerido":                  set(),
    "considerar_operador_b1":           {"vacancy_question"},
    "seguimiento_llamada":              set(),   # out_of_scope removido
    "reingreso_verificar":              set(),
}

OUTPUT_COLUMNS = [
    "qa_id", "candidate_question", "route_esperada_sugerida",
    "labels_esperadas_sugeridas", "prioridad",
    # Compat
    "actual_intent",
    # Extendidas
    "actual_primary_intent",
    "actual_secondary_intents",
    "actual_answers",
    "actual_business_route",
    "actual_labels",
    "actual_reply",
    "pass_forbidden_phrases",
    # Evaluación de ruta
    "mapping_status",
    "mapping_strength",
    "match_source",
    "matched_intents",
    # Hechos de negocio extraídos del texto
    "profile_vehicle_type",
    "business_fact_match",
    # Compat
    "pass_route",
    "status",
    "comment",
]

# Columnas del business route shadow classifier (se agregan solo con --include-business-shadow)
SHADOW_COLUMNS = [
    # JSON completo (evidencia + confidence)
    "business_requested_info",
    "business_explicit_facts",
    "business_signals",
    "business_ambiguity_flags",
    "business_policy_answer_keys",
    "business_validation_errors",
    # Escalares / flat (para grep/filtro rápido)
    "business_requires_human",
    "business_profile_action",
    "business_signal_names",
    "business_requested_info_topics",
    "business_fact_keys",
    "business_ambiguity_names",
    "business_shadow_status",
    "business_shadow_error",
    "profile_context_available",
]

_SHADOW_EMPTY: dict[str, Any] = {
    "business_requested_info": "[]",
    "business_explicit_facts": "{}",
    "business_signals": "[]",
    "business_ambiguity_flags": "[]",
    "business_policy_answer_keys": "[]",
    "business_validation_errors": "[]",
    "business_requires_human": "",
    "business_profile_action": "",
    "business_signal_names": "",
    "business_requested_info_topics": "",
    "business_fact_keys": "",
    "business_ambiguity_names": "",
    "business_shadow_status": "",
    "business_shadow_error": "",
    "profile_context_available": "false",
}

SHADOW_TOKENS_ESTIMATE = 1200  # aprox tokens por llamada al extractor unificado


# ── Helpers — forbidden phrases ───────────────────────────────────────────────

def _parse_forbidden(cell: str | None) -> list[str]:
    if not cell:
        return []
    return [f.strip() for f in cell.split(";") if f.strip()]


def _check_forbidden(text: str | None, forbidden: list[str]) -> tuple[bool, list[str]]:
    """Verificación literal, sin regex."""
    if not text:
        return True, []
    found = [f for f in forbidden if f.lower() in text.lower()]
    return len(found) == 0, found


# ── Evaluación de ruta ────────────────────────────────────────────────────────

def _evaluate_route(
    primary: str | None,
    secondary: list[str],
    route: str,
) -> tuple[str, str, list[str]]:
    """Retorna (mapping_status, match_source, matched_intents).

    Prioridad:
      1. any intent in ROUTE_STRONG[route] → PASS_STRONG
      2. any intent in ROUTE_WEAK[route]   → PASS_WEAK
      3. sin match                         → REVIEW_MAPPING
      4. route no en ninguna tabla         → CONTRACT_GAP
    """
    if route not in ROUTE_STRONG and route not in ROUTE_WEAK:
        return "CONTRACT_GAP", "none", []

    strong = ROUTE_STRONG.get(route)

    # wildcard
    if strong is None:
        return "PASS_STRONG", "wildcard", []

    all_intents = [(primary, "primary")] + [(s, "secondary") for s in secondary]

    # 1. STRONG
    strong_hits = [(intent, src) for intent, src in all_intents if intent in strong]
    if strong_hits:
        matched = [i for i, _ in strong_hits]
        source = "primary" if any(s == "primary" for _, s in strong_hits) else "secondary"
        return "PASS_STRONG", source, matched

    # 2. WEAK
    weak = ROUTE_WEAK.get(route, set())
    weak_hits = [(intent, src) for intent, src in all_intents if intent in weak]
    if weak_hits:
        matched = [i for i, _ in weak_hits]
        source = "primary" if any(s == "primary" for _, s in weak_hits) else "secondary"
        return "PASS_WEAK", source, matched

    return "REVIEW_MAPPING", "none", []


def _compat_status(mapping_status: str, pass_f: bool) -> tuple[bool, str]:
    """Retorna (pass_route_bool, status_compat) para columnas de compatibilidad."""
    if not pass_f:
        return False, "FAIL"
    if mapping_status in ("PASS_STRONG", "PASS_WEAK"):
        return True, "PASS"
    if mapping_status in ("REVIEW_MAPPING", "CONTRACT_GAP"):
        return False, "REVIEW"
    return False, "ERROR"


# ── Extracción de hechos de negocio (read-only, sin regex de intents) ─────────

def _extract_vehicle_fact(question: str) -> tuple[str, str]:
    """Extrae vehicle_type del texto usando el catálogo de dominio del proyecto.

    Retorna (profile_vehicle_type, business_fact_match):
      - profile_vehicle_type: 'full' | 'sencillo' | 'quinta_rueda' | etc, o ''
      - business_fact_match:  'vehicle_type_confirmed' si aplica objetivo, si no ''

    Reutiliza normalize_vehicle + applies_objetivo_full_sencillo del catálogo.
    Importación lazy: no falla si app/ no está en sys.path (modo dry sin app).
    """
    try:
        from app.knowledge.normalize_domain_values import (  # noqa: PLC0415
            applies_objetivo_full_sencillo,
            normalize_vehicle,
        )
    except ImportError:
        return "", ""

    resolution = normalize_vehicle(question)
    if resolution is None:
        return "", ""

    vt = resolution.value or resolution.domain or ""
    bfm = "vehicle_type_confirmed" if applies_objetivo_full_sencillo(resolution) else ""
    return vt, bfm


# ── Shadow del extractor unificado ───────────────────────────────────────────

def _run_business_shadow(
    question: str,
    conv_cls: dict | None = None,
) -> dict[str, Any]:
    """Llama al extractor unificado en modo shadow y lo convierte a reporte.

    Never raises. En error devuelve _SHADOW_EMPTY con status=ERROR.
    Read-only: no escribe DB, Chatwoot ni labels.
    """
    try:
        out = classify_business_route_shadow(
            text=question,
            canonical_profile={},
            asked_field_keys=[],
            missing_fields=[],
            conversational_classification=conv_cls,
        )
    except ImportError as exc:
        return {
            **_SHADOW_EMPTY,
            "business_shadow_status": "ERROR",
            "business_shadow_error": f"import_error: {type(exc).__name__}: {exc}",
        }
    except Exception as exc:
        if type(exc).__name__ == "LLMUnavailableError" or "Gemini no disponible" in str(exc):
            raise
        return {
            **_SHADOW_EMPTY,
            "business_shadow_status": "ERROR",
            "business_shadow_error": f"{type(exc).__name__}: {exc}",
        }

    return {
        # JSON completo (evidencia + confidence)
        "business_requested_info": json.dumps(
            [r.to_dict() for r in out.requested_info], ensure_ascii=False
        ),
        "business_explicit_facts": json.dumps(
            {k: v.to_dict() for k, v in out.explicit_facts.items()}, ensure_ascii=False
        ),
        "business_signals": json.dumps(
            [s.to_dict() for s in out.business_signals], ensure_ascii=False
        ),
        "business_ambiguity_flags": json.dumps(
            [f.to_dict() for f in out.ambiguity_flags], ensure_ascii=False
        ),
        "business_policy_answer_keys": json.dumps(
            out.policy_answer_keys, ensure_ascii=False
        ),
        "business_validation_errors": json.dumps(
            out.validation_errors, ensure_ascii=False
        ),
        # Escalares / flat
        "business_requires_human": out.requires_human,
        "business_profile_action": out.profile_context_action,
        "business_signal_names": "|".join(out.signal_names()),
        "business_requested_info_topics": "|".join(
            r.category for r in out.requested_info
        ),
        "business_fact_keys": "|".join(out.explicit_facts.keys()),
        "business_ambiguity_names": "|".join(out.flag_names()),
        "business_shadow_status": "ERROR" if out.shadow_error else "OK",
        "business_shadow_error": out.shadow_error,
        "profile_context_available": "false",
    }


def _shadow_context_text(row: dict[str, str]) -> str:
    """Texto de contexto para el shadow.

    Usa la pregunta candidata y, cuando existe, la metadata contextual del caso.
    Eso ayuda a las filas cortas o con mensaje eliminado sin cambiar la evaluación
    contra `route_esperada_sugerida`.
    """
    parts = [
        row.get("candidate_question") or "",
        row.get("topic") or "",
        row.get("agent_answer_historica") or "",
    ]
    return "\n".join(part.strip() for part in parts if part and part.strip())


def _make_row_fn(base_fn: Any, include_shadow: bool) -> Any:
    """Envuelve base_fn para agregar shadow fields cuando include_shadow=True.

    La función combinada:
      1. Llama base_fn(row) → result (puede lanzar; _with_retry lo captura).
      2. Si include_shadow, extrae conv_cls del result y llama _run_business_shadow.
      3. Agrega los campos shadow al result.

    _run_business_shadow nunca lanza, así que el paso 2 no puede romper la fila.
    """
    if not include_shadow:
        return base_fn

    def _combined(row: dict[str, str]) -> dict[str, Any]:
        result = base_fn(row)

        question = _shadow_context_text(row)
        # Reusar la clasificación conversacional si ya fue calculada
        conv_cls: dict | None = None
        primary = result.get("actual_primary_intent", "")
        if primary and primary not in ("", "ERROR"):
            try:
                secondary = json.loads(result.get("actual_secondary_intents", "[]"))
            except Exception:
                secondary = []
            conv_cls = {"primary_intent": primary, "secondary_intents": secondary}

        shadow_fields = _run_business_shadow(question, conv_cls)
        result.update(shadow_fields)
        if shadow_fields.get("business_shadow_status") == "ERROR":
            result["status"] = "ERROR"
            result["mapping_status"] = "ERROR"
            existing = result.get("comment", "")
            extra = f"Extractor shadow error: {shadow_fields.get('business_shadow_error', '')}"
            result["comment"] = f"{existing}; {extra}".lstrip("; ") if existing else extra
        else:
            _apply_shadow_route_evaluation(result, row, shadow_fields)
        return result

    return _combined


def _apply_shadow_route_evaluation(
    result: dict[str, Any],
    row: dict[str, str],
    shadow_fields: dict[str, Any],
) -> None:
    """Evalúa route_esperada_sugerida contra señales del extractor unificado.

    Mantiene compatibilidad de columnas históricas: actual_business_route almacena
    las señales business_* en formato pipe-separated y mapping_status/status reflejan
    si el extractor cubrió la ruta esperada.
    """
    route = row.get("route_esperada_sugerida") or ""
    signals = [s for s in (shadow_fields.get("business_signal_names") or "").split("|") if s]
    fact_keys = [f for f in (shadow_fields.get("business_fact_keys") or "").split("|") if f]
    result["actual_business_route"] = "|".join(signals)

    if not route:
        return
    if route == "otros_rag":
        result["mapping_status"] = "PASS_STRONG"
        result["mapping_strength"] = "strong"
        result["match_source"] = "shadow_wildcard"
        result["matched_intents"] = "[]"
        result["pass_route"] = True
        result["status"] = "PASS" if result.get("pass_forbidden_phrases", True) else "FAIL"
        return
    if route in signals:
        result["mapping_status"] = "PASS_STRONG"
        result["mapping_strength"] = "strong"
        result["match_source"] = "business_shadow"
        result["matched_intents"] = json.dumps([route], ensure_ascii=False)
        result["pass_route"] = True
        result["status"] = "PASS" if result.get("pass_forbidden_phrases", True) else "FAIL"
        return
    if route == "objetivo_full_sencillo" and "experience.vehicle_type" in fact_keys:
        result["mapping_status"] = "PASS_STRONG"
        result["mapping_strength"] = "strong"
        result["match_source"] = "business_fact"
        result["matched_intents"] = json.dumps(["experience.vehicle_type"], ensure_ascii=False)
        result["pass_route"] = True
        result["status"] = "PASS" if result.get("pass_forbidden_phrases", True) else "FAIL"
        return

    result["mapping_status"] = "REVIEW_MAPPING"
    result["mapping_strength"] = "review"
    result["match_source"] = "none"
    result["matched_intents"] = "[]"
    result["pass_route"] = False
    if result.get("status") == "PASS":
        result["status"] = "REVIEW"
    existing = result.get("comment", "")
    extra = f"Extractor shadow signals {signals} did not match expected route '{route}'."
    result["comment"] = f"{existing}; {extra}".lstrip("; ") if existing else extra


# ── Rate limit / retry ────────────────────────────────────────────────────────

def _is_rate_limit(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "429" in msg or "rate limit" in msg or "ratelimit" in msg or "too many" in msg


def _effective_sleep(rpm: float, tpm: int, tokens_per_call: int, sleep_override: float) -> float:
    sleep_by_rpm = 60.0 / rpm if rpm > 0 else 60.0
    sleep_by_tpm = (60.0 * tokens_per_call / tpm) if tpm > 0 else 60.0
    return max(sleep_override, sleep_by_rpm, sleep_by_tpm)


_ERROR_FIELDS: dict[str, Any] = {
    "actual_intent": "ERROR",
    "actual_primary_intent": "ERROR",
    "actual_secondary_intents": "[]",
    "actual_answers": "[]",
    "actual_business_route": "",
    "actual_labels": "",
    "actual_reply": "",
    "pass_forbidden_phrases": True,
    "mapping_status": "ERROR",
    "mapping_strength": "error",
    "match_source": "none",
    "matched_intents": "[]",
    "profile_vehicle_type": "",
    "business_fact_match": "",
    "pass_route": False,
    "status": "ERROR",
    # Shadow fields en error row
    **_SHADOW_EMPTY,
    "business_shadow_status": "ERROR",
    "business_shadow_error": "row_processing_failed",
}


def _with_retry(
    fn: Any,
    row: dict[str, str],
    max_retries: int,
    retry_base_seconds: float,
) -> dict[str, Any]:
    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 2):
        try:
            return fn(row)
        except Exception as exc:
            last_exc = exc
            if attempt > max_retries:
                break
            wait = retry_base_seconds * attempt
            tag = "rate-limit" if _is_rate_limit(exc) else type(exc).__name__
            print(f"  [retry {attempt}/{max_retries}] {tag} — espera {wait:.0f}s ...",
                  file=sys.stderr, flush=True)
            time.sleep(wait)

    return {
        **_ERROR_FIELDS,
        "comment": f"agotó {max_retries} reintentos: {type(last_exc).__name__}: {last_exc}",
    }


# ── Builders compartidos ──────────────────────────────────────────────────────

def _build_route_fields(
    primary: str,
    secondary: list[str],
    answers: list[Any],
    route: str,
    historic: str,
    row_forbidden: list[str],
    question: str = "",
) -> dict[str, Any]:
    """Evalúa ruta, verifica frases, construye campos de salida.

    Para rutas donde un hecho de negocio (vehicle_type) confirma la ruta, aplica
    upgrade PASS_WEAK/REVIEW_MAPPING → PASS_STRONG via match_source='business_fact'.
    """
    ms, src, matched = _evaluate_route(primary, secondary, route)

    # ── Business-fact upgrade para objetivo_full_sencillo ──
    profile_vt = ""
    bfm = ""
    if route == "objetivo_full_sencillo" and question:
        profile_vt, bfm = _extract_vehicle_fact(question)
        if bfm == "vehicle_type_confirmed" and ms != "PASS_STRONG":
            ms = "PASS_STRONG"
            src = "business_fact"
            matched = [f"vehicle_type={profile_vt}"]

    all_f = GLOBAL_FORBIDDEN + [f for f in row_forbidden if f not in GLOBAL_FORBIDDEN]
    pass_f, found = _check_forbidden(historic, all_f)
    _, final_status = _compat_status(ms, pass_f)

    comments: list[str] = []
    if found:
        comments.append(f"Frases prohibidas: {found}")
    if ms == "REVIEW_MAPPING":
        comments.append(
            f"Primary intent '{primary}' is conversational for route '{route}'. "
            "Business route requires future business_route classifier or expanded mapping."
        )
    elif ms == "CONTRACT_GAP":
        comments.append(f"Route '{route}' has no mapping defined.")
    elif ms == "PASS_WEAK":
        comments.append(
            f"Weak match via {src} ({matched}). "
            "Business route needs confirmation."
        )

    return {
        "actual_intent": primary,
        "actual_primary_intent": primary,
        "actual_secondary_intents": json.dumps(secondary, ensure_ascii=False),
        "actual_answers": json.dumps(
            [{"field": a.get("field"), "value": a.get("value")} for a in answers],
            ensure_ascii=False,
        ),
        "actual_business_route": "",
        "actual_labels": "",
        "pass_forbidden_phrases": pass_f,
        "mapping_status": ms,
        "mapping_strength": {
            "PASS_STRONG": "strong",
            "PASS_WEAK": "weak",
            "REVIEW_MAPPING": "review",
            "CONTRACT_GAP": "gap",
            "ERROR": "error",
        }.get(ms, ms.lower()),
        "match_source": src,
        "matched_intents": json.dumps(matched, ensure_ascii=False),
        "profile_vehicle_type": profile_vt,
        "business_fact_match": bfm,
        "pass_route": ms in ("PASS_STRONG", "PASS_WEAK"),
        "status": final_status,
        "comment": "; ".join(comments),
    }


# ── Modo dry ──────────────────────────────────────────────────────────────────

def run_dry(row: dict[str, str]) -> dict[str, Any]:
    historic = row.get("agent_answer_historica") or ""
    per_row = _parse_forbidden(row.get("frases_prohibidas"))
    all_f = GLOBAL_FORBIDDEN + [f for f in per_row if f not in GLOBAL_FORBIDDEN]
    pass_f, found = _check_forbidden(historic, all_f)
    return {
        "actual_intent": "",
        "actual_primary_intent": "",
        "actual_secondary_intents": "[]",
        "actual_answers": "[]",
        "actual_business_route": "",
        "actual_labels": "",
        "actual_reply": historic[:300],
        "pass_forbidden_phrases": pass_f,
        "mapping_status": "PASS" if pass_f else "FAIL",
        "mapping_strength": "strong" if pass_f else "fail",
        "match_source": "none",
        "matched_intents": "[]",
        "profile_vehicle_type": "",
        "business_fact_match": "",
        "pass_route": True,
        "status": "PASS" if pass_f else "FAIL",
        "comment": f"Frases prohibidas en histórico: {found}" if found else "",
    }


# ── Modo classify ─────────────────────────────────────────────────────────────

def run_classify(row: dict[str, str]) -> dict[str, Any]:
    from app.knowledge.intent_classifier import classify_message  # noqa: PLC0415

    question = row.get("candidate_question") or ""
    route = row.get("route_esperada_sugerida") or ""

    result = classify_message(question)

    primary: str = result.get("primary_intent") or ""
    secondary: list[str] = result.get("secondary_intents") or []
    answers: list[Any] = result.get("answers") or []
    per_row = _parse_forbidden(row.get("frases_prohibidas"))
    historic = row.get("agent_answer_historica") or ""

    fields = _build_route_fields(primary, secondary, answers, route, historic, per_row, question)
    return {**fields, "actual_reply": ""}


# ── Modo full ─────────────────────────────────────────────────────────────────

def run_full(row: dict[str, str]) -> dict[str, Any]:
    from app.knowledge.intent_classifier import classify_message  # noqa: PLC0415
    from app.knowledge.intent_enricher import enrich_classification  # noqa: PLC0415
    from app.knowledge.intent_orchestrator import plan_and_respond  # noqa: PLC0415

    question = row.get("candidate_question") or ""
    route = row.get("route_esperada_sugerida") or ""

    classification = classify_message(question)
    enriched = enrich_classification(classification)
    plan = plan_and_respond(enriched, question, {})

    primary: str = classification.get("primary_intent") or ""
    secondary: list[str] = classification.get("secondary_intents") or []
    answers: list[Any] = classification.get("answers") or []
    actual_reply = (plan.get("response_text") or "")[:400]
    per_row = _parse_forbidden(row.get("frases_prohibidas"))
    historic = row.get("agent_answer_historica") or ""

    fields = _build_route_fields(primary, secondary, answers, route, historic, per_row, question)

    # También chequear frases prohibidas en la respuesta nueva
    all_f = GLOBAL_FORBIDDEN + [f for f in per_row if f not in GLOBAL_FORBIDDEN]
    pass_f_new, found_new = _check_forbidden(actual_reply, all_f)
    if not pass_f_new:
        fields["pass_forbidden_phrases"] = False
        fields["status"] = "FAIL"
        existing = fields.get("comment", "")
        extra = f"Frases prohibidas en respuesta nueva: {found_new}"
        fields["comment"] = f"{existing}; {extra}".lstrip("; ") if existing else extra

    return {**fields, "actual_reply": actual_reply}


RUN_FN = {"dry": run_dry, "classify": run_classify, "full": run_full}


# ── Presupuesto ───────────────────────────────────────────────────────────────

def _effective_tokens_per_case(
    mode: str,
    tokens_per_call: int,
    include_business_shadow: bool,
) -> int:
    """Tokens estimados por caso según modo y shadow.

    Sin shadow: tokens_per_call. Con shadow: tokens_per_call + SHADOW_TOKENS_ESTIMATE
    (en modo dry solo el extractor llama al LLM, así que es SHADOW_TOKENS_ESTIMATE).
    """
    if include_business_shadow:
        if mode == "dry":
            return SHADOW_TOKENS_ESTIMATE
        return tokens_per_call + SHADOW_TOKENS_ESTIMATE
    return tokens_per_call


def _budget_row_limit(daily_budget: int, effective_tokens: int) -> int:
    """Máximo de filas que caben en el presupuesto diario al costo efectivo por caso."""
    return daily_budget // max(effective_tokens, 1)


# ── Runner principal ──────────────────────────────────────────────────────────

def run(
    input_path: Path,
    output_path: Path,
    mode: str,
    limit: int,
    start_index: int,
    route_filter: str | None,
    priority_filter: str | None,
    rpm: float,
    tpm: int,
    tokens_per_call: int,
    sleep_override: float,
    max_retries: int,
    retry_base_seconds: float,
    daily_budget: int,
    stop_before_budget: bool,
    append: bool,
    dry_run: bool,
    include_business_shadow: bool = False,
) -> None:
    with open(input_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if route_filter:
        rows = [r for r in rows if r.get("route_esperada_sugerida") == route_filter]
    if priority_filter:
        rows = [r for r in rows if (r.get("prioridad") or "").lower() == priority_filter.lower()]
    if start_index > 0:
        rows = rows[start_index:]
    if limit > 0:
        rows = rows[:limit]

    needs_llm = mode in ("classify", "full") or include_business_shadow
    effective_tokens = _effective_tokens_per_case(mode, tokens_per_call, include_business_shadow)
    eff_sleep = _effective_sleep(rpm, tpm, effective_tokens, sleep_override) if needs_llm else 0.0

    if needs_llm and stop_before_budget and daily_budget > 0:
        max_by_budget = _budget_row_limit(daily_budget, effective_tokens)
        if len(rows) > max_by_budget:
            print(
                f"[budget] {len(rows)} × {effective_tokens} = {len(rows)*effective_tokens:,} "
                f"> budget {daily_budget:,}. Recortando a {max_by_budget} casos.",
                file=sys.stderr, flush=True,
            )
            rows = rows[:max_by_budget]

    est_tokens = len(rows) * effective_tokens
    est_min = ((len(rows) - 1) * eff_sleep / 60.0) if len(rows) > 1 else 0.0
    print(f"\nCases selected:              {len(rows)}", file=sys.stderr)
    if include_business_shadow:
        print("Unified extractor shadow:    enabled", file=sys.stderr)
        print("Extractor shadow is read-only", file=sys.stderr)
        print("Extractor shadow may use LLM", file=sys.stderr)
    if needs_llm:
        print(f"Estimated tokens/call:       {effective_tokens}", file=sys.stderr)
        print(f"Estimated total tokens:      {est_tokens:,}", file=sys.stderr)
        print(f"Daily token budget:          {daily_budget:,}", file=sys.stderr)
        print(
            f"Estimated sleep between:     {eff_sleep:.1f}s  "
            f"(rpm={rpm}, tpm={tpm}, override={sleep_override})",
            file=sys.stderr,
        )
        print(f"Estimated runtime:           ~{est_min:.1f} minutes", file=sys.stderr)
        print(f"Max retries / backoff base:  {max_retries} / {retry_base_seconds}s", file=sys.stderr)
    print("", file=sys.stderr, flush=True)

    fn = _make_row_fn(RUN_FN[mode], include_business_shadow)
    effective_columns = OUTPUT_COLUMNS + (SHADOW_COLUMNS if include_business_shadow else [])

    write_header = True
    file_mode = "w"
    if not dry_run:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if append and output_path.exists():
            file_mode = "a"
            write_header = False

    out_file = None
    writer = None
    if not dry_run:
        out_file = open(output_path, file_mode, newline="", encoding="utf-8")
        writer = csv.DictWriter(out_file, fieldnames=effective_columns)
        if write_header:
            writer.writeheader()

    ms_counters: dict[str, int] = {}
    status_counters: dict[str, int] = {}
    results_summary: list[dict[str, Any]] = []

    try:
        for i, row in enumerate(rows):
            if needs_llm and i > 0:
                time.sleep(eff_sleep)

            try:
                result = _with_retry(fn, row, max_retries, retry_base_seconds) if needs_llm else fn(row)
            except Exception:
                result = {
                    **_ERROR_FIELDS,
                    "comment": traceback.format_exc(limit=3),
                }

            status = result.get("status", "ERROR")
            ms = result.get("mapping_status", "ERROR")
            status_counters[status] = status_counters.get(status, 0) + 1
            ms_counters[ms] = ms_counters.get(ms, 0) + 1

            out_row: dict[str, Any] = {
                "qa_id":                      row.get("qa_id", ""),
                "candidate_question":         (row.get("candidate_question") or "")[:200],
                "route_esperada_sugerida":    row.get("route_esperada_sugerida", ""),
                "labels_esperadas_sugeridas": row.get("labels_esperadas_sugeridas", ""),
                "prioridad":                  row.get("prioridad", ""),
                "actual_intent":              result.get("actual_intent", ""),
                "actual_primary_intent":      result.get("actual_primary_intent", ""),
                "actual_secondary_intents":   result.get("actual_secondary_intents", "[]"),
                "actual_answers":             result.get("actual_answers", "[]"),
                "actual_business_route":      result.get("actual_business_route", ""),
                "actual_labels":              result.get("actual_labels", ""),
                "actual_reply":               result.get("actual_reply", ""),
                "pass_forbidden_phrases":     result.get("pass_forbidden_phrases", ""),
                "mapping_status":             ms,
                "mapping_strength":           result.get("mapping_strength", ""),
                "match_source":               result.get("match_source", ""),
                "matched_intents":            result.get("matched_intents", "[]"),
                "profile_vehicle_type":       result.get("profile_vehicle_type", ""),
                "business_fact_match":        result.get("business_fact_match", ""),
                "pass_route":                 result.get("pass_route", ""),
                "status":                     status,
                "comment":                    result.get("comment", ""),
            }
            if include_business_shadow:
                for col in SHADOW_COLUMNS:
                    out_row[col] = result.get(col, _SHADOW_EMPTY.get(col, ""))

            if not dry_run and writer and out_file:
                writer.writerow(out_row)
                out_file.flush()

            results_summary.append(out_row)

            if (i + 1) % 5 == 0 or (i + 1) == len(rows):
                done = i + 1
                elapsed_min = done * eff_sleep / 60.0
                print(
                    f"  {done:3d}/{len(rows)}  {ms:20s}  status={status}  "
                    f"~{elapsed_min:.1f}min",
                    file=sys.stderr, flush=True,
                )

    finally:
        if out_file:
            out_file.close()

    if not dry_run:
        print(f"\nReporte guardado: {output_path}")

    total = len(results_summary)

    print(f"\n=== mapping_status (modo={mode}, total={total}) ===")
    for ms in ("PASS_STRONG", "PASS_WEAK", "REVIEW_MAPPING", "CONTRACT_GAP", "ERROR"):
        n = ms_counters.get(ms, 0)
        if n:
            pct = round(100 * n / total, 1) if total else 0
            print(f"  {ms:20s} {n:4d}  ({pct}%)")

    print(f"\n=== status compat ===")
    for st in ("PASS", "REVIEW", "FAIL", "ERROR"):
        n = status_counters.get(st, 0)
        if n:
            pct = round(100 * n / total, 1) if total else 0
            print(f"  {st:10s} {n:4d}  ({pct}%)")

    reviews = [
        r for r in results_summary
        if r.get("mapping_status") in ("REVIEW_MAPPING", "CONTRACT_GAP", "ERROR")
        or r.get("status") in ("FAIL", "ERROR")
    ]
    if reviews:
        print(f"\n=== REVIEW / FAIL / ERROR ({len(reviews)} total) ===")
        for r in reviews[:15]:
            ms = r.get("mapping_status", "")
            sec = r.get("actual_secondary_intents", "[]")
            src = r.get("match_source", "")
            print(
                f"  [{r['status']}/{ms}] {r['qa_id']} | "
                f"route={r['route_esperada_sugerida']} | "
                f"primary={r['actual_intent']} secondary={sec} src={src}"
            )
            if r.get("comment"):
                print(f"         {str(r['comment'])[:160]}")

    fail_by_route: Counter[str] = Counter(
        r["route_esperada_sugerida"] for r in reviews
    )
    if fail_by_route:
        print("\n=== REVIEW/FAIL por ruta ===")
        for route, n in fail_by_route.most_common():
            print(f"  {n:3d}  {route}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--input", default=str(DEFAULT_INPUT))
    p.add_argument("--output", default=str(DEFAULT_OUTPUT))
    p.add_argument("--mode", choices=["dry", "classify", "full"], default="dry")
    p.add_argument("--limit", type=int, default=0, help="0 = todos los casos")
    p.add_argument("--start-index", type=int, default=0,
                   help="Índice de inicio en el dataframe filtrado (para bloques)")
    p.add_argument("--route-filter", help="Filtrar por route_esperada_sugerida exacta")
    p.add_argument("--priority", help="Filtrar por prioridad (Alta, Media)")
    # Rate-limit
    p.add_argument("--requests-per-minute", type=float, default=3.0)
    p.add_argument("--tokens-per-minute", type=int, default=6000)
    p.add_argument("--estimated-tokens-per-call", type=int, default=2800)
    p.add_argument("--sleep-seconds", type=float, default=0.0)
    # Retry
    p.add_argument("--max-retries", type=int, default=3)
    p.add_argument("--retry-base-seconds", type=float, default=20.0)
    # Presupuesto diario
    p.add_argument("--daily-token-budget", type=int, default=450000)
    p.add_argument("--stop-before-daily-budget", action="store_true")
    # Reanudación
    p.add_argument("--append", action="store_true")
    p.add_argument("--dry-run", action="store_true", help="No escribe archivos de salida")
    # Unified extractor shadow
    p.add_argument(
        "--include-business-shadow",
        action="store_true",
        default=False,
        help=(
            "Activa el shadow del extractor unificado (read-only). "
            "Agrega columnas business_* al CSV. Requiere GEMINI_API_KEY."
        ),
    )
    args = p.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"ERROR: No se encontró input: {input_path}", file=sys.stderr)
        sys.exit(1)

    needs_gemini = args.mode in ("classify", "full") or args.include_business_shadow
    if needs_gemini and not os.getenv("GEMINI_API_KEY"):
        print(
            "ERROR: GEMINI_API_KEY no definida. "
            "Usar --mode dry sin --include-business-shadow para correr sin LLM.",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.mode in ("classify", "full") or args.include_business_shadow:
        sys.path.insert(0, str(REPO_ROOT))

    run(
        input_path=input_path,
        output_path=Path(args.output),
        mode=args.mode,
        limit=args.limit,
        start_index=args.start_index,
        route_filter=args.route_filter,
        priority_filter=args.priority,
        rpm=args.requests_per_minute,
        tpm=args.tokens_per_minute,
        tokens_per_call=args.estimated_tokens_per_call,
        sleep_override=args.sleep_seconds,
        max_retries=args.max_retries,
        retry_base_seconds=args.retry_base_seconds,
        daily_budget=args.daily_token_budget,
        stop_before_budget=args.stop_before_daily_budget,
        append=args.append,
        dry_run=args.dry_run,
        include_business_shadow=args.include_business_shadow,
    )


if __name__ == "__main__":
    main()
