"""Entry HTTP (FastAPI) del asistente de reclutamiento "Mundo".

Responsabilidad: recibir el webhook de Chatwoot, aplicar las defensas de borde
y encolar el trabajo. NO orquesta ni genera respuestas — eso vive en el worker
(`tasks_chatwoot.py` → `orchestrators/knowledge_orchestrator.py`).

Defensas de borde en el path del webhook (`/chatwoot/webhook`):
- auth **fail-closed** (sin API key válida ⇒ 401),
- filtros de evento (ignora eventos no entrantes / sin contenido útil),
- rate limit en Redis db2 (separado del broker Celery en db1),
- `media_guard` (G4): mensajes con attachments se cortan ANTES de extraer u
  orquestar — no hay OCR; ver `_chatwoot_has_media`.

`/classify` es un endpoint **aislado de prueba** del pipeline multi-intent
(shadow): no persiste ni envía a Chatwoot, no es el path de producción.
"""
import time
import traceback
import os
import json
import re
import httpx

from fastapi import FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse, ORJSONResponse
from pydantic import BaseModel

import asyncio
from .indexer import build_index, call_llm, retrieve_context_for_guardrail, _to_int
from .graphs.hr_graph import run_hr_graph_message
from .db import get_conn, make_conversation_key
from .persona_config import SYSTEM_PROMPT
from .settings import INCLUDE_ERROR_DETAILS, REINDEX_API_KEY, INTERNAL_API_KEY
from .chatwoot_note_sync import (
    TERMINAL_LABELS,
    _filter_official_labels,
    sync_chatwoot_candidate_note,
)

app = FastAPI(default_response_class=ORJSONResponse)

_DEV_WEBHOOK_TOKEN = "dev_chatwoot_webhook_token_123"
_IS_PRODUCTION = os.getenv("APP_ENV", "").lower() == "production"


@app.on_event("startup")
def _validate_security_config() -> None:
    """Valida configuración de seguridad al arrancar.

    En producción (APP_ENV=production) falla con RuntimeError si faltan secretos
    críticos. En otros entornos solo emite warnings.
    """
    from .settings import INTERNAL_API_KEY, REINDEX_API_KEY
    chatwoot_token = os.getenv("CHATWOOT_WEBHOOK_TOKEN", "")
    issues = []
    if not INTERNAL_API_KEY:
        issues.append("INTERNAL_API_KEY está vacía — endpoints internos denegarán todo acceso")
    if not REINDEX_API_KEY:
        issues.append("REINDEX_API_KEY está vacía — /reindex denegará todo acceso")
    if not chatwoot_token:
        issues.append("CHATWOOT_WEBHOOK_TOKEN está vacío — webhook denegará todo acceso")
    elif chatwoot_token == _DEV_WEBHOOK_TOKEN:
        issues.append("CHATWOOT_WEBHOOK_TOKEN usa el valor de desarrollo — rotar antes de producción")
    if issues:
        msg = "[SECURITY] Configuración insegura detectada:\n" + "\n".join(f"  - {i}" for i in issues)
        if _IS_PRODUCTION:
            raise RuntimeError(msg)
        else:
            print(msg, flush=True)


_rl_redis_client = None


def _rate_limit_redis():
    """Lazy singleton Redis client on db 2 (separate from Celery on db 1)."""
    global _rl_redis_client
    if _rl_redis_client is None:
        try:
            import redis as _r
            url = os.getenv("CELERY_BROKER_URL", "redis://chatwoot_redis:6379/1")
            rl_url = re.sub(r"/\d+$", "/2", url)
            _rl_redis_client = _r.from_url(rl_url, decode_responses=True)
        except Exception:
            pass
    return _rl_redis_client


def _clean_llm_answer(text: str) -> str:
    """Limpia la respuesta del LLM — delega al cleaner unificado (rag-corpus #13).

    Antes esta función y `knowledge_orchestrator._clean_reply` eran implementaciones
    divergentes; ahora ambas usan `reply_cleaner.clean_reply` (unión de sus reglas).
    """
    from app.knowledge.reply_cleaner import clean_reply

    return clean_reply(text)


def _source_payload(item: dict) -> dict:
    """
    Normaliza fuentes para respuesta pública/debug.

    Con Rerank activo, indexer.py puede devolver:
    - score: score final usado por filtros
    - rerank_score: score de Cohere Rerank
    - chroma_score: score original de Chroma
    """
    payload = {
        "source": item.get("source"),
        "score": round(item.get("score") or 0, 4),
    }

    if item.get("rerank_score") is not None:
        payload["rerank_score"] = round(item.get("rerank_score") or 0, 4)

    if item.get("chroma_score") is not None:
        payload["chroma_score"] = round(item.get("chroma_score") or 0, 4)

    if item.get("id"):
        payload["id"] = item.get("id")

    return payload


def _split_for_telegram(text: str, limit: int = 3500):
    parts = []
    remaining = text or ""
    while len(remaining) > limit:
        cut = remaining.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        parts.append(remaining[:cut])
        remaining = remaining[cut:]
    if remaining:
        parts.append(remaining)
    return parts


def _public_error(exc: Exception):
    if INCLUDE_ERROR_DETAILS:
        return f"{type(exc).__name__}: {exc}"
    return "internal_error"


@app.get("/health")
def health():
    checks: dict = {}
    all_ok = True

    # ── Postgres ──────────────────────────────────────────────────────────────
    try:
        t0 = time.time()
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 AS ok")
        checks["postgres"] = {"ok": True, "ms": round((time.time() - t0) * 1000, 1)}
    except Exception as exc:
        checks["postgres"] = {"ok": False, "error": str(exc)[:120]}
        all_ok = False

    # ── Neo4j ─────────────────────────────────────────────────────────────────
    try:
        t0 = time.time()
        from .knowledge.neo4j_client import get_knowledge_client
        neo4j_ok = get_knowledge_client().healthcheck()
        checks["neo4j"] = {"ok": bool(neo4j_ok.get("ok")), "ms": round((time.time() - t0) * 1000, 1)}
        if not neo4j_ok.get("ok"):
            all_ok = False
    except Exception as exc:
        checks["neo4j"] = {"ok": False, "error": str(exc)[:120]}
        all_ok = False

    # ── ChromaDB ──────────────────────────────────────────────────────────────
    try:
        t0 = time.time()
        from .indexer import _get_collection
        col = _get_collection()
        checks["chromadb"] = {"ok": True, "docs": col.count(), "ms": round((time.time() - t0) * 1000, 1)}
    except Exception as exc:
        checks["chromadb"] = {"ok": False, "error": str(exc)[:120]}
        all_ok = False

    status_code = 200 if all_ok else 503
    return JSONResponse(
        status_code=status_code,
        content={"status": "ok" if all_ok else "degraded", "checks": checks},
    )


class ReindexBody(BaseModel):
    top_k: int | None = None


