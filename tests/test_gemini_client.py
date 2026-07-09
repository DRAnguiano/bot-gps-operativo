"""Cliente Gemini — proveedor ÚNICO (gemini-full-provider-migration B1).

Groq/Cohere eliminados: ningún dispatch los invoca — ante fallo de Gemini cada
camino degrada con su contrato de error (JSON de error / '' / excepción al caller).
Todo mockeado: sin llamadas reales a la red.
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
    def test_default_model_is_flash(self):
        captured = {}

        def _capture(url, params=None, json=None, timeout=None):
            captured["url"] = url
            return _fake_response(text="ok")

        with mock.patch("httpx.post", side_effect=_capture):
            gc.generate_text("hola")
        # gemini-2.5-flash fue RETIRADO por Google (404, verificado 2026-07-08) —
        # el default vigente es gemini-3.5-flash.
        assert "/gemini-3.5-flash:generateContent" in captured["url"]

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


# ── dispatch: Gemini primario, Groq fallback TEMPORAL (2026-07-09) ────────────
# gemini-3.5-flash con 503 "high demand" sostenido — ver docstring de indexer.py
# y gemini_client.py. Groq NUNCA se llama si Gemini responde (mock de httpx.post
# intercepta ANTES de que exista una respuesta real); solo entra ante fallo.

@mock.patch.dict("os.environ", {"GEMINI_API_KEY": "fake-key"})
class TestDispatchGeminiPrimaryGroqFallback:
    def test_generation_success_never_calls_groq(self):
        with mock.patch("httpx.post", return_value=_fake_response(text="desde gemini")), \
             mock.patch("app.indexer.call_groq_with_system") as m_groq:
            assert gc.dispatch_generation("sys", "user") == "desde gemini"
        m_groq.assert_not_called()

    def test_generation_failure_falls_back_to_groq(self):
        with mock.patch("httpx.post", return_value=_fake_response(status_code=429)), \
             mock.patch("app.indexer.call_groq_with_system", return_value="desde groq") as m_groq:
            out = gc.dispatch_generation("sys", "user")
        assert out == "desde groq"
        m_groq.assert_called_once()

    def test_json_success_never_calls_groq(self):
        with mock.patch("httpx.post", return_value=_fake_response(text='{"a": 1}')), \
             mock.patch("app.indexer.call_groq_json") as m_groq:
            assert json.loads(gc.dispatch_json("prompt", "system")) == {"a": 1}
        m_groq.assert_not_called()

    def test_json_failure_falls_back_to_groq(self):
        with mock.patch("httpx.post", side_effect=httpx.TimeoutException("slow")), \
             mock.patch("app.indexer.call_groq_json", return_value='{"b": 2}') as m_groq:
            out = gc.dispatch_json("prompt", "system")
        assert json.loads(out) == {"b": 2}
        m_groq.assert_called_once()

    def test_json_failure_groq_also_fails_returns_error_contract(self):
        # Si Gemini Y Groq fallan, el contrato de error se preserva (extracción
        # vacía / señales neutras) en vez de propagar una excepción.
        with mock.patch("httpx.post", side_effect=httpx.TimeoutException("slow")), \
             mock.patch("app.indexer.call_groq_json", side_effect=RuntimeError("groq caído")):
            out = gc.dispatch_json("prompt", "system")
        assert json.loads(out) == {"error": "gemini_error"}

    def test_json_uses_backup_key_on_primary_rate_limit(self):
        calls = []

        def _capture(url, params=None, json=None, timeout=None):
            calls.append(params["key"])
            if len(calls) == 1:
                return _fake_response(status_code=429)
            return _fake_response(text='{"ok": true}')

        with mock.patch.dict("os.environ", {
            "GEMINI_API_KEY": "primary",
            "GEMINI_API_KEY_BACKUP": "backup",
        }), mock.patch("httpx.post", side_effect=_capture):
            out = gc.dispatch_json("prompt", "system")

        assert json.loads(out) == {"ok": True}
        assert calls == ["primary", "backup"]

    def test_json_signature_has_no_model_param(self):
        # 4.3: el parámetro model= (selección de modelo Groq) fue retirado — el
        # modelo es único y vive en GEMINI_MODEL.
        import inspect
        assert "model" not in inspect.signature(gc.dispatch_json).parameters

    def test_vision_success_never_calls_groq(self):
        with mock.patch("httpx.post", return_value=_fake_response(text="tipo_documento: ine")), \
             mock.patch("app.indexer.call_groq_vision") as m_groq:
            assert gc.dispatch_vision(b"img", "prompt") == "tipo_documento: ine"
        m_groq.assert_not_called()

    def test_vision_failure_falls_back_to_groq(self):
        with mock.patch("httpx.post", return_value=_fake_response(status_code=429)), \
             mock.patch("app.indexer.call_groq_vision", return_value="desde groq") as m_groq:
            out = gc.dispatch_vision(b"img", "prompt")
        assert out == "desde groq"
        m_groq.assert_called_once()

    def test_vision_failure_groq_also_fails_returns_empty(self):
        with mock.patch("httpx.post", return_value=_fake_response(status_code=429)), \
             mock.patch("app.indexer.call_groq_vision", side_effect=RuntimeError("groq caído")):
            assert gc.dispatch_vision(b"img", "prompt") == ""

    def test_audio_success(self):
        with mock.patch("httpx.post", return_value=_fake_response(text="soy fulero de Torreón")):
            out = gc.dispatch_audio(b"OggS...")
        assert out == "soy fulero de Torreón"

    def test_audio_failure_returns_empty(self):
        with mock.patch("httpx.post", side_effect=httpx.TimeoutException("slow")):
            assert gc.dispatch_audio(b"OggS...") == ""

    def test_audio_prompt_includes_glossary(self):
        captured = {}

        def _capture(url, params=None, json=None, timeout=None):
            captured.update(json)
            return _fake_response(text="ok")

        with mock.patch("httpx.post", side_effect=_capture):
            gc.dispatch_audio(b"OggS...")
        prompt_text = captured["contents"][0]["parts"][1]["text"]
        assert "fulero" in prompt_text and "caja seca" in prompt_text


# ── call_llm: Gemini único, contrato de error del caller ─────────────────────

@mock.patch.dict("os.environ", {"GEMINI_API_KEY": "fake-key"})
class TestCallLlmGeminiPrimaryGroqFallback:
    def test_routes_through_gemini_never_calls_groq_on_success(self):
        from app import indexer
        with mock.patch("httpx.post", return_value=_fake_response(text="desde gemini")), \
             mock.patch("app.indexer.call_groq_with_system") as m_groq:
            out = indexer.call_llm("hola")
        assert out == "desde gemini"
        m_groq.assert_not_called()

    def test_failure_falls_back_to_groq_temporal(self):
        # El fallback vive en dispatch_generation (gemini_client.py, capa única —
        # ver su docstring); call_gemini_llm (indexer.py) solo re-propaga lo que
        # esa capa devuelva. TEMPORAL 2026-07-09 mientras gemini-3.5-flash da 503
        # sostenido.
        from app import indexer
        with mock.patch("httpx.post", return_value=_fake_response(status_code=429)), \
             mock.patch("app.indexer.call_groq_with_system", return_value="desde groq") as m_groq:
            out = indexer.call_llm("hola")
        assert out == "desde groq"
        m_groq.assert_called_once()

    def test_uses_gemini_config_not_groq_constants(self):
        from app import indexer
        captured = {}

        def _capture(url, params=None, json=None, timeout=None):
            captured.update(json)
            return _fake_response(text="ok")

        with mock.patch("httpx.post", side_effect=_capture):
            indexer.call_llm("hola")
        assert captured["generationConfig"]["maxOutputTokens"] == gc.GEMINI_MAX_TOKENS
