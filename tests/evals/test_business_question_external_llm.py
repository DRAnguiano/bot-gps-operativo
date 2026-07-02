"""Eval con LLM real — matriz adversarial de detección de pregunta de negocio.

SCAFFOLD de medición (no gate). Corre la matriz contra el extractor/clasificador
REAL y registra, por caso, tres niveles separados:

    raw_signals:            is_question, business_term_regex_hit, matched_terms, has_embedded_question
    candidate_signal:       maybe_business_question   (OR de las 3 — puede sobredisparar)
    semantic_classification: confirmed_business_question, intent_family, evidence

NO asere `decision.action`, prioridad de funnel, handoff ni persistencia final:
esos contratos nacen en los Bloques 3–6. Aquí solo se MIDE la clasificación.

Reglas honradas:
- `@pytest.mark.external_llm` → excluido del gate unitario por defecto (pytest.ini).
- Si no hay Groq / cuota agotada → `pytest.skip` (no rompe el gate).
- No se cambian las expectativas si el modelo falla: se listan IDs como incidencias.
- Los falsos positivos de gate (maybe=True en enunciados) se reportan como
  costo/ruido, NO como bug funcional (no alteran la decisión final aquí).
"""
from __future__ import annotations

import json
import os
import time
from collections import Counter

import pytest

from tests.fixtures.business_question_matrix import CASES

pytestmark = [pytest.mark.external_llm, pytest.mark.integration]


# ── helpers deterministas (raw_signals) ───────────────────────────────────────
def _raw_signals(message: str) -> dict:
    from app.knowledge.current_turn import (
        BUSINESS_QUESTION_TERMS,
        is_question,
        _message_has_any,
    )
    from app.knowledge.text_normalizer import normalize_text

    matched = [t for t in BUSINESS_QUESTION_TERMS if normalize_text(t) in normalize_text(message)]
    return {
        "is_question": bool(is_question(message)),
        "business_term_regex_hit": bool(matched),
        "matched_terms": matched,
    }


def _candidate_signal(message: str, has_embedded: bool) -> bool:
    """maybe_business_question = el detector barato (OR de las 3 señales)."""
    from dataclasses import dataclass
    from app.knowledge.current_turn import has_business_question

    @dataclass
    class _S:
        has_embedded_question: bool = has_embedded

    return bool(has_business_question(message, _S()))


def _groq_available() -> bool:
    if not (os.getenv("GROQ_API_KEY") or os.getenv("GROQ_API_KEY_BACKUP")):
        return False
    try:
        from app.knowledge.turn_extractor import extract_turn

        extract_turn("hola")  # smoke: si truena por auth/cuota/red → no disponible
        return True
    except Exception:
        return False


def _observe(message: str) -> dict:
    """Salida REAL del extractor + clasificador. Nunca propaga: registra error."""
    from app.knowledge.turn_extractor import extract_turn
    from app.knowledge.intent_classifier import classify_message
    from app.lead_memory.profile_extractor import extract_profile_facts_as_dict

    rec: dict = {"error": None}
    try:
        ext = extract_turn(message)
        rec["has_embedded_question"] = bool(ext.signals.has_embedded_question)
        rec["evidence"] = ext.embedded_question
    except Exception as e:
        rec["has_embedded_question"] = None
        rec["evidence"] = None
        rec["error"] = f"extract_turn: {e}"
    try:
        cls = classify_message(message)
        qs = [q for q in (cls.get("questions") or []) if isinstance(q, dict)]
        rec["observed_intents"] = [q.get("intent") for q in qs]
        rec["requires_rag_any"] = any(q.get("requires_rag") for q in qs)
    except Exception as e:
        rec["observed_intents"] = None
        rec["requires_rag_any"] = None
        rec["error"] = (rec["error"] or "") + f" | classify: {e}"
    try:
        rec["observed_facts"] = extract_profile_facts_as_dict(message)
    except Exception as e:
        rec["observed_facts"] = None
        rec["error"] = (rec["error"] or "") + f" | facts: {e}"
    return rec


def _f1(tp: int, fp: int, fn: int) -> float:
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    return (2 * p * r / (p + r)) if (p + r) else 0.0