@app.post("/reindex")
def reindex(
    body: ReindexBody | None = None,
    k: int | None = Query(default=None),
    x_api_key: str | None = Header(default=None),
):
    if not REINDEX_API_KEY or x_api_key != REINDEX_API_KEY:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})

    started = time.time()
    top_k = _to_int(k, _to_int(getattr(body, "top_k", None), 3))

    try:
        stats = build_index()
        return {
            "status": "ok",
            "top_k": top_k,
            "index": stats,
            "elapsed_s": round(time.time() - started, 2),
        }
    except Exception as exc:
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"status": "error", "error": _public_error(exc)},
        )


class AskBody(BaseModel):
    q: str
    history: str | None = ""
    top_k: int | None = None


class OrchestrateMessageBody(BaseModel):
    channel: str = "telegram_demo"
    channel_user_id: str
    username: str | None = None
    phone: str | None = None
    message: str
    external_message_id: str | None = None


@app.post("/ask")
def ask(body: AskBody, x_api_key: str | None = Header(default=None)):
    """
    Endpoint RAG original.
    Lo conservamos para compatibilidad con el workflow actual.
    """
    # [NOTA] Este endpoint es legacy — hace RAG directo sin perfil ni memoria de
    # lead. Fue el primer endpoint del sistema antes del orquestador.
    # En el flujo normal de Chatwoot/Telegram nunca se llama; solo se usa en
    # pruebas manuales o integraciones antiguas.
    # [RIESGO] Si alguien lo llama en paralelo con el webhook, puede generar
    # respuestas inconsistentes con el perfil guardado en Postgres porque no
    # lee ni escribe lead_memory.
    # [MEJORA] Documentar en README que este endpoint está deprecado.
    # No eliminar aún hasta confirmar que ninguna integración externa lo usa.
    if not INTERNAL_API_KEY or x_api_key != INTERNAL_API_KEY:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    try:
        question = body.q.strip()
        history_text = body.history.strip() if body.history else "No hay historial previo."

        ctx = retrieve_context_for_guardrail(question, top_k=body.top_k)
        valid_ctx = [item for item in ctx if (item["score"] or 0) >= 0.30]

        if valid_ctx:
            context_text = "\n\n---\n\n".join(item["text"] for item in valid_ctx)
        else:
            context_text = "No se encontro informacion en los manuales para esta pregunta."

        prompt = f"""
{SYSTEM_PROMPT}

=== HISTORIAL DE LA CONVERSACION RECIENTE ===
{history_text}

=== CONTEXTO RECUPERADO DE LOS MANUALES ===
{context_text}

=== MENSAJE ACTUAL DEL CANDIDATO ===
{question}

INSTRUCCIONES DE RESPUESTA:
1. Responde únicamente con base en el contexto recuperado.
2. Si no hay información suficiente, dilo con claridad y no inventes.
3. No prometas sueldo, contratación, beneficios, rutas, descansos, pago por kilómetro ni condiciones no confirmadas.
4. Si el contexto recuperado trae una cifra o condición específica, puedes mencionarla como "según la información disponible", aclarando que Capital Humano confirma la información final.
5. Si el contexto no trae una cifra o condición específica, no la inventes y di que Capital Humano debe confirmarla.
6. No avances etapas de reclutamiento desde este endpoint.
7. No extraigas ni guardes datos del candidato desde este endpoint.
8. Responde breve, natural y en español.
9. No hagas preguntas de seguimiento.
10. No cierres con frases genéricas como "si tienes otra duda", "puedo ayudarte", "estoy aquí para ayudarte" o similares.
11. Si el dato debe validarlo Capital Humano, dilo de forma natural.

RESPUESTA:
"""
        final = _clean_llm_answer(call_llm(prompt))

        return {
            "text": final,
            "chunks": _split_for_telegram(final),
            "mode": f"hr_recruiting_{os.getenv('LLM_PROVIDER', 'groq').strip().lower()}",
            "sources": [
                _source_payload(item)
                for item in valid_ctx
            ],
        }
    except Exception as exc:
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": _public_error(exc)})


@app.post("/orchestrate/message")
def orchestrate(body: OrchestrateMessageBody, x_api_key: str | None = Header(default=None)):
    """
    Endpoint principal del sistema.

    Este endpoint:
    - crea/actualiza conversación
    - guarda mensaje entrante
    - detecta intención/riesgo
    - extrae datos del candidato
    - consulta RAG si aplica
    - crea handoff humano si aplica
    - guarda eventos analíticos
    - devuelve respuesta lista para Telegram/Chatwoot/WhatsApp
    """
    if not INTERNAL_API_KEY or x_api_key != INTERNAL_API_KEY:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    try:
        result = run_hr_graph_message(
            channel=body.channel,
            channel_user_id=body.channel_user_id,
            username=body.username,
            phone=body.phone,
            message=body.message,
            external_message_id=body.external_message_id,
)
        return result
    except Exception as exc:
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": _public_error(exc)})


class ClassifyBody(BaseModel):
    message: str
    known_facts: dict | None = None
    last_bot_question: str | None = None


@app.post("/classify")
def classify(body: ClassifyBody, x_api_key: str | None = Header(default=None)):
    """Endpoint de prueba del pipeline multi-intent (Fases 1-3).

    Aislado: no persiste ni envía a Chatwoot. Devuelve clasificación, enriquecimiento
    y el plan+respuesta. known_facts simula los campos ya conocidos del lead.
    """
    if not INTERNAL_API_KEY or x_api_key != INTERNAL_API_KEY:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    try:
        from .knowledge.intent_classifier import classify_message
        from .knowledge.intent_enricher import enrich_classification
        from .knowledge.intent_orchestrator import plan_and_respond
        classification = classify_message(body.message, last_bot_question=body.last_bot_question)
        enriched = enrich_classification(classification)
        plan = plan_and_respond(enriched, body.message, body.known_facts)
        return {"classification": classification, "enriched": enriched, "plan": plan}
    except Exception as exc:
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": _public_error(exc)})


class ReleaseHumanReviewBody(BaseModel):
    conversation_key: str
    stage_to: str = "START"


@app.post("/admin/release-human-review")
def release_human_review_endpoint(
    body: ReleaseHumanReviewBody, x_api_key: str | None = Header(default=None)
):
    """Libera una conversación de HUMAN_REVIEW_REQUIRED por acción humana/operativa (#8).

    El bot nunca sale solo de revisión humana (`update_stage` la pin-ea); esta es la
    ÚNICA vía explícita de regreso, pensada para que un agente u operación la invoque
    tras tomar y resolver el caso. Protegido con `INTERNAL_API_KEY`.
    """
    if not INTERNAL_API_KEY or x_api_key != INTERNAL_API_KEY:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    try:
        from .db import release_human_review

        release_human_review(body.conversation_key, stage_to=body.stage_to)
        return {
            "status": "released",
            "conversation_key": body.conversation_key,
            "stage_to": body.stage_to,
        }
    except Exception as exc:
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": _public_error(exc)})


