"""G4 — media_guard a nivel del webhook de Chatwoot (agnóstico al canal).

Cubre:
- Audio: transcripción existente (no cambia).
- Imagen/sticker: ahora van por visión Groq → si devuelve texto ≥3 chars, se encola;
  si falla/vacío → fallback acotado y media_guard.
- Adjunto no soportado (doc/video): fallback acotado (comportamiento anterior).
- Tests unit de los helpers _detect_visual_attachment y _classify_attachment.
- Test unit de call_groq_vision con fallback de clave.
"""
from __future__ import annotations

import asyncio
import base64
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

TOKEN = "test-token"
CHANNELS = ["telegram", "whatsapp"]

# ─────────────────────────────────────────────────────────────────────────────
# Helpers de payload
# ─────────────────────────────────────────────────────────────────────────────

def _payload(*, attachments=None, content="", channel_type="telegram"):
    return {
        "event": "message_created",
        "message_type": "incoming",
        "content": content,
        "id": 123,
        "account": {"id": 1},
        "conversation": {"id": 99, "meta": {"channel": channel_type}},
        "inbox": {"id": 7, "channel_type": channel_type, "name": channel_type.title()},
        "sender": {"id": 555, "name": "Demo"},
        "attachments": attachments or [],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Fixture base del client (sin mock de visión — se añade por test)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("CHATWOOT_WEBHOOK_TOKEN", TOKEN)
    monkeypatch.setenv("INBOUND_DEBOUNCE_ENABLED", "false")
    monkeypatch.setenv("WEBHOOK_RATE_LIMIT_ENABLED", "false")

    import app.app as A

    sent: dict = {}

    async def fake_send(account_id, conversation_id, content):
        sent.update(account_id=account_id, conversation_id=conversation_id, content=content)
        return {"ok": True}

    called = {"orchestrator": 0}

    def fake_orchestrator(**kwargs):
        called["orchestrator"] += 1
        return {}

    monkeypatch.setattr(A, "_send_chatwoot_message", fake_send)
    monkeypatch.setattr(A, "run_hr_graph_message", fake_orchestrator)

    return TestClient(A.app), sent, called


# ─────────────────────────────────────────────────────────────────────────────
# 6.1 — Unit: _detect_visual_attachment y _classify_attachment
# ─────────────────────────────────────────────────────────────────────────────

def test_detect_visual_image():
    from app.app import _detect_visual_attachment
    payload = _payload(attachments=[{"file_type": "image", "data_url": "http://x/img.jpg"}])
    url, kind = _detect_visual_attachment(payload)
    assert kind == "image"
    assert url == "http://x/img.jpg"


def test_detect_visual_sticker_by_filetype():
    from app.app import _detect_visual_attachment
    payload = _payload(attachments=[{"file_type": "sticker", "data_url": "http://x/s.webp"}])
    url, kind = _detect_visual_attachment(payload)
    assert kind == "sticker"


def test_detect_visual_sticker_by_extension():
    from app.app import _detect_visual_attachment
    payload = _payload(attachments=[{"file_type": "image", "data_url": "http://x/s.webp"}])
    url, kind = _detect_visual_attachment(payload)
    assert kind == "sticker"


def test_detect_visual_audio_returns_none():
    from app.app import _detect_visual_attachment
    payload = _payload(attachments=[{"file_type": "audio", "data_url": "http://x/a.ogg"}])
    url, kind = _detect_visual_attachment(payload)
    assert kind == ""
    assert url is None


def test_detect_visual_no_attachment():
    from app.app import _detect_visual_attachment
    url, kind = _detect_visual_attachment(_payload())
    assert kind == ""
    assert url is None


def test_detect_visual_nested_message_attachments():
    from app.app import _detect_visual_attachment
    payload = _payload(attachments=[])
    payload["message"] = {"attachments": [{"file_type": "image", "data_url": "http://x/img.png"}]}
    url, kind = _detect_visual_attachment(payload)
    assert kind == "image"


def test_classify_attachment_audio():
    from app.app import _classify_attachment
    p = _payload(attachments=[{"file_type": "audio", "data_url": "x"}])
    assert _classify_attachment(p) == "audio"


def test_classify_attachment_audio_by_content_type():
    from app.app import _classify_attachment, _detect_audio_attachment
    p = _payload(attachments=[{
        "file_type": "file",
        "data_url": "http://x/active-storage/blob",
        "content_type": "audio/ogg",
    }])
    assert _classify_attachment(p) == "audio"
    assert _detect_audio_attachment(p) == ("http://x/active-storage/blob", "audio/ogg")


def test_classify_attachment_audio_by_voice_filetype():
    from app.app import _classify_attachment
    p = _payload(attachments=[{"file_type": "voice", "data_url": "http://x/blob"}])
    assert _classify_attachment(p) == "audio"


def test_classify_attachment_audio_by_extension():
    from app.app import _classify_attachment, _detect_audio_attachment
    p = _payload(attachments=[{"file_type": "file", "data_url": "http://x/audio.oga"}])
    assert _classify_attachment(p) == "audio"
    assert _detect_audio_attachment(p) == ("http://x/audio.oga", "audio/ogg")


def test_classify_attachment_image():
    from app.app import _classify_attachment
    p = _payload(attachments=[{"file_type": "image", "data_url": "http://x/img.jpg"}])
    assert _classify_attachment(p) == "image"


def test_classify_attachment_sticker():
    from app.app import _classify_attachment
    p = _payload(attachments=[{"file_type": "sticker", "data_url": "http://x/s.webp"}])
    assert _classify_attachment(p) == "sticker"


def test_classify_attachment_other():
    from app.app import _classify_attachment
    p = _payload(attachments=[{"file_type": "file", "data_url": "http://x/doc.pdf"}])
    # file_type="file" sin extensión de imagen → other
    assert _classify_attachment(p) == "other"


def test_classify_attachment_none():
    from app.app import _classify_attachment
    assert _classify_attachment(_payload()) == "none"


# ─────────────────────────────────────────────────────────────────────────────
# 6.2 — Unit: visión Gemini degrada a media_guard contract
# ─────────────────────────────────────────────────────────────────────────────

def test_dispatch_vision_rate_limit_returns_empty(monkeypatch):
    """Visión Gemini-único: 429 devuelve '' y el webhook aplica media_guard."""
    import app.gemini_client as GC

    class FakeResp:
        status_code = 429
        text = "rate limit"

        def json(self):
            return {}

    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    with patch("httpx.post", return_value=FakeResp()):
        assert GC.dispatch_vision(b"\x89PNG\r\n", "clasifica") == ""


# ─────────────────────────────────────────────────────────────────────────────
# 6.3 — Integración webhook: imagen con dato de funnel → encola, sin enlatado
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("channel_type", CHANNELS)
def test_image_with_funnel_data_enqueues(client, monkeypatch, channel_type):
    """Imagen procesada por visión → content sobreescrito, pipeline corre, NO enlatado."""
    import app.app as A

    c, sent, called = client

    async def fake_vision_download(*a, **kw):
        pass

    # dispatch_vision (gemini-natural-recruiter B4) reemplazó la llamada directa a
    # call_groq_vision en app.py; se mockea en el punto de llamada real.
    import app.gemini_client as GC
    monkeypatch.setattr(GC, "dispatch_vision", lambda *a, **kw: "licencia tipo E")

    # Mock de descarga HTTP dentro del webhook
    class FakeResp:
        content = b"\xff\xd8\xff"  # bytes JPEG mínimos
        status_code = 200
        def raise_for_status(self): pass

    class FakeAsyncClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, **kw): return FakeResp()

    monkeypatch.setattr(A.httpx, "AsyncClient", lambda **kw: FakeAsyncClient())

    r = c.post(
        "/chatwoot/webhook",
        params={"token": TOKEN},
        json=_payload(
            attachments=[{"file_type": "image", "data_url": "http://x/img.jpg"}],
            content="",
            channel_type=channel_type,
        ),
    )
    body = r.json()
    # No debe ser media_guard — el pipeline debe haber corrido
    assert body["status"] != "media_guard", f"Esperaba pipeline, got {body}"
    assert called["orchestrator"] == 1
    # No se emitió reply enlatado de rechazo al candidato
    assert "content" not in sent or "no puedo revisar" not in sent.get("content", "")