def test_business_question_eval_scaffold():
    if not _groq_available():
        pytest.skip("Groq no disponible (sin API key o cuota agotada) — eval external_llm omitida")

    model_config = {
        "GROQ_MODEL": os.getenv("GROQ_MODEL"),
        "UNIFIED_EXTRACTOR_MODEL": os.getenv("UNIFIED_EXTRACTOR_MODEL"),
        "GROQ_CLASSIFIER_MODEL": os.getenv("GROQ_CLASSIFIER_MODEL"),
    }
    records = []
    for case in CASES:
        msg = case["message"]
        raw = _raw_signals(msg)
        obs = _observe(msg)
        confirmed = obs.get("has_embedded_question")  # proxy actual de la capa semántica
        records.append(
            {
                "id": case["id"],
                "group": case["group"],
                "message": msg,
                "expected_semantic": case["expected_semantic"],
                "expected_intent_family": case.get("intent_family"),
                # raw_signals
                "is_question": raw["is_question"],
                "business_term_regex_hit": raw["business_term_regex_hit"],
                "matched_terms": raw["matched_terms"],
                "has_embedded_question": obs.get("has_embedded_question"),
                # candidate_signal
                "maybe_business_question": _candidate_signal(msg, bool(obs.get("has_embedded_question"))),
                # semantic_classification (observado)
                "confirmed_business_question": confirmed,
                "observed_intents": obs.get("observed_intents"),
                "requires_rag_any": obs.get("requires_rag_any"),
                "evidence": obs.get("evidence"),
                "observed_facts": obs.get("observed_facts"),
                "error": obs.get("error"),
            }
        )

    # ── métricas (positivos/negativos; ambiguos aparte) ───────────────────────
    tp = fp = fn = tn = 0
    incidencias = []  # IDs donde observado != esperado (para abrir issue, no para debilitar)
    gate_false_positives = []  # maybe=True en enunciados (costo/ruido)
    ambiguous = []
    for r in records:
        exp = r["expected_semantic"]
        got = r["confirmed_business_question"]
        if r["maybe_business_question"] and exp is False:
            gate_false_positives.append(r["id"])
        if exp == "uncertain":
            ambiguous.append({"id": r["id"], "confirmed": got, "maybe": r["maybe_business_question"]})
            continue
        if exp is True and got is True:
            tp += 1
        elif exp is True and got is False:
            fn += 1; incidencias.append({"id": r["id"], "exp": True, "got": got})
        elif exp is False and got is True:
            fp += 1; incidencias.append({"id": r["id"], "exp": False, "got": got})
        elif exp is False and got is False:
            tn += 1

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1_pos = _f1(tp, fp, fn)
    f1_neg = _f1(tn, fn, fp)
    metrics = {
        "coverage": len(records),
        "total_cases": len(CASES),
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "macro_f1": round((f1_pos + f1_neg) / 2, 3),
        "gate_false_positives": gate_false_positives,
        "ambiguous_distribution": Counter(str(a["confirmed"]) for a in ambiguous),
        "incidencias": incidencias,
        "errores": [r["id"] for r in records if r["error"]],
    }

    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "model_config": model_config,
        "metrics": metrics,
        "records": records,
    }

    # Persistir (best-effort) + imprimir resumen (visible con -s)
    try:
        os.makedirs("reports", exist_ok=True)
        path = f"reports/business_question_eval_{int(time.time())}.json"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
        print(f"\n[EVAL] reporte escrito en {path}")
    except Exception as e:
        print(f"\n[EVAL] no se pudo escribir reporte: {e}")

    print("\n[EVAL] métricas:", json.dumps(metrics, ensure_ascii=False, default=str, indent=2))
    if incidencias:
        print("\n[EVAL] INCIDENCIAS (abrir issue con estos IDs, NO cambiar expectativas):",
              [i["id"] for i in incidencias])

    # Asserts de SCAFFOLD (no de calidad de modelo): cobertura completa + métricas presentes.
    assert metrics["coverage"] == len(CASES), "cobertura incompleta: faltan registros"
    assert "macro_f1" in metrics
