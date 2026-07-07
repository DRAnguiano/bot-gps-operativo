"""Cliente Gemini + dispatch por función (gemini-natural-recruiter B3, D1/D2).

Todo mockeado: sin llamadas reales a la red ni a Groq. Contrato: specs/gemini-
provider-adapter.
"""
from __future__ import annotations

import json
from unittest import mock

import httpx
import pytest

from app import gemini_client as gc


def _fake_response(status_code=200, text="OK", json_body=None):
    resp = mock.Mock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = text
    resp.json.return_value = json_body or {
        "candidates": [{"content": {"parts": [{"text": text}]}}]
    }
    return resp


@mock.patch.dict("os.environ", {"GEMINI_API_KEY": "fake-key"})
class TestGenerateText:
    def test_success(self):
        with mock.patch("httpx.post", return_value=_fake_response(text="hola")):
            assert gc.generate_text("hola?") == "hola"

    def test_thinking_budget_zero_always_set(self):
        # Bug en vivo 2026-07-07: sin esto, el thinking consume maxOutputTokens y
        # el texto visible corta a media palabra ("El pago en Trans...").
        captured = {}

        def _capture(url, params=None, json=None, timeout=None):
            captured.update(json)
            return _fake_response(text="respuesta completa")

        with mock.patch("httpx.post", side_effect=_capture):
            gc.generate_text("pregunta", system="sys")
        assert captured["generationConfig"]["thinkingConfig"]["thinkingBudget"] == 0

    def test_missing_key_raises(self):
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": ""}):
            with pytest.raises(gc.GeminiError):
                gc.generate_text("x")

    def test_http_error_raises(self):
        with mock.patch("httpx.post", return_value=_fake_response(status_code=500, text="boom")):
            with pytest.raises(gc.GeminiError):
                gc.generate_text("x")

    def test_rate_limit_raises(self):
        with mock.patch("httpx.post", return_value=_fake_response(status_code=429)):
            with pytest.raises(gc.GeminiError):
                gc.generate_text("x")

    def test_timeout_raises(self):
        with mock.patch("httpx.post", side_effect=httpx.TimeoutException("slow")):
            with pytest.raises(gc.GeminiError):
                gc.generate_text("x")


@mock.patch.dict("os.environ", {"GEMINI_API_KEY": "fake-key"})
class TestGenerateJson:
    def test_thinking_budget_zero_always_set(self):
        captured = {}

        def _capture(url, params=None, json=None, timeout=None):
            captured.update(json)
            return _fake_response(text='{"ok": true}')

        with mock.patch("httpx.post", side_effect=_capture):
            gc.generate_json("extrae esto", system="eres un extractor")
        assert captured["generationConfig"]["thinkingConfig"]["thinkingBudget"] == 0
        assert captured["generationConfig"]["responseMimeType"] == "application/json"

    def test_returns_parseable_json(self):
        with mock.patch("httpx.post", return_value=_fake_response(text='{"a": 1}')):
            out = gc.generate_json("x", system="y")
        assert json.loads(out) == {"a": 1}


@mock.patch.dict("os.environ", {"GEMINI_API_KEY": "fake-key"})
class TestGenerateVision:
    def test_success_with_image_bytes(self):
        with mock.patch("httpx.post", return_value=_fake_response(text="licencia")):
            out = gc.generate_vision(b"\x89PNG...", "clasifica")
        assert out == "licencia"

    def test_empty_bytes_raises(self):
        with pytest.raises(gc.GeminiError):
            gc.generate_vision(b"", "clasifica")

    def test_json_mode_sets_thinking_budget_zero(self):
        captured = {}

        def _capture(url, params=None, json=None, timeout=None):
            captured.update(json)
            return _fake_response(text='{"tipo_documento":"ine"}')

        with mock.patch("httpx.post", side_effect=_capture):
            gc.generate_vision(b"bytes", "clasifica", json_mode=True)
        assert captured["generationConfig"]["thinkingConfig"]["thinkingBudget"] == 0


