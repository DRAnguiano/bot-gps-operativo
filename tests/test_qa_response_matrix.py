"""Tests for qa_response_matrix.py C6 — shadow integration, no LLM calls."""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# scripts/ is not a package inside the Docker image — add it to path directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import qa_response_matrix as harness  # noqa: E402
from qa_response_matrix import (
    OUTPUT_COLUMNS,
    SHADOW_COLUMNS,
    _SHADOW_EMPTY,
    _make_row_fn,
    _run_business_shadow,
    run_dry,
)


# ── _run_business_shadow ──────────────────────────────────────────────────────

SHADOW_MOCK_PATH = "qa_response_matrix.classify_business_route_shadow"


class TestRunBusinessShadow:
    def test_import_error_returns_error_fields(self):
        with patch.dict("sys.modules", {"app.knowledge.business_route_classifier": None}):
            result = _run_business_shadow("hola")
        assert result["business_shadow_status"] == "ERROR"
        assert "import_error" in result["business_shadow_error"]

    def test_module_retired_degrades_to_error_row(self):
        # business_route_classifier fue RETIRADO (gemini-full-provider-migration,
        # 2026-07-07: código huérfano; el entendimiento del turno vive en el
        # extractor unificado). El harness degrada a fila ERROR trazable sin
        # crashear, hasta que se repunte al extractor (gate 4.2).
        result = _run_business_shadow("manejo sencillo")
        assert result["business_shadow_status"] == "ERROR"
        assert "import_error" in result["business_shadow_error"]

    def test_valid_output_fields_present(self):
        from app.knowledge.business_route_schema import (
            BusinessRouteOutput, BusinessSignal, ExplicitFact,
        )
        mock_out = BusinessRouteOutput()
        mock_out.business_signals.append(
            BusinessSignal(name="pago_condiciones", evidence="km", confidence=0.9)
        )
        mock_out.explicit_facts["experience.vehicle_type"] = ExplicitFact(
            field="experience.vehicle_type", value="sencillo", evidence="sencillo"
        )

        with patch(
            "qa_response_matrix.classify_business_route_shadow",
            return_value=mock_out,
        ):
            result = _run_business_shadow("manejo sencillo", conv_cls=None)

        assert result["business_shadow_status"] == "OK"
        assert result["business_shadow_error"] == ""
        assert result["business_signal_names"] == "pago_condiciones"
        assert result["business_fact_keys"] == "experience.vehicle_type"
        assert result["profile_context_available"] == "false"

        # JSON columns must be valid JSON
        json.loads(result["business_signals"])
        json.loads(result["business_explicit_facts"])
        json.loads(result["business_requested_info"])

    def test_exception_in_classifier_returns_error(self):
        with patch(
            "qa_response_matrix.classify_business_route_shadow",
            side_effect=RuntimeError("unexpected"),
        ):
            result = _run_business_shadow("hola")

        assert result["business_shadow_status"] == "ERROR"
        assert "RuntimeError" in result["business_shadow_error"]

    def test_multiple_signals_pipe_separated(self):
        from app.knowledge.business_route_schema import BusinessRouteOutput, BusinessSignal

        mock_out = BusinessRouteOutput()
        mock_out.business_signals.extend([
            BusinessSignal(name="pago_condiciones", evidence="km", confidence=0.9),
            BusinessSignal(name="ubicacion_base_traslado", evidence="ruta", confidence=0.9),
        ])

        with patch(
            "qa_response_matrix.classify_business_route_shadow",
            return_value=mock_out,
        ):
            result = _run_business_shadow("km y ruta")

        names = result["business_signal_names"].split("|")
        assert "pago_condiciones" in names
        assert "ubicacion_base_traslado" in names


# ── _make_row_fn ──────────────────────────────────────────────────────────────