# ─────────────────────────────────────────────────────────────────────────────
# 6.4 — Integración webhook: sticker afirmativo → encola texto de intención
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("channel_type", CHANNELS)
def test_sticker_intent_enqueues(client, monkeypatch, channel_type):
    """Sticker procesado por visión → intención textual encolada, pipeline corre."""
    import app.app as A

    c, sent, called = client

    import app.gemini_client as GC
    monkeypatch.setattr(GC, "dispatch_vision", lambda *a, **kw: "afirmativo")

    class FakeResp:
        content = b"RIFF"  # bytes mínimos webp-like
        status_code = 200
        def raise_for_status(self): pass

    class FakeAsyncClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, **kw): return FakeResp()

    monkeypatch.setattr(A.httpx, "AsyncClient", lambda **kw: FakeAsyncClient())

    r = c.post(
        "/chatwoot/webhook",
        params={"token": TOKEN},
        json=_payload(
            attachments=[{"file_type": "sticker", "data_url": "http://x/s.webp"}],
            content="",
            channel_type=channel_type,
        ),
    )
    body = r.json()
    assert body["status"] != "media_guard", f"Esperaba pipeline, got {body}"
    assert called["orchestrator"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# 6.5 — Imagen/sticker no procesable → fallback acotado, no encola
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("att", [
    [{"file_type": "image", "data_url": "http://x/img.jpg"}],
    [{"file_type": "sticker", "data_url": "http://x/s.webp"}],
])
def test_image_sticker_vision_fails_media_guard(client, monkeypatch, att):
    """Visión devuelve vacío → fallback acotado, sin encolar."""
    import app.app as A

    c, sent, called = client

    import app.gemini_client as GC
    monkeypatch.setattr(GC, "dispatch_vision", lambda *a, **kw: "")

    class FakeResp:
        content = b"\x00"
        status_code = 200
        def raise_for_status(self): pass

    class FakeAsyncClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, **kw): return FakeResp()

    monkeypatch.setattr(A.httpx, "AsyncClient", lambda **kw: FakeAsyncClient())

    r = c.post(
        "/chatwoot/webhook",
        params={"token": TOKEN},
        json=_payload(attachments=att, content=""),
    )
    body = r.json()
    assert body["status"] == "media_guard"
    assert body.get("extracted") is False and body.get("enqueued") is False
    assert called["orchestrator"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# 6.6 — Adjunto no soportado (doc/video) → fallback acotado
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("att", [
    [{"file_type": "file", "data_url": "http://x/doc.pdf"}],
    [{"file_type": "video", "data_url": "http://x/vid.mp4"}],
])
def test_unsupported_attachment_media_guard(client, att):
    """Adjuntos no soportados (doc/video) siguen al fallback acotado."""
    c, sent, called = client
    r = c.post(
        "/chatwoot/webhook",
        params={"token": TOKEN},
        json=_payload(attachments=att, content=""),
    )
    body = r.json()
    assert body["status"] == "media_guard"
    assert body.get("extracted") is False and body.get("enqueued") is False
    assert called["orchestrator"] == 0
    # El fallback acotado se emite para adjuntos no soportados
    assert "content" in sent


# ─────────────────────────────────────────────────────────────────────────────
# Casos de robustez previos (conservados)
# ─────────────────────────────────────────────────────────────────────────────

def test_media_nested_message_attachments_doc(client):
    """Robustez: attachments de tipo doc anidados en message.attachments → media_guard."""
    c, sent, called = client
    payload = _payload(attachments=[], content="")
    payload["message"] = {"attachments": [{"file_type": "file", "data_url": "x"}]}
    r = c.post("/chatwoot/webhook", params={"token": TOKEN}, json=payload)
    assert r.json()["status"] == "media_guard"
    assert called["orchestrator"] == 0


@pytest.mark.parametrize("attachments", [
    [{"id": 555}],
    [{"message_id": 9}],
    [{"extension": "pdf"}],
    [{"foo": "bar"}],
])
def test_media_atypical_attachment_dict(client, attachments):
    """Robustez: cualquier attachment dict no vacío sin file_type conocida → media_guard."""
    c, sent, called = client
    r = c.post("/chatwoot/webhook", params={"token": TOKEN}, json=_payload(attachments=attachments, content=""))
    assert r.json()["status"] == "media_guard"
    assert called["orchestrator"] == 0


def test_empty_attachment_dict_is_not_media(client):
    """Un attachment vacío {} no debe contar como media (evita falsos positivos)."""
    c, sent, called = client
    r = c.post("/chatwoot/webhook", params={"token": TOKEN}, json=_payload(attachments=[{}], content="tengo licencia tipo E"))
    assert r.json()["status"] != "media_guard"
    assert called["orchestrator"] == 1


def test_text_only_passes(client):
    c, sent, called = client
    r = c.post(
        "/chatwoot/webhook",
        params={"token": TOKEN},
        json=_payload(attachments=[], content="tengo licencia tipo E"),
    )
    assert r.json()["status"] != "media_guard"
    assert called["orchestrator"] == 1


def test_debounce_on_image_vision_success(client, monkeypatch):
    """Con debounce ON, imagen procesada exitosamente se encola (no media_guard)."""
    import app.app as A

    monkeypatch.setenv("INBOUND_DEBOUNCE_ENABLED", "true")
    c, sent, called = client

    import app.gemini_client as GC
    monkeypatch.setattr(GC, "dispatch_vision", lambda *a, **kw: "licencia tipo E")

    class FakeResp:
        content = b"\xff\xd8\xff"
        status_code = 200
        def raise_for_status(self): pass

    class FakeAsyncClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, **kw): return FakeResp()

    monkeypatch.setattr(A.httpx, "AsyncClient", lambda **kw: FakeAsyncClient())

    r = c.post(
        "/chatwoot/webhook",
        params={"token": TOKEN},
        json=_payload(attachments=[{"file_type": "image", "data_url": "http://x/img.jpg"}], content=""),
    )
    # Con debounce ON y visión exitosa se encola; la respuesta es "enqueued" no "media_guard"
    assert r.json()["status"] != "media_guard"
