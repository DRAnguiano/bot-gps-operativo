"""Cliente Gemini 2.5 Flash — proveedor LLM único.

REST vía httpx (sin dependencia nueva). thinkingBudget=0 SIEMPRE en llamadas JSON
(hallazgo del eval 2026-07-07: el thinking por default consume maxOutputTokens y
trunca el JSON). Default: Flash para dar más margen de RPM en pruebas y
staging; `GEMINI_MODEL` permite override explícito.
"""
from __future__ import annotations

import base64
import os

import httpx

_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
_DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
# gemini-2.5-flash fue RETIRADO por Google (404 "no longer available", verificado
# 2026-07-08 en vivo). gemini-3.5-flash confirmado disponible (503 de sobrecarga
# transitoria, no 404 — el modelo existe). Revisar `GET /v1beta/models` si vuelve
# a fallar: los IDs de modelo de Gemini no son estables a largo plazo.

# Config propia de Gemini (no se reciclan las constantes GROQ_*, deprecadas):
GEMINI_MAX_TOKENS = int(os.getenv("GEMINI_MAX_TOKENS", "500") or 500)
GEMINI_TEMPERATURE = float(os.getenv("GEMINI_TEMPERATURE", os.getenv("TEMPERATURE", "0.0")) or 0.0)


class GeminiError(RuntimeError):
    """Fallo de la llamada a Gemini (HTTP, timeout, o respuesta sin contenido)."""


def _api_keys() -> list[tuple[str, str]]:
    keys: list[tuple[str, str]] = []
    primary = os.environ.get("GEMINI_API_KEY")
    backup = os.environ.get("GEMINI_API_KEY_BACKUP")
    if primary:
        keys.append(("primary", primary))
    if backup and backup != primary:
        keys.append(("backup", backup))
    if not keys:
        raise GeminiError("missing_gemini_api_key")
    return keys


def _timeout() -> httpx.Timeout:
    secs = float(os.getenv("GEMINI_TIMEOUT_SECONDS", "20"))
    return httpx.Timeout(secs, connect=5.0)


def _post(body: dict, *, model: str | None = None) -> str:
    url = f"{_API_BASE}/{model or _DEFAULT_MODEL}:generateContent"
    last_exc: GeminiError | None = None
    for idx, (label, key) in enumerate(_api_keys()):
        try:
            r = httpx.post(url, params={"key": key}, json=body, timeout=_timeout())
        except httpx.TimeoutException as exc:
            last_exc = GeminiError(f"timeout: {exc}")
        except httpx.HTTPError as exc:
            last_exc = GeminiError(f"http_error: {exc}")
        else:
            if r.status_code == 429:
                last_exc = GeminiError("rate_limited")
            elif r.status_code != 200:
                last_exc = GeminiError(f"http_{r.status_code}: {r.text[:200]}")
            else:
                try:
                    return r.json()["candidates"][0]["content"]["parts"][0]["text"]
                except (KeyError, IndexError) as exc:
                    last_exc = GeminiError(f"empty_response: {exc}")
                else:
                    last_exc = None

        if last_exc is not None and idx + 1 < len(_api_keys()):
            print(f"[gemini_fallback] {label} falló, usando backup", flush=True)
            continue
        if last_exc is not None:
            raise last_exc
    raise GeminiError("missing_gemini_api_key")


def generate_text(
    prompt: str,
    *,
    system: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 500,
) -> str:
    """Generación conversacional (equivalente a call_groq_with_system).

    thinkingBudget=0 SIEMPRE (mismo criterio que D2 para JSON): bug en vivo
    2026-07-07 — sin esto, Gemini gasta parte de maxOutputTokens en razonamiento
    invisible y el texto visible llega cortado a media palabra ("El pago en Trans").
    Fiabilidad de respuesta completa pesa más que el margen de "pensamiento".
    """
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
            "thinkingConfig": {"thinkingBudget": 0},
        },
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


# ── Dispatch por función — Gemini PRIMARIO, Groq fallback TEMPORAL ────────────
# TEMPORAL (2026-07-09): gemini-3.5-flash está devolviendo 503 "high demand"
# sostenido en ambas keys (primaria y backup). Mientras se estabiliza o se
# contrata el tier pago, cada dispatch cae a Groq (`call_groq_*`, restauradas en
# indexer.py con las 4 keys/orgs) ANTE FALLO — Gemini sigue siendo el intento
# PRIMARIO siempre; Groq nunca se llama si Gemini responde. Retirar este fallback
# cuando Gemini se estabilice (ver openspec/changes/gemini-full-provider-migration).