class TestMakeRowFn:
    def test_shadow_disabled_returns_base_fn_unchanged(self):
        base_fn_called = []

        def base_fn(row):
            base_fn_called.append(True)
            return {"actual_primary_intent": "pay_question", "status": "PASS"}

        combined = _make_row_fn(base_fn, include_shadow=False)
        assert combined is base_fn

    def test_shadow_enabled_adds_shadow_fields(self):
        from app.knowledge.business_route_schema import BusinessRouteOutput

        def base_fn(row):
            return {
                "actual_primary_intent": "pay_question",
                "actual_secondary_intents": "[]",
                "status": "PASS",
            }

        mock_out = BusinessRouteOutput()

        with patch(
            "qa_response_matrix.classify_business_route_shadow",
            return_value=mock_out,
        ):
            combined = _make_row_fn(base_fn, include_shadow=True)
            result = combined({"candidate_question": "km cargado?"})

        assert "business_shadow_status" in result
        assert "business_signal_names" in result
        assert "profile_context_available" in result

    def test_shadow_never_raises(self):
        def base_fn(row):
            return {"actual_primary_intent": "pay_question", "actual_secondary_intents": "[]"}

        with patch(
            "qa_response_matrix.classify_business_route_shadow",
            side_effect=RuntimeError("boom"),
        ):
            combined = _make_row_fn(base_fn, include_shadow=True)
            result = combined({"candidate_question": "test"})

        assert result["business_shadow_status"] == "ERROR"

    def test_conv_cls_passed_from_intent_result(self):
        """Verifica que conv_cls se construye desde el resultado del classify."""
        from app.knowledge.business_route_schema import BusinessRouteOutput

        captured_conv = {}

        def base_fn(row):
            return {
                "actual_primary_intent": "pay_question",
                "actual_secondary_intents": '["logistics_question"]',
            }

        def mock_shadow(text, canonical_profile, asked_field_keys, missing_fields,
                        conversational_classification):
            captured_conv.update(conversational_classification or {})
            return BusinessRouteOutput()

        with patch("qa_response_matrix.classify_business_route_shadow", mock_shadow):
            combined = _make_row_fn(base_fn, include_shadow=True)
            combined({"candidate_question": "test"})

        assert captured_conv.get("primary_intent") == "pay_question"
        assert "logistics_question" in captured_conv.get("secondary_intents", [])


# ── Presupuesto ───────────────────────────────────────────────────────────────

class TestBudget:
    def test_effective_tokens_without_shadow_uses_tokens_per_call(self):
        from qa_response_matrix import _effective_tokens_per_case
        assert _effective_tokens_per_case("classify", 800, include_business_shadow=False) == 800
        assert _effective_tokens_per_case("full", 800, include_business_shadow=False) == 800

    def test_effective_tokens_with_shadow_adds_estimate(self):
        from qa_response_matrix import SHADOW_TOKENS_ESTIMATE, _effective_tokens_per_case
        assert (
            _effective_tokens_per_case("classify", 800, include_business_shadow=True)
            == 800 + SHADOW_TOKENS_ESTIMATE
        )

    def test_effective_tokens_dry_with_shadow_is_shadow_only(self):
        # En modo dry el base run no llama LLM; solo cuenta el shadow.
        from qa_response_matrix import SHADOW_TOKENS_ESTIMATE, _effective_tokens_per_case
        assert (
            _effective_tokens_per_case("dry", 800, include_business_shadow=True)
            == SHADOW_TOKENS_ESTIMATE
        )

    def test_budget_row_limit_uses_effective_tokens(self):
        from qa_response_matrix import _budget_row_limit
        # 10_000 de budget: a 800/caso caben 12; a 2_000/caso (con shadow) caben 5.
        assert _budget_row_limit(10_000, 800) == 12
        assert _budget_row_limit(10_000, 2_000) == 5

    def test_budget_row_limit_never_divides_by_zero(self):
        from qa_response_matrix import _budget_row_limit
        assert _budget_row_limit(10_000, 0) == 10_000


# ── SHADOW_COLUMNS / OUTPUT_COLUMNS ──────────────────────────────────────────

class TestColumns:
    def test_shadow_columns_no_overlap_with_output_columns(self):
        assert not set(OUTPUT_COLUMNS) & set(SHADOW_COLUMNS), (
            "SHADOW_COLUMNS must not overlap OUTPUT_COLUMNS"
        )

    def test_shadow_empty_covers_all_shadow_columns(self):
        for col in SHADOW_COLUMNS:
            assert col in _SHADOW_EMPTY, f"_SHADOW_EMPTY missing column: {col}"

    def test_error_fields_has_shadow_fields(self):
        from qa_response_matrix import _ERROR_FIELDS
        assert "business_shadow_status" in _ERROR_FIELDS
        assert _ERROR_FIELDS["business_shadow_status"] == "ERROR"