def _extract_chatwoot_contact(payload: dict) -> dict:
    """
    Extrae datos del contacto desde distintas formas de payload de Chatwoot.
    OJO: esta función NO debe tener decorador @app.post.
    """
    sender = payload.get("sender") or {}
    conversation = payload.get("conversation") or {}

    meta = conversation.get("meta") or {}
    sender_from_meta = meta.get("sender") or {}

    contact = sender or sender_from_meta or {}

    contact_id = (
        contact.get("id")
        or payload.get("sender_id")
        or payload.get("contact_id")
        or payload.get("source_id")
    )

    name = (
        contact.get("name")
        or contact.get("email")
        or contact.get("phone_number")
        or sender_from_meta.get("name")
        or sender_from_meta.get("email")
        or sender_from_meta.get("phone_number")
    )

    phone = contact.get("phone_number") or sender_from_meta.get("phone_number")
    email = contact.get("email") or sender_from_meta.get("email")

    return {
        "contact_id": contact_id,
        "name": name,
        "phone": phone,
        "email": email,
    }


def _extract_chatwoot_channel_label(payload: dict) -> str:
    """
    Devuelve un nombre humano del canal real desde donde llegó la conversación.

    Ejemplos:
    - Telegram
    - WhatsApp
    - Webchat
    - Chatwoot
    """
    inbox = payload.get("inbox") or {}
    conversation = payload.get("conversation") or {}
    meta = conversation.get("meta") or {}

    inbox_name = str(inbox.get("name") or "").strip()
    channel_type = str(
        inbox.get("channel_type")
        or inbox.get("channel")
        or meta.get("channel")
        or ""
    ).lower()

    raw_text = f"{inbox_name} {channel_type}".lower()

    if "telegram" in raw_text:
        return "Telegram"

    if "whatsapp" in raw_text or channel_type == "wa":
        return "WhatsApp"

    if "webwidget" in raw_text or "website" in raw_text or "webchat" in raw_text:
        return "Webchat"

    if inbox_name:
        return inbox_name

    return "Chatwoot"


# Reply de fallback acotado del media_guard (G4).
# Se emite SOLO para: fallo de visión en imagen/sticker, o adjunto no soportado (doc/video).
# Las imágenes y stickers exitosamente procesados por visión NO emiten este mensaje.
_MEDIA_GUARD_REPLY = (
    "Gracias por compartirlo. Por el momento no puedo revisar documentos o videos "
    "por este medio. Para continuar con su registro, por favor "
    "respóndame en texto la información solicitada."
)

# Reply canned cuando se recibió audio pero no pudo transcribirse.
_AUDIO_GUARD_REPLY = (
    "Recibí tu audio, pero no pude entenderlo bien. "
    "¿Podrías escribirme en texto lo que me quieres decir?"
)


def _chatwoot_has_media(payload: dict) -> bool:
    """True si el evento entrante de Chatwoot trae attachments (media), agnóstico al canal.

    Cubre imagen, documento, archivo, audio, video y sticker: Chatwoot los expone en
    `attachments` con `file_type`/`data_url`, independiente del canal (Telegram/WhatsApp/...).
    Revisa la ruta top-level y una ruta anidada (`message.attachments`) por robustez ante
    variaciones del payload.
    """
    def _any_media(items) -> bool:
        if not isinstance(items, list):
            return False
        media_keys = {
            "file_type",
            "data_url",
            "thumb_url",
            "extension",
            "file_size",
            "id",
            "message_id",
        }
        return any(
            isinstance(a, dict)
            and (
                any(a.get(k) for k in media_keys)
                or bool(a)
            )
            for a in items
        )

    if _any_media(payload.get("attachments")):
        return True
    message = payload.get("message")
    if isinstance(message, dict) and _any_media(message.get("attachments")):
        return True
    return False


_AUDIO_EXT_TO_MIME = {
    ".mp3": "audio/mpeg",
    ".mpeg": "audio/mpeg",
    ".mpga": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".opus": "audio/ogg",
    ".webm": "audio/webm",
    ".amr": "audio/amr",
}


def _attachment_url_ext(url: str) -> str:
    path = (url or "").lower().split("?", 1)[0].rsplit("/", 1)[-1]
    if "." not in path:
        return ""
    return "." + path.rsplit(".", 1)[-1]


def _attachment_content_type(a: dict) -> str:
    return str(
        a.get("content_type")
        or a.get("contentType")
        or a.get("file_content_type")
        or a.get("mime_type")
        or a.get("mimeType")
        or ""
    ).lower()


def _detect_audio_attachment(payload: dict) -> tuple[str | None, str | None]:
    """Devuelve (url, mime_type) del primer audio, o (None, None).

    Chatwoot normalmente expone file_type=="audio", pero según canal/conector puede
    llegar como voice/recording o como file con content_type/URL de audio.
    Revisa tanto la ruta top-level como message.attachments.
    """
    def _find_audio(items) -> tuple[str | None, str | None]:
        if not isinstance(items, list):
            return None, None
        for a in items:
            if not isinstance(a, dict):
                continue
            ft = str(a.get("file_type") or a.get("fileType") or "").lower()
            url = a.get("data_url") or a.get("download_url") or a.get("file_url") or a.get("thumb_url") or ""
            ctype = _attachment_content_type(a)
            ext = _attachment_url_ext(url)
            is_audio = (
                ft in {"audio", "voice", "voice_message", "recording"}
                or ctype.startswith("audio/")
                or ext in _AUDIO_EXT_TO_MIME
            )
            if is_audio and url:
                return url, ctype if ctype.startswith("audio/") else _AUDIO_EXT_TO_MIME.get(ext)
        return None, None

    result = _find_audio(payload.get("attachments"))
    if result[0]:
        return result
    message = payload.get("message")
    if isinstance(message, dict):
        return _find_audio(message.get("attachments"))
    return None, None


def _detect_audio_url(payload: dict) -> str | None:
    """Devuelve la URL del primer adjunto de audio, o None si no hay audio."""
    return _detect_audio_attachment(payload)[0]