def dispatch_generation(system: str, user: str, *, temperature: float | None = None,
                         max_tokens: int = 300) -> str:
    """Generación conversacional con system prompt (persona Mundo, acuses,
    reencauces). Gemini primario; ante fallo cae a Groq (temporal)."""
    try:
        return generate_text(user, system=system, temperature=temperature or 0.0, max_tokens=max_tokens)
    except GeminiError as exc:
        print(f"[gemini_fallback] generation -> groq (temporal): {exc}", flush=True)
        from app.indexer import call_groq_with_system
        return call_groq_with_system(system, user, temperature=temperature, max_tokens=max_tokens)


def dispatch_json(prompt: str, system_message: str, *, temperature: float = 0.0) -> str:
    """Extracción/clasificación JSON (orden posicional prompt, system — herencia del
    contrato anterior). Devuelve el string JSON crudo. Gemini primario; ante fallo
    cae a Groq (temporal) antes de devolver el contrato de error."""
    try:
        return generate_json(prompt, system=system_message, temperature=temperature)
    except GeminiError as exc:
        print(f"[gemini_fallback] json -> groq (temporal): {exc}", flush=True)
        try:
            from app.indexer import call_groq_json
            return call_groq_json(prompt, system_message, temperature=temperature)
        except Exception as exc2:
            print(f"[gemini_json] Error tras fallback: {exc2}", flush=True)
            return '{"error": "gemini_error"}'


def dispatch_vision(image_bytes: bytes, prompt: str, *, mime_type: str = "image/jpeg",
                     json_mode: bool = False, groq_fallback_kwargs: dict | None = None) -> str:
    """Visión de documentos. Gemini primario; ante fallo cae a Groq (temporal)
    antes de devolver '' (media guard acotado)."""
    try:
        return generate_vision(image_bytes, prompt, mime_type=mime_type, json_mode=json_mode)
    except GeminiError as exc:
        print(f"[gemini_fallback] vision -> groq (temporal): {exc}", flush=True)
        try:
            from app.indexer import call_groq_vision
            return call_groq_vision(image_bytes, mime_type=mime_type, **(groq_fallback_kwargs or {}))
        except Exception as exc2:
            print(f"[gemini_vision] Error tras fallback: {exc2}", flush=True)
            return ""


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
        "generationConfig": {
            "temperature": 0.0,
            "maxOutputTokens": max_tokens,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    return _post(body).strip()


# Glosario trailero para transcripción FIEL (bug en vivo conv 163: Whisper destrozó
# "fulero"→"futbol"). Solo transcripción — el análisis de tono queda fuera (no es
# requisito hoy; ver open question del design de gemini-natural-recruiter).
_AUDIO_TRANSCRIBE_PROMPT = (
    "Transcribe FIELMENTE este audio en español mexicano de un candidato a operador "
    "de tractocamión. Devuelve SOLO la transcripción, sin comentarios.\n"
    "Glosario de jerga del dominio (respeta estos términos tal cual si los oyes, no "
    "los sustituyas por palabras parecidas): fulero/fulera (operador de tracto full), "
    "full, sencillo, doble articulado, doble, caja seca, quinta rueda, torton, rabón, "
    "tracto, tráiler, apto médico, licencia federal, R-Control, Transmontes, "
    "semanas del IMSS, cartas laborales, La Laguna, Torreón, Gómez Palacio, Lerdo.\n"
    "Los nombres y apellidos del candidato son HISPANOS (p. ej. Elizondo, Elías, "
    "Eliezer, Munera, Anguiano): no los anglicanices (Elizondo≠Ellison) ni los "
    "dividas como artículo + palabra (Elizondo≠'el lizondo', Elías≠'el lisa')."
)


_MIME_TO_AUDIO_EXT = {
    "audio/mpeg": "audio.mp3",
    "audio/wav": "audio.wav",
    "audio/mp4": "audio.m4a",
    "audio/aac": "audio.aac",
    "audio/ogg": "audio.ogg",
    "audio/webm": "audio.webm",
    "audio/amr": "audio.amr",
}


def dispatch_audio(audio_bytes: bytes, *, mime_type: str = "audio/ogg") -> str:
    """Transcripción de nota de voz. Gemini nativo (con glosario trailero) primario;
    ante fallo cae a Groq Whisper (TEMPORAL 2026-07-10 — pierde jerga: fulero→futbol,
    pero transcripción imperfecta supera al audio guard). Solo si ambos fallan
    devuelve '' (el webhook cae al guard acotado)."""
    try:
        return transcribe_audio(audio_bytes, _AUDIO_TRANSCRIBE_PROMPT, mime_type=mime_type)
    except GeminiError as exc:
        print(f"[gemini_fallback] audio -> groq whisper (temporal): {exc}", flush=True)
        try:
            from app.indexer import call_groq_transcribe
            filename = _MIME_TO_AUDIO_EXT.get(mime_type, "audio.ogg")
            return call_groq_transcribe(audio_bytes, filename)
        except Exception as exc2:
            print(f"[gemini_audio] Error tras fallback: {exc2}", flush=True)
            return ""
