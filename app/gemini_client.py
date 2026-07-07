"""Cliente Gemini 2.5 Flash — adapter multi-proveedor (gemini-natural-recruiter D1/D2).

REST vía httpx (sin dependencia nueva). thinkingBudget=0 SIEMPRE en llamadas JSON
(hallazgo del eval 2026-07-07: el thinking por default consume maxOutputTokens y
trunca el JSON). Cutover por FUNCIÓN vía env (`LLM_*_PROVIDER`), con fallback
automático a Groq si Gemini falla/agota cuota — cada corte es independiente y
reversible. Ver openspec/changes/gemini-natural-recruiter/design.md.
"""
from __future__ import annotations

import base64
import os

import httpx

_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
_DEFAULT_MODEL = "gemini-2.5-flash"


class GeminiError(RuntimeError):
    """Fallo de la llamada a Gemini (HTTP, timeout, o respuesta sin contenido)."""


def _api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise GeminiError("missing_gemini_api_key")
    return key


def _timeout() -> httpx.Timeout:
    secs = float(os.getenv("GEMINI_TIMEOUT_SECONDS", "20"))
    return httpx.Timeout(secs, connect=5.0)


def _post(body: dict, *, model: str | None = None) -> str:
    url = f"{_API_BASE}/{model or _DEFAULT_MODEL}:generateContent"
    try:
        r = httpx.post(url, params={"key": _api_key()}, json=body, timeout=_timeout())
    except httpx.TimeoutException as exc:
        raise GeminiError(f"timeout: {exc}") from exc
    except httpx.HTTPError as exc:
        raise GeminiError(f"http_error: {exc}") from exc
    if r.status_code == 429:
        raise GeminiError("rate_limited")
    if r.status_code != 200:
        raise GeminiError(f"http_{r.status_code}: {r.text[:200]}")
    try:
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as exc:
        raise GeminiError(f"empty_response: {exc}") from exc


def generate_text(
    prompt: str,
    *,
    system: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 500,
) -> str:
    """Generación conversacional (equivalente a call_groq_with_system)."""
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    return _post(body).strip()


def generate_json(
    prompt: str,
    *,
    system: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 1200,
) -> str:
    """Llamada JSON mode (equivalente a call_groq_json). thinkingBudget=0 SIEMPRE
    (D2): sin esto, el thinking consume maxOutputTokens y el JSON llega truncado."""
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
            "responseMimeType": "application/json",
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    return _post(body).strip()


def generate_vision(
    image_bytes: bytes,
    prompt: str,
    *,
    mime_type: str = "image/jpeg",
    json_mode: bool = False,
    max_tokens: int = 400,
) -> str:
    """Clasificación + extracción de imagen en una sola llamada (equivalente a
    call_groq_vision, pero puede devolver JSON estructurado directo)."""
    if not image_bytes:
        raise GeminiError("empty_image_bytes")
    b64 = base64.b64encode(image_bytes).decode("ascii")
    generation_config = {"temperature": 0.0, "maxOutputTokens": max_tokens}
    if json_mode:
        generation_config["responseMimeType"] = "application/json"
        generation_config["thinkingConfig"] = {"thinkingBudget": 0}
    body = {
        "contents": [{
            "parts": [
                {"inlineData": {"mimeType": mime_type, "data": b64}},
                {"text": prompt},
            ]
        }],
        "generationConfig": generation_config,
    }
    return _post(body).strip()


# ── Dispatch por función con fallback automático a Groq (D1) ──────────────────
# Cutover independiente y reversible: LLM_GENERATION_PROVIDER / LLM_VISION_PROVIDER
# / LLM_AUDIO_PROVIDER / LLM_EXTRACTOR_PROVIDER en {"groq"(default), "gemini"}.

def _provider(env_name: str) -> str:
    return (os.getenv(env_name) or "groq").strip().lower()


def dispatch_generation(system: str, user: str, *, temperature: float | None = None,
                         max_tokens: int = 300) -> str:
    """Equivalente de propósito a call_groq_with_system, con cutover por env."""
    from app.indexer import call_groq_with_system

    if _provider("LLM_GENERATION_PROVIDER") != "gemini":
        return call_groq_with_system(system, user, temperature=temperature, max_tokens=max_tokens)
    try:
        return generate_text(user, system=system, temperature=temperature or 0.0, max_tokens=max_tokens)
    except GeminiError as exc:
        print(f"[gemini_fallback] generation -> groq: {exc}", flush=True)
        return call_groq_with_system(system, user, temperature=temperature, max_tokens=max_tokens)


def dispatch_vision(image_bytes: bytes, prompt: str, *, mime_type: str = "image/jpeg",
                     json_mode: bool = False, groq_fallback_kwargs: dict | None = None) -> str:
    """Equivalente de propósito a call_groq_vision, con cutover por env.

    ``groq_fallback_kwargs`` se pasa a call_groq_vision (is_sticker, etc.) — el
    prompt de Gemini y el de Groq pueden diferir (system_prompt vs prompt inline).
    """
    from app.indexer import call_groq_vision

    if _provider("LLM_VISION_PROVIDER") != "gemini":
        return call_groq_vision(image_bytes, mime_type=mime_type, **(groq_fallback_kwargs or {}))
    try:
        return generate_vision(image_bytes, prompt, mime_type=mime_type, json_mode=json_mode)
    except GeminiError as exc:
        print(f"[gemini_fallback] vision -> groq: {exc}", flush=True)
        return call_groq_vision(image_bytes, mime_type=mime_type, **(groq_fallback_kwargs or {}))


def transcribe_audio(
    audio_bytes: bytes,
    prompt: str,
    *,
    mime_type: str = "audio/ogg",
    max_tokens: int = 400,
) -> str:
    """Transcripción de audio nativa (Fase G2). El prompt incluye el glosario
    trailero para evitar destrozos de jerga (fulero→futbol observado con Whisper)."""
    if not audio_bytes:
        raise GeminiError("empty_audio_bytes")
    b64 = base64.b64encode(audio_bytes).decode("ascii")
    body = {
        "contents": [{
            "parts": [
                {"inlineData": {"mimeType": mime_type, "data": b64}},
                {"text": prompt},
            ]
        }],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": max_tokens},
    }
    return _post(body).strip()