def _detect_visual_attachment(payload: dict) -> tuple[str | None, str]:
    """Devuelve (data_url, tipo) del primer adjunto visual (imagen o sticker), o (None, "").

    Tipos posibles: "image", "sticker".
    - file_type == "sticker" o nombre/extensión .webp → "sticker"
    - file_type in {"image", "file"} con extensión de imagen → "image"
    Revisa ruta top-level y message.attachments.
    """
    _IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif", ".heic", ".heif"}

    def _find_visual(items) -> tuple[str | None, str]:
        if not isinstance(items, list):
            return None, ""
        for a in items:
            if not isinstance(a, dict):
                continue
            ft = (a.get("file_type") or "").lower()
            url = a.get("data_url") or a.get("thumb_url") or ""
            url_lower = url.lower().split("?")[0]
            ext = "." + url_lower.rsplit(".", 1)[-1] if "." in url_lower.rsplit("/", 1)[-1] else ""
            # Sticker explícito por file_type
            if ft == "sticker":
                return url or None, "sticker"
            # file_type == "image" → imagen; si la URL es .webp tratar como sticker
            if ft == "image":
                if ext == ".webp":
                    return url or None, "sticker"
                return url or None, "image"
            # file_type == "file" solo si la extensión de URL es de imagen reconocida
            if ft == "file":
                if ext == ".webp":
                    return url or None, "sticker"
                if ext in _IMAGE_EXTS:
                    return url or None, "image"
        return None, ""

    url, kind = _find_visual(payload.get("attachments"))
    if kind:
        return url, kind
    message = payload.get("message")
    if isinstance(message, dict):
        return _find_visual(message.get("attachments"))
    return None, ""


def _classify_attachment(payload: dict) -> str:
    """Clasifica el tipo de adjunto dominante: 'audio' | 'image' | 'sticker' | 'other' | 'none'.

    Usa la misma lógica de detección que _detect_audio_url y _detect_visual_attachment,
    consolidada en un solo lugar para la rama media_guard.
    """
    if not _chatwoot_has_media(payload):
        return "none"
    if _detect_audio_url(payload):
        return "audio"
    _, kind = _detect_visual_attachment(payload)
    if kind in {"image", "sticker"}:
        return kind
    return "other"


async def _send_chatwoot_message(
    account_id: int | str,
    conversation_id: int | str,
    content: str,
) -> dict:
    """
    Envía una respuesta pública a una conversación de Chatwoot.
    """
    base_url = os.getenv("CHATWOOT_BASE_URL", "").strip().rstrip("/")
    api_token = os.getenv("CHATWOOT_API_TOKEN", "").strip()

    if not base_url:
        raise RuntimeError("CHATWOOT_BASE_URL is not configured")

    if not api_token:
        raise RuntimeError("CHATWOOT_API_TOKEN is not configured")

    url = (
        f"{base_url}/api/v1/accounts/{account_id}"
        f"/conversations/{conversation_id}/messages"
    )

    headers = {
        "api_access_token": api_token,
        "Content-Type": "application/json",
    }

    body = {
        "content": content,
        "message_type": "outgoing",
        "private": False,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(url, headers=headers, json=body)
        response.raise_for_status()
        return response.json()


def _normalize_chatwoot_labels(labels) -> list[str]:
    """
    Normaliza labels sugeridas desde PostgreSQL.
    PostgreSQL puede devolver arrays como list, tuple o string tipo "{a,b}".
    """
    if not labels:
        return []

    if isinstance(labels, str):
        labels = labels.strip()
        if labels.startswith("{") and labels.endswith("}"):
            labels = labels[1:-1].split(",")
        else:
            labels = [labels]

    clean = []
    for label in labels:
        value = str(label or "").strip().lower()
        if value:
            clean.append(value)

    # Chokepoint único: mapea aliases fantasma → oficial y descarta lo que no esté en
    # el catálogo, igual que el path Python. Antes esta función NO filtraba y dejaba
    # pasar labels de la vista SQL (requiere_humano, ubicacion_extranjero, …) a Chatwoot.
    return _filter_official_labels(clean)


def _fallback_chatwoot_labels(result: dict) -> list[str]:
    """
    Labels básicas si por alguna razón no se puede leer v_rh_work_queue.
    Solo labels del catálogo oficial; las terminales remueven bot_activo.

    OJO — ruta DEGRADADA: el criterio de `perfil_listo` aquí es
    `current_stage == "PROFILE_READY"`, distinto del de la ruta principal
    (`chatwoot_note_sync.calculate_candidate_labels`, que exige
    vehículo+licencia+apto+`vacancy_accepted`). Ambas comparten
    `OFFICIAL_LABELS`/`TERMINAL_LABELS` pero pueden discrepar en cuándo emiten
    una label terminal. Deuda registrada en `docs/deuda_tecnica.md` (D-3).
    """
    labels = {"bot_activo"}

    if result.get("requires_human"):
        labels.update({"requiere_agente", "requiere_revision_ch"})

    if result.get("risk_level") == "high":
        labels.update({"riesgo_alto", "requiere_agente"})

    if result.get("current_stage") == "PROFILE_READY":
        labels.update({"perfil_listo", "requiere_revision_ch"})

    if labels & TERMINAL_LABELS:
        labels.discard("bot_activo")

    return _filter_official_labels(labels)


def _get_rh_work_queue_metadata(conversation_key: str) -> dict:
    """
    Consulta la cola operativa RH para traer prioridad, acción recomendada,
    ubicación estructurada, contacto y labels sugeridas para Chatwoot.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    conversation_key,
                    channel,
                    channel_user_id,
                    current_stage,
                    last_intent,

                    nombre_completo,
                    telefono,

                    ciudad,
                    ciudad_raw,
                    estado_region,
                    pais_codigo,
                    pais_nombre,
                    city_group,
                    is_local_laguna,
                    is_foreign_country,
                    location_requires_ch_validation,
                    location_needs_travel_validation,
                    city_catalog_alias,
                    city_catalog_id,

                    risk_level,
                    requires_human,
                    work_priority,
                    work_bucket,
                    recommended_action,
                    suggested_chatwoot_labels,

                    is_profile_ready,
                    has_base_profile_data,
                    is_restrictive_review,
                    needs_location_ch_validation,
                    is_foraneo_mx
                FROM v_rh_work_queue
                WHERE conversation_key = %(conversation_key)s
                LIMIT 1;
                """,
                {"conversation_key": conversation_key},
            )
            row = cur.fetchone()

    return dict(row) if row else {}