@mock.patch.dict("os.environ", {"GEMINI_API_KEY": "fake-key"})
class TestDispatchGeneration:
    def test_default_provider_is_gemini_no_env_needed(self):
        # Decisión 2026-07-07: Groq se deprecia como camino principal — Gemini es
        # el default SIN necesidad de fijar LLM_GENERATION_PROVIDER. clear=True
        # aísla de cualquier valor real en el entorno (staging ya lo trae fijado).
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "fake-key"}, clear=True), \
             mock.patch("httpx.post", return_value=_fake_response(text="desde gemini")), \
             mock.patch("app.indexer.call_groq_with_system") as m_groq:
            out = gc.dispatch_generation("sys", "user")
        assert out == "desde gemini"
        m_groq.assert_not_called()

    def test_explicit_groq_override_still_works(self):
        with mock.patch.dict("os.environ", {"LLM_GENERATION_PROVIDER": "groq"}), \
             mock.patch("app.indexer.call_groq_with_system", return_value="desde groq") as m_groq, \
             mock.patch("httpx.post") as m_post:
            out = gc.dispatch_generation("sys", "user")
        assert out == "desde groq"
        m_groq.assert_called_once()
        m_post.assert_not_called()

    def test_gemini_provider_used_when_configured(self):
        with mock.patch.dict("os.environ", {"LLM_GENERATION_PROVIDER": "gemini"}), \
             mock.patch("httpx.post", return_value=_fake_response(text="desde gemini")), \
             mock.patch("app.indexer.call_groq_with_system") as m_groq:
            out = gc.dispatch_generation("sys", "user")
        assert out == "desde gemini"
        m_groq.assert_not_called()

    def test_gemini_failure_falls_back_to_groq(self):
        with mock.patch.dict("os.environ", {"LLM_GENERATION_PROVIDER": "gemini"}), \
             mock.patch("httpx.post", side_effect=httpx.TimeoutException("slow")), \
             mock.patch("app.indexer.call_groq_with_system", return_value="fallback ok") as m_groq:
            out = gc.dispatch_generation("sys", "user")
        assert out == "fallback ok"
        m_groq.assert_called_once()

    def test_gemini_rate_limit_falls_back_to_groq(self):
        with mock.patch.dict("os.environ", {"LLM_GENERATION_PROVIDER": "gemini"}), \
             mock.patch("httpx.post", return_value=_fake_response(status_code=429)), \
             mock.patch("app.indexer.call_groq_with_system", return_value="fallback ok") as m_groq:
            out = gc.dispatch_generation("sys", "user")
        assert out == "fallback ok"
        m_groq.assert_called_once()


@mock.patch.dict("os.environ", {"GEMINI_API_KEY": "fake-key"})
class TestDispatchVision:
    def test_default_provider_is_gemini_no_env_needed(self):
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "fake-key"}, clear=True), \
             mock.patch("httpx.post", return_value=_fake_response(text="tipo_documento: ine")), \
             mock.patch("app.indexer.call_groq_vision") as m_groq:
            out = gc.dispatch_vision(b"img", "prompt")
        assert out == "tipo_documento: ine"
        m_groq.assert_not_called()

    def test_explicit_groq_override_still_works(self):
        with mock.patch.dict("os.environ", {"LLM_VISION_PROVIDER": "groq"}), \
             mock.patch("app.indexer.call_groq_vision", return_value="desde groq") as m_groq, \
             mock.patch("httpx.post") as m_post:
            out = gc.dispatch_vision(b"img", "prompt")
        assert out == "desde groq"
        m_groq.assert_called_once()
        m_post.assert_not_called()

    def test_gemini_provider_used_when_configured(self):
        with mock.patch.dict("os.environ", {"LLM_VISION_PROVIDER": "gemini"}), \
             mock.patch("httpx.post", return_value=_fake_response(text="tipo_documento: ine")), \
             mock.patch("app.indexer.call_groq_vision") as m_groq:
            out = gc.dispatch_vision(b"img", "prompt")
        assert out == "tipo_documento: ine"
        m_groq.assert_not_called()

    def test_gemini_failure_falls_back_to_groq(self):
        with mock.patch.dict("os.environ", {"LLM_VISION_PROVIDER": "gemini"}), \
             mock.patch("httpx.post", side_effect=httpx.TimeoutException("slow")), \
             mock.patch("app.indexer.call_groq_vision", return_value="fallback ok") as m_groq:
            out = gc.dispatch_vision(b"img", "prompt")
        assert out == "fallback ok"
        m_groq.assert_called_once()


@mock.patch.dict("os.environ", {"GEMINI_API_KEY": "fake-key"})
class TestCallLlmCutover:
    """Fase G1: call_llm (RAG generation). Gemini es el default desde 2026-07-07
    (Groq deprecado como camino principal, queda como fallback/override explícito)."""

    def test_default_routes_through_gemini(self):
        from app import indexer
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "fake-key"}, clear=True), \
             mock.patch("httpx.post", return_value=_fake_response(text="desde gemini")), \
             mock.patch("app.indexer.call_groq_llm") as m_groq:
            out = indexer.call_llm("hola")
        assert out == "desde gemini"
        m_groq.assert_not_called()

    def test_explicit_groq_override_still_works(self):
        from app import indexer
        with mock.patch.dict("os.environ", {"LLM_GENERATION_PROVIDER": "groq"}), \
             mock.patch("app.indexer.call_groq_llm", return_value="groq") as m_groq, \
             mock.patch("httpx.post") as m_post:
            out = indexer.call_llm("hola")
        assert out == "groq"
        m_groq.assert_called_once()
        m_post.assert_not_called()

    def test_gemini_activated_routes_through_dispatch(self):
        from app import indexer
        with mock.patch.dict("os.environ", {"LLM_GENERATION_PROVIDER": "gemini"}), \
             mock.patch("httpx.post", return_value=_fake_response(text="desde gemini")), \
             mock.patch("app.indexer.call_groq_llm") as m_groq:
            out = indexer.call_llm("hola")
        assert out == "desde gemini"
        m_groq.assert_not_called()

    def test_gemini_activated_falls_back_on_failure(self):
        from app import indexer
        with mock.patch.dict("os.environ", {"LLM_GENERATION_PROVIDER": "gemini"}), \
             mock.patch("httpx.post", side_effect=httpx.TimeoutException("slow")), \
             mock.patch("app.indexer.call_groq_with_system", return_value="fallback ok") as m_groq:
            out = indexer.call_llm("hola")
        assert out == "fallback ok"
        m_groq.assert_called_once()