async def _set_chatwoot_labels(
    account_id: int | str,
    conversation_id: int | str,
    labels: list[str],
) -> dict:
    """
    Reemplaza/asigna labels a una conversación de Chatwoot.
    """
    clean_labels = _normalize_chatwoot_labels(labels)
    if not clean_labels:
        return {"skipped": True, "reason": "empty_labels"}

    base_url = os.getenv("CHATWOOT_BASE_URL", "").strip().rstrip("/")
    api_token = os.getenv("CHATWOOT_API_TOKEN", "").strip()

    if not base_url:
        raise RuntimeError("CHATWOOT_BASE_URL is not configured")

    if not api_token:
        raise RuntimeError("CHATWOOT_API_TOKEN is not configured")

    url = (
        f"{base_url}/api/v1/accounts/{account_id}"
        f"/conversations/{conversation_id}/labels"
    )

    headers = {
        "api_access_token": api_token,
        "Content-Type": "application/json",
    }

    body = {
        "labels": clean_labels,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(url, headers=headers, json=body)
        response.raise_for_status()
        return response.json()


async def _send_chatwoot_private_note(
    account_id: int | str,
    conversation_id: int | str,
    content: str,
) -> dict:
    """
    Crea una nota interna en la conversación de Chatwoot.
    """
    base_url = os.getenv("CHATWOOT_BASE_URL", "").strip().rstrip("/")
    api_token = os.getenv("CHATWOOT_API_TOKEN", "").strip()

    if not base_url:
        raise RuntimeError("CHATWOOT_BASE_URL is not configured")

    if not api_token:
        raise RuntimeError("CHATWOOT_API_TOKEN is not configured")

    url = (
        f"{base_url}/api/v1/accounts/{account_id}"
        f"/conversations/{conversation_id}/messages"
    )

    headers = {
        "api_access_token": api_token,
        "Content-Type": "application/json",
    }

    body = {
        "content": content,
        "message_type": "outgoing",
        "private": True,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(url, headers=headers, json=body)
        response.raise_for_status()
        return response.json()


def _human_bool(value) -> str:
    """
    Convierte booleanos/valores a texto amigable para notas internas.
    """
    if value is True:
        return "SÍ"
    if value is False:
        return "NO"
    if value is None:
        return "N/D"
    return "SÍ" if bool(value) else "NO"


def _human_required(value) -> str:
    """
    Para textos tipo 'No requerida' / 'Requerida', más claro que SÍ/NO.
    """
    if value is True:
        return "Requerida"
    if value is False:
        return "No requerida"
    return "N/D"


def _human_risk_level(value: str | None) -> str:
    mapping = {
        "low": "Bajo",
        "medium": "Medio",
        "high": "Alto",
    }
    return mapping.get((value or "").lower(), value or "N/D")


def _human_stage(value: str | None) -> str:
    mapping = {
        "START": "Inicio",
        "NEW_LEAD": "Nuevo prospecto",
        "ASK_CITY": "Ciudad pendiente",
        "ASK_LICENSE": "Licencia pendiente",
        "ASK_EXPERIENCE": "Experiencia pendiente",
        "ASK_APTO": "Apto médico pendiente",
        "ASK_AVAILABILITY": "Disponibilidad pendiente",
        "PROFILE_READY": "Perfil listo",
        "CLARIFY_AMBIGUOUS_SLANG": "Aclaración pendiente",
        "HUMAN_REVIEW_REQUIRED": "Revisión restrictiva",
    }
    return mapping.get(value or "", value or "N/D")


def _human_intent(value: str | None) -> str:
    mapping = {
        "candidate_answer": "Respuesta del candidato",
        "document_question": "Pregunta documental",
        "followup_time_question": "Pregunta sobre seguimiento",
        "documents_complete_followup": "Documentación / siguiente paso",
        "foraneo_travel_question": "Pregunta sobre traslado foráneo",
        "foreign_location_validation": "Ubicación extranjera / validar CH",
        "sensitive_handoff": "Tema sensible",
        "rcontrol_or_incident_handoff": "Incidencia / R-Control",
        "salary_sensitive": "Sueldo / validación CH",
        "ambiguous_slang_clarification": "Aclaración de jerga",
        "slang_clarified_safe": "Jerga aclarada",
        "slang_clarification_risky": "Jerga con riesgo",
        "conditional_availability": "Disponibilidad condicionada",
    }
    return mapping.get(value or "", value or "N/D")


def _human_city_group(value: str | None) -> str:
    mapping = {
        "Laguna": "Local Laguna",
        "Foráneo México": "Foráneo",
        "Extranjero / validar C.H.": "Extranjero / validar CH",
        "No catalogada": "No catalogada",
    }
    return mapping.get(value or "", value or "N/D")


def _note_title_from_work_queue(work_queue: dict, labels: list[str]) -> str:
    """
    Título corto y operativo para la nota interna.
    """
    if work_queue.get("is_restrictive_review"):
        return "🤖 Nota IA: Revisión restrictiva"

    if work_queue.get("is_foreign_country"):
        return "🤖 Nota IA: Candidato extranjero"

    if "foraneo" in labels or work_queue.get("is_foraneo_mx"):
        return "🤖 Nota IA: Candidato foráneo"

    if "local_laguna" in labels or work_queue.get("is_local_laguna"):
        return "🤖 Nota IA: Candidato local"

    if work_queue.get("is_profile_ready"):
        return "🤖 Nota IA: Perfil listo"

    return "🤖 Nota IA: Seguimiento de candidato"


def _short_queue_label(work_queue: dict) -> str:
    """
    Convierte work_bucket largo en una lectura corta para RH.

    Prioridad actual:
    1 = perfil listo local
    2 = perfil listo foráneo
    3 = perfil listo extranjero
    4 = perfil listo con dato pendiente
    5 = en proceso
    6 = aclaración pendiente
    7 = posible abandono
    8 = revisión restrictiva / posible no apto
    """
    priority = work_queue.get("work_priority")
    bucket = work_queue.get("work_bucket") or "N/D"

    if priority == 1:
        return "1 - Local listo"
    if priority == 2:
        return "2 - Foráneo listo"
    if priority == 3:
        return "3 - Extranjero listo"
    if priority == 4:
        return "4 - Perfil listo / validar dato"
    if priority == 5:
        return "5 - En proceso"
    if priority == 6:
        return "6 - Aclaración"
    if priority == 7:
        return "7 - Posible abandono"
    if priority == 8:
        return "8 - Revisión restrictiva"

    return bucket


def _build_chatwoot_internal_note(
    result: dict,
    work_queue: dict,
    labels: list[str],
    username: str,
    content: str,
    channel_label: str | None = None,
) -> str:
    """
    Construye una nota interna breve, escaneable y humana para Capital Humano.
    """
    current_stage_raw = result.get("current_stage") or work_queue.get("current_stage")
    intent_raw = result.get("intent") or work_queue.get("last_intent")
    risk_level_raw = result.get("risk_level") or work_queue.get("risk_level")

    current_stage = _human_stage(current_stage_raw)
    intent = _human_intent(intent_raw)
    risk_level = _human_risk_level(risk_level_raw)

    title = _note_title_from_work_queue(work_queue, labels)
    queue_label = _short_queue_label(work_queue)

    recommended_action = work_queue.get("recommended_action") or "Continuar seguimiento según etapa."

    nombre_contacto = (
        work_queue.get("nombre_completo")
        or username
        or "No disponible"
    )

    telefono_contacto = (
        work_queue.get("telefono")
        or "No disponible"
    )

    canal = channel_label or work_queue.get("channel") or "Chatwoot"

    ciudad = work_queue.get("ciudad") or "N/D"
    estado_region = work_queue.get("estado_region") or "N/D"
    pais_codigo = work_queue.get("pais_codigo") or "N/D"
    city_group = _human_city_group(work_queue.get("city_group"))

    location_requires_ch_validation = bool(work_queue.get("location_requires_ch_validation"))
    location_needs_travel_validation = bool(work_queue.get("location_needs_travel_validation"))

    labels_text = ", ".join(labels) if labels else "N/D"
    safe_content = (content or "").strip()[:500]

    return (
        f"{title}\n\n"
        f"Acción: {recommended_action}.\n"
        f"Último mensaje: \"{safe_content}\"\n\n"
        "👤 Contacto\n"
        f"Nombre: {nombre_contacto}\n"
        f"Teléfono: {telefono_contacto}\n"
        f"Canal: {canal}\n\n"
        "📋 Estado del proceso\n"
        f"Etapa: {current_stage}\n"
        f"Cola: {queue_label}\n"
        f"Intención: {intent}\n"
        f"Riesgo: {risk_level}\n\n"
        "📍 Ubicación\n"
        f"Ciudad: {ciudad}, {estado_region} ({pais_codigo})\n"
        f"Clasificación: {city_group}\n"
        f"Requiere boleto/traslado: {_human_bool(location_needs_travel_validation)}\n"
        f"Validación CH por ubicación: {_human_required(location_requires_ch_validation)}\n\n"
        f"Labels: {labels_text}"
    )


@app.post("/chatwoot/webhook")
async def chatwoot_webhook(
    request: Request,
    token: str | None = Query(default=None),
    x_chatwoot_webhook_token: str | None = Header(default=None),
):
    """
    Webhook de Chatwoot integrado con el orquestador RH.
    """
    expected_token = os.getenv("CHATWOOT_WEBHOOK_TOKEN", "").strip()
    received_token = x_chatwoot_webhook_token or token

    # Fail-closed: si no hay token configurado, o no coincide, se rechaza.
    if not expected_token or received_token != expected_token:
        return JSONResponse(
            status_code=401,
            content={
                "status": "error",
                "error": "unauthorized",
            },
        )

    try:
        payload = await request.json()
    except Exception:
        payload = {
            "raw_body": (await request.body()).decode("utf-8", errors="ignore")
        }

    if not isinstance(payload, dict):
        return {
            "status": "ignored",
            "reason": "payload_not_dict",
        }

    event = payload.get("event")
    message_type = payload.get("message_type")
    content = (payload.get("content") or "").strip()

    conversation = payload.get("conversation") or {}
    account = payload.get("account") or {}
    inbox = payload.get("inbox") or {}

    conversation_id = conversation.get("id") or payload.get("conversation_id")
    account_id = account.get("id") or payload.get("account_id")
    inbox_id = inbox.get("id") or payload.get("inbox_id")
    message_id = payload.get("id") or payload.get("message_id")

    contact = _extract_chatwoot_contact(payload)
    channel_label = _extract_chatwoot_channel_label(payload)

    print(
        "[CHATWOOT_WEBHOOK]",
        json.dumps(
            {
                "event": event,
                "message_type": message_type,
                "account_id": account_id,
                "conversation_id": conversation_id,
                "inbox_id": inbox_id,
                "message_id": message_id,
                "contact_id": contact.get("contact_id"),
                "contact_name": contact.get("name"),
                "channel_label": channel_label,
                "content_preview": content[:300],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )

    if event != "message_created":
        return {
            "status": "ignored",
            "reason": "not_message_created",
            "event": event,
        }

    if message_type != "incoming":
        return {
            "status": "ignored",
            "reason": "not_incoming",
            "message_type": message_type,
        }

    # ── media_guard (G4): attachments → rama audio (transcripción) o reject genérico ──
    # Va ANTES de empty_content: los mensajes solo-media traen content vacío.
    # vision_doc: clasificación del documento del expediente (si el adjunto es uno);
    # viaja en el item encolado para que el worker registre la recepción y acuse.
    vision_doc: dict | None = None
    _audio_url = _detect_audio_url(payload)
    if _audio_url or _chatwoot_has_media(payload):
        if not account_id or not conversation_id:
            return {"status": "ignored", "reason": "media_without_ids"}

        # ── Rama audio: descargar + transcribir con Gemini nativo ──
        if _audio_url:
            transcribed_text = ""
            transcribe_error = None
            try:
                chatwoot_token = os.getenv("CHATWOOT_API_TOKEN", "")
                headers = {"api_access_token": chatwoot_token} if chatwoot_token else {}
                async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=5.0), follow_redirects=True) as hc:
                    resp = await hc.get(_audio_url, headers=headers)
                    resp.raise_for_status()
                    audio_bytes = resp.content
                # Gemini audio nativo (gemini-full-provider-migration B5): transcribe
                # con el glosario trailero en el prompt — cierra el bug de Whisper
                # "fulero"→"futbol" (conv 163). mime_type desde la extensión.
                _audio_url2, _detected_mime = _detect_audio_attachment(payload)
                _aname = (_audio_url2 or _audio_url).split("?")[0].split("/")[-1].lower()
                _ext = "." + _aname.rsplit(".", 1)[-1] if "." in _aname else ""
                _amime = _detected_mime or _AUDIO_EXT_TO_MIME.get(_ext) or "audio/ogg"
                from app.gemini_client import dispatch_audio
                transcribed_text = await asyncio.to_thread(
                    dispatch_audio, audio_bytes, mime_type=_amime
                )
            except Exception as exc:
                transcribe_error = str(exc)
                print(f"[CHATWOOT_AUDIO_TRANSCRIBE] Error: {exc}", flush=True)

            print(
                "[CHATWOOT_AUDIO_TRANSCRIBE]",
                json.dumps(
                    {
                        "account_id": account_id,
                        "conversation_id": conversation_id,
                        "message_id": message_id,
                        "audio_url": _audio_url[:80],
                        "transcribed_len": len(transcribed_text),
                        "error": transcribe_error,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )

            if len(transcribed_text) >= 3:
                # Texto válido → sobreescribir content y continuar el pipeline normal
                content = transcribed_text
            else:
                # Sin texto válido → reply específico, no encolar
                sent = False
                try:
                    await _send_chatwoot_message(
                        account_id=account_id,
                        conversation_id=conversation_id,
                        content=_AUDIO_GUARD_REPLY,
                    )
                    sent = True
                except Exception:
                    traceback.print_exc()
                return {
                    "status": "audio_guard",
                    "sent_to_chatwoot": sent,
                    "transcribed": False,
                    "enqueued": False,
                }
        else:
            # ── Rama no-audio: imagen/sticker → visión; otro → fallback acotado ──
            att_kind = _classify_attachment(payload)
            _visual_url, _visual_kind = _detect_visual_attachment(payload)

            if att_kind in {"image", "sticker"}:
                # ── Sub-rama visión: descargar + procesar con Groq Vision ──
                vision_text = ""
                vision_error = None
                try:
                    chatwoot_token = os.getenv("CHATWOOT_API_TOKEN", "")
                    headers = {"api_access_token": chatwoot_token} if chatwoot_token else {}
                    async with httpx.AsyncClient(
                        timeout=httpx.Timeout(20.0, connect=5.0), follow_redirects=True
                    ) as hc:
                        _vis_url = _visual_url or ""
                        resp = await hc.get(_vis_url, headers=headers)
                        resp.raise_for_status()
                        image_bytes = resp.content
                    # Inferir mime_type desde la URL para base64
                    _url_path = _vis_url.split("?")[0].lower()
                    if _url_path.endswith(".png"):
                        mime_type = "image/png"
                    elif _url_path.endswith(".webp"):
                        mime_type = "image/webp"
                    elif _url_path.endswith(".gif"):
                        mime_type = "image/gif"
                    else:
                        mime_type = "image/jpeg"
                    # Visión Gemini-único (gemini-full-provider-migration): ante
                    # fallo el dispatch devuelve '' → media guard acotado.
                    from app.gemini_client import dispatch_vision
                    from app.indexer import _VISION_PROMPT_IMAGE, _VISION_PROMPT_STICKER
                    _vision_prompt = _VISION_PROMPT_STICKER if att_kind == "sticker" else _VISION_PROMPT_IMAGE
                    vision_text = await asyncio.to_thread(
                        dispatch_vision,
                        image_bytes,
                        _vision_prompt,
                        mime_type=mime_type,
                    )
                except Exception as exc:
                    vision_error = str(exc)
                    print(f"[CHATWOOT_VISION] Error descarga/visión: {exc}", flush=True)

                print(
                    "[CHATWOOT_VISION]",
                    json.dumps(
                        {
                            "account_id": account_id,
                            "conversation_id": conversation_id,
                            "message_id": message_id,
                            "channel_label": channel_label,
                            "att_kind": att_kind,
                            "vision_text_len": len(vision_text),
                            "error": vision_error,
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )

                # Expediente (document-expediente-vision-v2 B1): separar la clasificación
                # tipo_documento/legible del texto de perfilamiento. El registro y el
                # acuse los hace el worker (vision_doc viaja en el item encolado).
                from .lead_memory.expediente import parse_vision_classification
                _clean_text, _doc_tipo, _doc_legible = parse_vision_classification(vision_text)
                if _doc_tipo:
                    vision_doc = {"tipo": _doc_tipo, "legible": _doc_legible}

                if len(_clean_text) >= 3:
                    # Texto válido → sobreescribir content y continuar el pipeline normal
                    content = _clean_text
                elif _doc_tipo:
                    # Documento del expediente sin texto de perfilamiento (p. ej. CURP,
                    # o ilegible): encolar con marcador neutro; el worker registra la
                    # recepción y responde el acuse (no el media guard enlatado).
                    content = "[documento recibido]"
                else:
                    # Visión no devolvió nada útil → fallback acotado y cortar
                    sent = False
                    try:
                        await _send_chatwoot_message(
                            account_id=account_id,
                            conversation_id=conversation_id,
                            content=_MEDIA_GUARD_REPLY,
                        )
                        sent = True
                    except Exception:
                        traceback.print_exc()
                    return {
                        "status": "media_guard",
                        "sent_to_chatwoot": sent,
                        "extracted": False,
                        "enqueued": False,
                    }
            else:
                # ── Sub-rama no soportada: doc, video, etc. → fallback acotado ──
                _top_att = payload.get("attachments")
                _msg_att = (payload.get("message") or {}).get("attachments")
                attachments_count = (
                    (len(_top_att) if isinstance(_top_att, list) else 0)
                    + (len(_msg_att) if isinstance(_msg_att, list) else 0)
                )
                sent = False
                try:
                    await _send_chatwoot_message(
                        account_id=account_id,
                        conversation_id=conversation_id,
                        content=_MEDIA_GUARD_REPLY,
                    )
                    sent = True
                except Exception:
                    traceback.print_exc()
                print(
                    "[CHATWOOT_MEDIA_GUARD]",
                    json.dumps(
                        {
                            "account_id": account_id,
                            "conversation_id": conversation_id,
                            "message_id": message_id,
                            "channel_label": channel_label,
                            "attachments": attachments_count,
                            "had_caption": bool(content),
                            "sent": sent,
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                return {
                    "status": "media_guard",
                    "sent_to_chatwoot": sent,
                    "extracted": False,
                    "enqueued": False,
                }

    if not content:
        return {
            "status": "ignored",
            "reason": "empty_content",
        }

    if not account_id or not conversation_id:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "error": "missing_account_or_conversation_id",
            },
        )

    channel_user_id = str(
        contact.get("phone")
        or contact.get("contact_id")
        or conversation_id
    )

    username = contact.get("name") or f"Chatwoot Contact {channel_user_id}"

    # ── Rate limit: max N messages per channel_user_id per 60 s ─────────────
    if os.getenv("WEBHOOK_RATE_LIMIT_ENABLED", "true").strip().lower() not in {"0", "false", "no", "n", "off"}:
        try:
            _rl = _rate_limit_redis()
            if _rl is not None:
                _rl_key = f"rate:webhook:{channel_user_id}"
                _rl_count = _rl.incr(_rl_key)
                if _rl_count == 1:
                    _rl.expire(_rl_key, 60)
                _rl_max = int(os.getenv("WEBHOOK_RATE_LIMIT_MAX_PER_MINUTE", "30"))
                if _rl_count > _rl_max:
                    print(
                        f"[RATE_LIMITED] channel_user_id={channel_user_id} count={_rl_count}",
                        flush=True,
                    )
                    return JSONResponse(
                        status_code=429,
                        content={"status": "rate_limited", "retry_after": 60},
                    )
        except Exception:
            pass  # never block the webhook on rate limit errors

    # INBOUND_DEBOUNCE_ENABLED controla si el procesamiento es async (worker Celery)
    # o síncrono en el mismo request. El default es "true" (async): el webhook
    # responde en <100ms y el worker aplica deduplicación y current_turn guard.
    # Solo deshabilitar explícitamente con INBOUND_DEBOUNCE_ENABLED=false para diagnóstico.
    if os.getenv("INBOUND_DEBOUNCE_ENABLED", "true").strip().lower() not in {"0", "false", "no", "n", "off"}:
        try:
            from .tasks_chatwoot import enqueue_chatwoot_message

            queued = enqueue_chatwoot_message(
                {
                    "account_id": account_id,
                    "conversation_id": conversation_id,
                    "inbox_id": inbox_id,
                    "message_id": message_id,
                    "channel_user_id": channel_user_id,
                    "username": username,
                    "phone": contact.get("phone"),
                    "channel_label": channel_label,
                    "content": content,
                    "vision_doc": vision_doc,
                }
            )

            print(
                "[CHATWOOT_DEBOUNCE_QUEUED]",
                json.dumps(
                    {
                        "account_id": account_id,
                        "conversation_id": conversation_id,
                        "message_id": message_id,
                        "channel_user_id": channel_user_id,
                        "debounce_seconds": queued.get("debounce_seconds"),
                        # Privacidad (expediente B2): los datos extraídos de un documento
                        # NO van al log en claro; solo el tipo clasificado.
                        "content_preview": (
                            f"[documento: {vision_doc['tipo']}]" if vision_doc else content[:300]
                        ),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )

            return {
                "status": "accepted",
                "queued": True,
                "debounce_seconds": queued.get("debounce_seconds"),
                "conversation_id": conversation_id,
                "account_id": account_id,
                "message_id": message_id,
            }

        except Exception as exc:
            traceback.print_exc()
            return JSONResponse(
                status_code=500,
                content={
                    "status": "error",
                    "error": _public_error(exc),
                    "where": "chatwoot_debounce_enqueue",
                },
            )


    # [RIESGO] Todo lo que sigue (orquestador + 2 llamadas HTTP a Chatwoot) se
    # ejecuta de forma síncrona dentro del handler async ANTES de devolver 200.
    # Si el total tarda más de ~25-30s, Chatwoot reintenta el webhook y el
    # candidato recibe el mensaje duplicado.
    # Desglose del tiempo típico por operación:
    #   run_hr_graph_message  → Neo4j + Postgres + LLM: 3-8s
    #   _send_chatwoot_message → HTTP Chatwoot: 0.5-2s
    #   sync_chatwoot_candidate_note → Postgres + 2x HTTP Chatwoot: 1-4s
    # Total: 4-14s en condiciones normales. Puede escalar con latencia de red.
    # [MEJORA] Activar INBOUND_DEBOUNCE_ENABLED=true para que todo esto ocurra
    # en el worker Celery y el webhook responda en <200ms.
    try:
        result = run_hr_graph_message(
            channel="chatwoot",
            channel_user_id=channel_user_id,
            username=username,
            phone=contact.get("phone"),
            message=content,
            external_message_id=str(message_id or ""),
        )

        reply = (result.get("reply") or result.get("text") or "").strip()

        if not reply:
            return {
                "status": "ok",
                "processed": True,
                "sent_to_chatwoot": False,
                "reason": "empty_reply",
                "orchestrator_result": result,
            }

        chatwoot_response = await _send_chatwoot_message(
            account_id=account_id,
            conversation_id=conversation_id,
            content=reply,
        )

        conversation_key = make_conversation_key("chatwoot", channel_user_id)
        work_queue = _get_rh_work_queue_metadata(conversation_key)

        labels = _normalize_chatwoot_labels(
            work_queue.get("suggested_chatwoot_labels")
        )

        if not labels:
            labels = _fallback_chatwoot_labels(result)

        labels_applied = False
        note_created = False
        labels_error = None
        note_error = None
        note_sync = None

        try:
            note_sync = await sync_chatwoot_candidate_note(
                lead_key=conversation_key,
                account_id=account_id,
                conversation_id=conversation_id,
                fallback_last_message=content,
                channel_label=channel_label,
            )
            labels = note_sync.get("labels") or []
            labels_applied = bool(note_sync.get("ok"))
            note_created = bool(note_sync.get("ok"))

            print(
                "[CHATWOOT_NOTE_SYNC_OK]",
                json.dumps(
                    {
                        "lead_key": conversation_key,
                        "conversation_id": conversation_id,
                        "account_id": account_id,
                        "labels": labels,
                        "note_message_id": note_sync.get("note_message_id"),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )

        except Exception as sync_exc:
            note_error = str(sync_exc)
            labels_error = str(sync_exc)

            print(
                "[CHATWOOT_NOTE_SYNC_ERROR]",
                json.dumps(
                    {
                        "lead_key": conversation_key,
                        "conversation_id": conversation_id,
                        "account_id": account_id,
                        "error": str(sync_exc)[:500],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )

            # Fallback al comportamiento anterior para no romper operación si falla la memoria v2.
            try:
                await _set_chatwoot_labels(
                    account_id=account_id,
                    conversation_id=conversation_id,
                    labels=labels,
                )
                labels_applied = True
            except Exception as label_exc:
                labels_error = str(label_exc)
                print(
                    "[CHATWOOT_LABELS_ERROR]",
                    json.dumps(
                        {
                            "conversation_id": conversation_id,
                            "account_id": account_id,
                            "labels": labels,
                            "error": labels_error[:500],
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )

            try:
                note = _build_chatwoot_internal_note(
                    result=result,
                    work_queue=work_queue,
                    labels=labels,
                    username=username,
                    content=content,
                    channel_label=channel_label,
                )

                await _send_chatwoot_private_note(
                    account_id=account_id,
                    conversation_id=conversation_id,
                    content=note,
                )
                note_created = True
            except Exception as fallback_note_exc:
                note_error = str(fallback_note_exc)
                print(
                    "[CHATWOOT_NOTE_ERROR]",
                    json.dumps(
                        {
                            "conversation_id": conversation_id,
                            "account_id": account_id,
                            "error": note_error[:500],
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )

        return {
            "status": "ok",
            "processed": True,
            "sent_to_chatwoot": True,
            "conversation_id": conversation_id,
            "account_id": account_id,
            "current_stage": result.get("current_stage"),
            "intent": result.get("intent"),
            "requires_human": result.get("requires_human"),
            "risk_level": result.get("risk_level"),
            "chatwoot_message_id": chatwoot_response.get("id"),
            "labels": labels,
            "labels_applied": labels_applied,
            "labels_error": labels_error,
            "note_created": note_created,
            "note_error": note_error,
            "note_sync": note_sync,
            "work_priority": work_queue.get("work_priority"),
            "work_bucket": work_queue.get("work_bucket"),
            "recommended_action": work_queue.get("recommended_action"),
            "ciudad": work_queue.get("ciudad"),
            "estado_region": work_queue.get("estado_region"),
            "pais_codigo": work_queue.get("pais_codigo"),
            "city_group": work_queue.get("city_group"),
            "nombre_completo": work_queue.get("nombre_completo"),
            "telefono": work_queue.get("telefono"),
            "channel_label": channel_label,
            "is_profile_ready": work_queue.get("is_profile_ready"),
            "is_restrictive_review": work_queue.get("is_restrictive_review"),
            "is_foraneo_mx": work_queue.get("is_foraneo_mx"),
            "needs_location_ch_validation": work_queue.get("needs_location_ch_validation"),
        }

    except httpx.HTTPStatusError as exc:
        traceback.print_exc()
        return JSONResponse(
            status_code=502,
            content={
                "status": "error",
                "error": "chatwoot_api_error",
                "details": str(exc),
                "response_text": exc.response.text[:1000],
            },
        )

    except Exception as exc:
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "error": _public_error(exc),
            },
        )
