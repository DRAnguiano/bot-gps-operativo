"""Worker Celery del path entrante (queue ``inbound``).

Entre el webhook (`app/app.py`) y el orquestador. Responsabilidades:

- **Debounce** (~6s) y combinado de mensajes consecutivos del mismo lead, para
  no orquestar ráfagas mensaje a mensaje.
- Aplicar el `current_turn` guard y, si procede, persistir facts inferidos por
  contexto (p. ej. "sí" ⇒ apto vigente) para que el funnel no vuelva a
  preguntar lo ya respondido.
- Llamar al orquestador, persistir en Postgres (fuente de verdad) y disparar el
  sync a Chatwoot (reply + nota + labels).

NO define reglas de negocio nuevas: edad, labels y copy canónico viven en sus
módulos de dominio; aquí solo se invocan/propagan.
"""
import asyncio
import json
import os
import re
import time
import traceback
import uuid
from typing import Any

import redis

# Registra las tareas de seguimiento para que el worker inbound las ejecute
import app.tasks_seguimiento  # noqa: F401

from app.celery_app import celery_app
from app.knowledge.geo_utils import normalize_zm_laguna_city, is_zm_laguna_canonical


def _env_int(name: str, default: int) -> int:
    try:
        value = os.getenv(name)
        if value is None or str(value).strip() == "":
            return default
        return int(value)
    except Exception:
        return default


def _redis_url() -> str:
    return (
        os.getenv("CELERY_BROKER_URL")
        or os.getenv("REDIS_URL")
        or "redis://chatwoot_redis:6379/1"
    )


def _redis_client() -> redis.Redis:
    return redis.Redis.from_url(_redis_url(), decode_responses=True)


def _safe_text(value: Any, max_len: int = 4000) -> str:
    text = str(value or "").strip()
    return text[:max_len]


def _dedupe_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    clean = []

    for item in messages:
        message_id = str(item.get("message_id") or item.get("external_message_id") or "").strip()
        dedupe_key = message_id or f"{item.get('received_at')}:{item.get('content')}"

        if dedupe_key in seen:
            continue

        seen.add(dedupe_key)
        clean.append(item)

    return clean


def _combine_contents(messages: list[dict[str, Any]]) -> str:
    parts = []

    for item in messages:
        content = _safe_text(item.get("content"), 2000)
        if content:
            parts.append(content)

    return "\n".join(parts).strip()






def _conversation_turns_count(result: dict[str, Any]) -> int | None:
    for event in result.get("events") or []:
        if isinstance(event, dict) and event.get("type") == "conversation_memory_built":
            try:
                return int(event.get("turns_count") or 0)
            except Exception:
                return None
    return None


def _maybe_prepend_first_reply_intro(
    reply: str, result: dict[str, Any], is_first_reply: bool | None = None
) -> str:
    """
    Adds Mundo's public intro only on the first assistant reply of a conversation.

    This is intentionally done at the Chatwoot/Telegram delivery layer so curl
    tests and internal graph behavior stay clean.

    ``is_first_reply`` is the authoritative signal (computed by the caller as
    "no previous assistant message in lead memory"). The legacy
    ``conversation_memory_built`` event path is kept only as fallback: nothing
    emits that event today, so without the explicit flag the intro never fired
    (bug observado en smoke 2026-06-12 12:12).
    """
    clean = (reply or "").strip()
    if not clean:
        return clean

    enabled = os.getenv("FIRST_REPLY_INTRO_ENABLED", "true").strip().lower()
    if enabled not in {"1", "true", "yes", "y", "on"}:
        return clean

    intro = os.getenv(
        "ASSISTANT_PUBLIC_INTRO",
        "Hola, soy Mundo, del equipo de reclutamiento de Transmontes.",
    ).strip()

    if not intro:
        return clean

    normalized = clean.lower()
    if "soy mundo" in normalized[:180]:
        return clean

    if is_first_reply is None:
        turns_count = _conversation_turns_count(result)
        # Legacy: only first real assistant response; if the event is missing,
        # avoid adding the intro to prevent accidental repeated greetings.
        is_first_reply = turns_count == 0

    if not is_first_reply:
        return clean

    return f"{intro}\n\n{clean}"


def enqueue_chatwoot_message(item: dict[str, Any]) -> dict[str, Any]:
    """
    Guarda un mensaje entrante en Redis y agenda procesamiento diferido.

    La última tarea programada gana. Las tareas anteriores despiertan,
    revisan el token y se descartan si ya llegó un mensaje más nuevo.
    """
    r = _redis_client()

    account_id = str(item.get("account_id") or "unknown")
    conversation_id = str(item.get("conversation_id") or "unknown")

    debounce_seconds = _env_int("INBOUND_DEBOUNCE_SECONDS", 6)
    ttl_seconds = max(_env_int("INBOUND_DEBOUNCE_TTL_SECONDS", 900), debounce_seconds + 60)

    token = uuid.uuid4().hex

    pending_key = f"hr:inbound:chatwoot:{account_id}:{conversation_id}:pending"
    latest_key = f"hr:inbound:chatwoot:{account_id}:{conversation_id}:latest_token"

    payload = {
        **item,
        "token": token,
        "received_at": time.time(),
    }

    r.rpush(pending_key, json.dumps(payload, ensure_ascii=False))
    r.expire(pending_key, ttl_seconds)
    r.set(latest_key, token, ex=ttl_seconds)

    process_chatwoot_debounced_message.apply_async(
        args=[pending_key, latest_key, token],
        countdown=debounce_seconds,
        queue="inbound",
    )

    return {
        "queued": True,
        "token": token,
        "pending_key": pending_key,
        "latest_key": latest_key,
        "debounce_seconds": debounce_seconds,
    }


def _run_unified_extractor_shadow(
    *,
    message: str,
    last_bot: str | None,
    pre_memory: dict[str, Any],
    current_path_facts: dict[str, Any],
    conversation_id: Any,
) -> None:
    """Corre el extractor unificado en paralelo al path actual (log-only).

    Loggea: el TurnExtraction validado, divergencias de extracción fact-por-fact
    (5.3) y divergencias de escritura vs el valor guardado (5.4). NO persiste,
    NO afecta el reply. Aislado: cualquier error se traga arriba.
    """
    from app.knowledge.turn_extractor import extract_turn, validate_extraction

    known = {
        f"{r['fact_group']}.{r['fact_key']}": r["fact_value"]
        for r in (pre_memory.get("facts") or [])
        if r.get("fact_group") and r.get("fact_key") and r.get("fact_value")
    }
    extraction = extract_turn(message, last_bot, known)
    validated = validate_extraction(extraction, known)
    unified_facts = {f"{f['fact_group']}.{f['fact_key']}": f["fact_value"] for f in validated}

    # 5.3: divergencias de extracción (path actual vs unificado), ignorando claves de control
    _ignore = {"location.is_local_laguna", "interest.payment", "interest.routes"}
    cur = {k: v for k, v in (current_path_facts or {}).items() if k not in _ignore}
    extraction_diffs = []
    for k in set(cur) | set(unified_facts):
        a, b = cur.get(k), unified_facts.get(k)
        if str(a or "") != str(b or ""):
            extraction_diffs.append({"key": k, "current": a, "unified": b})

    # 5.4: divergencias de escritura — qué valor ganaría con política gobernada
    write_diffs = []
    for f in validated:
        key = f"{f['fact_group']}.{f['fact_key']}"
        saved = known.get(key)
        if saved is not None and str(saved) != str(f["fact_value"]):
            write_diffs.append({
                "key": key, "saved": saved, "candidate": f["fact_value"],
                "conf": f["confidence"], "correction": f["is_explicit_correction"],
            })

    print("[UNIFIED_SHADOW]", json.dumps({
        "conversation_id": conversation_id,
        "message": message[:200],
        "unified_facts": unified_facts,
        "embedded_question": extraction.embedded_question,
        "extraction_diffs": extraction_diffs,
        "write_diffs": write_diffs,
    }, ensure_ascii=False), flush=True)


@celery_app.task(name="chatwoot.process_debounced_message")
def process_chatwoot_debounced_message(
    pending_key: str,
    latest_key: str,
    token: str,
) -> dict[str, Any]:
    """
    Procesa el lote de mensajes pendientes del mismo contacto/conversación.

    Si el token no es el último, significa que llegó otro mensaje después y
    esta tarea se descarta. La última tarea consolidará todo el lote.
    """
    r = _redis_client()

    latest_token = r.get(latest_key)
    if latest_token != token:
        return {
            "status": "stale",
            "reason": "newer_message_pending",
            "token": token,
            "latest_token": latest_token,
        }

    raw_messages = r.lrange(pending_key, 0, -1)

    # Evita que tareas posteriores reprocesen el mismo lote.
    r.delete(pending_key)
    r.delete(latest_key)

    messages: list[dict[str, Any]] = []
    for raw in raw_messages:
        try:
            messages.append(json.loads(raw))
        except Exception:
            continue

    messages = _dedupe_messages(messages)
    messages.sort(key=lambda item: float(item.get("received_at") or 0))

    print(
        "[CHATWOOT_DEBOUNCE_BATCH_ITEMS]",
        json.dumps(
            [
                {
                    "message_id": item.get("message_id"),
                    "received_at": item.get("received_at"),
                    "content": str(item.get("content") or "")[:300],
                }
                for item in messages
            ],
            ensure_ascii=False,
        ),
        flush=True,
    )

    if not messages:
        return {
            "status": "ignored",
            "reason": "empty_batch",
        }

    first = messages[0]
    last = messages[-1]

    combined_content = _combine_contents(messages)
    if not combined_content:
        return {
            "status": "ignored",
            "reason": "empty_combined_content",
            "batch_size": len(messages),
        }

    account_id = first.get("account_id")
    conversation_id = first.get("conversation_id")
    channel_user_id = first.get("channel_user_id")
    username = first.get("username")
    phone = first.get("phone")
    channel_label = first.get("channel_label") or "Chatwoot"

    message_ids = [
        str(item.get("message_id") or "")
        for item in messages
        if item.get("message_id") is not None
    ]

    external_message_id = (
        f"debounced:{message_ids[0]}:{message_ids[-1]}"
        if message_ids
        else f"debounced:{int(time.time())}:{token[:8]}"
    )

    print(
        "[CHATWOOT_DEBOUNCE_PROCESS]",
        json.dumps(
            {
                "account_id": account_id,
                "conversation_id": conversation_id,
                "channel_user_id": channel_user_id,
                "batch_size": len(messages),
                "external_message_id": external_message_id,
                # Privacidad (expediente B2): si el lote trae un documento, los datos
                # extraídos por visión NO se loggean en claro; solo el tipo.
                "combined_content": (
                    "[documento: " + ", ".join(
                        str((it.get("vision_doc") or {}).get("tipo")) for it in messages
                        if it.get("vision_doc")
                    ) + "]"
                    if any(it.get("vision_doc") for it in messages)
                    else combined_content[:500]
                ),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )

    try:
        # Import diferido para evitar ciclos al cargar FastAPI/Celery.
        from app.app import (
            _build_chatwoot_internal_note,
            _fallback_chatwoot_labels,
            _get_rh_work_queue_metadata,
            _normalize_chatwoot_labels,
            _send_chatwoot_message,
            _send_chatwoot_private_note,
            _set_chatwoot_labels,
        )
        from app.db import make_conversation_key
        from app.graphs.hr_graph import run_hr_graph_message
        from app.knowledge.current_turn import (
            build_current_turn_ack,
            has_business_question,
            is_campaign_or_interest_entry,
        )
        from app.chatwoot_note_sync import sync_chatwoot_candidate_note
        from app.lead_memory.repository import get_lead_memory

        # Pre-load context before orchestrator so we can read the last bot message
        conversation_key_for_facts = make_conversation_key("chatwoot", str(channel_user_id))
        pre_memory = get_lead_memory(conversation_key=conversation_key_for_facts)
        last_bot_message = None
        for _m in reversed(pre_memory.get("messages") or []):
            if isinstance(_m, dict) and _m.get("role") == "assistant":
                # Cola, no cabeza: la pregunta vigente vive al FINAL del mensaje.
                # El [:500] original dejó ciego al detector de confirmación cuando
                # el resumen iba al final de una respuesta de 1027 chars (conv 176).
                last_bot_message = str(_m.get("message") or "")[-2000:]
                break

        # ── Bloque 4: guardia de insistencia — si el lead está en pausa (tras 5 ruegos
        # sin dato válido), NO se procesa ni responde (suppress), SIN gastar LLM. El
        # avance del perfil ya está preservado en facts; pasada la hora, el siguiente
        # mensaje reanuda normal desde donde quedó. ──────────────────────────────────
        from app.knowledge.insistence_guard import is_paused as _ig_is_paused
        _pause_lead_key = (pre_memory.get("lead") or {}).get("lead_key") or conversation_key_for_facts
        if _ig_is_paused(_pause_lead_key):
            import logging as _lg
            _lg.getLogger(__name__).info(
                "[INSISTENCE_PAUSED_SUPPRESS] lead=%s conv=%s — sin respuesta (pausa activa)",
                _pause_lead_key, conversation_id,
            )
            return {
                "status": "ok",
                "processed": False,
                "sent_to_chatwoot": False,
                "batch_size": len(messages),
                "combined_content": combined_content,
                "reason": "insistence_paused",
            }

        # ── Bloque 4b: anti-spam / flood sostenido. El debounce ya coalesce ráfagas
        # <6s; aquí se corta el flood sostenido (muchos turnos separados) con un
        # cooldown por lead, SIN gastar LLM. Agnóstico de contenido. ────────────────
        from app.knowledge import anti_spam
        if anti_spam.is_flood_cooldown(_pause_lead_key) or anti_spam.register_and_check(_pause_lead_key):
            import logging as _lg2
            _lg2.getLogger(__name__).warning(
                "[ANTISPAM_SUPPRESS] lead=%s conv=%s — flood/cooldown, sin respuesta",
                _pause_lead_key, conversation_id,
            )
            return {
                "status": "ok",
                "processed": False,
                "sent_to_chatwoot": False,
                "batch_size": len(messages),
                "combined_content": combined_content,
                "reason": "antispam_flood",
            }

        # ── Expediente B2 (privacidad): consentimiento expreso del apto médico. ─────
        # El apto es dato sensible de salud (LFPDPPP): si estaba pendiente el "sí
        # acepto" y este mensaje lo afirma, se registra y se invita a reenviar la foto.
        from app.lead_memory import expediente as _exp
        _known_pre = {
            f"{r['fact_group']}.{r['fact_key']}": r["fact_value"]
            for r in (pre_memory.get("facts") or []) if r.get("fact_value")
        }
        if _exp.apto_consent_pending(_known_pre) and _exp.is_consent_affirmative(combined_content):
            _exp.register_express_consent(_pause_lead_key)
            _consent_reply = (
                "Gracias por su autorización ✓. Puede enviarnos la foto de su apto "
                "médico cuando guste y seguimos con su expediente."
            )
            try:
                asyncio.run(_send_chatwoot_message(
                    account_id=account_id, conversation_id=conversation_id,
                    content=_consent_reply,
                ))
            except Exception:
                traceback.print_exc()
            return {
                "status": "ok", "processed": True, "sent_to_chatwoot": True,
                "batch_size": len(messages), "combined_content": combined_content,
                "reason": "apto_consent_registered",
            }

        # ── Expediente (document-expediente-vision-v2 B1): registrar la recepción de
        # documentos clasificados por visión ANTES del orquestador (así la Nota IA del
        # turno ya los ve). La imagen nunca se persiste; solo estado + trazabilidad
        # (source_message_id). El acuse se compone después del reply. ────────────────
        _docs_received_now: list[str] = []
        _docs_ilegible_now: list[str] = []
        _apto_gate_fired = False
        for _it in messages:
            _vd = _it.get("vision_doc") or {}
            _vd_tipo = _vd.get("tipo")
            if not _vd_tipo:
                continue
            # B2 gate: el apto médico NO se registra ni se extrae sin consentimiento
            # EXPRESO. Se pide la autorización y el resultado de visión se descarta
            # (el contenido del turno se neutraliza para no persistir facts del apto).
            if _vd_tipo == "apto_medico" and not _exp.has_express_consent(_known_pre):
                _exp.request_apto_consent(_pause_lead_key)
                _apto_gate_fired = True
                combined_content = "[documento recibido]"
                continue
            _vd_legible = bool(_vd.get("legible", True))
            if _exp.mark_received(_pause_lead_key, _vd_tipo, legible=_vd_legible):
                (_docs_received_now if _vd_legible else _docs_ilegible_now).append(_vd_tipo)
                try:
                    from app.lead_memory.repository import upsert_lead_fact as _exp_up
                    _exp_up(
                        lead_key=_pause_lead_key, fact_group="expediente",
                        fact_key=f"{_vd_tipo}.source_message_id",
                        fact_value=str(_it.get("message_id") or ""),
                        confidence=1.0, source="vision_document",
                    )
                except Exception:
                    pass

        # ── 6.1: extracción única antes de bifurcar guard/orquestador ──────────
        from app.knowledge.turn_extractor import extract_turn, validate_extraction
        from app.knowledge.text_normalizer import normalize_text as _norm
        from app.knowledge.llm_errors import LLMUnavailableError
        _known_facts = {
            f"{r['fact_group']}.{r['fact_key']}": r["fact_value"]
            for r in (pre_memory.get("facts") or [])
            if r.get("fact_group") and r.get("fact_key") and r.get("fact_value")
        }
        try:
            _pre_extraction = extract_turn(combined_content, last_bot_message, _known_facts)
        except LLMUnavailableError as _llm_exc:
            # Gate: LLM no disponible (quota agotada en primaria y backup).
            # Abort silencioso: sin respuesta al candidato, sin persistencia, solo log.
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "[LLM_GATE] turno abortado — LLM no disponible: lead=%s conv=%s err=%s",
                conversation_key_for_facts, conversation_id, _llm_exc,
            )
            return {
                "status": "skipped_llm_unavailable",
                "processed": False,
                "sent_to_chatwoot": False,
                "reason": str(_llm_exc),
            }
        _pre_validated = validate_extraction(_pre_extraction, _known_facts)

        # Construir dict de guard a partir de los facts validados (Capa 2)
        _current_turn_facts: dict = {
            f"{f['fact_group']}.{f['fact_key']}": f["fact_value"]
            for f in _pre_validated
        }
        # Context confirmations: "si" → apto_status/license.status/labor_letters
        # (Capa 2 determinista basada en última pregunta del bot — no LLM)
        from app.knowledge.current_turn import _extract_context_confirmation_facts
        _ctx = _extract_context_confirmation_facts(
            _norm(combined_content), last_bot_message or "",
            _turn_signals=_pre_extraction.signals,
        )
        for _ck, _cv in _ctx.items():
            if _ck not in _current_turn_facts:
                _current_turn_facts[_ck] = _cv
        # Señales de interés (solo guard, no se persisten)
        _txt = _norm(combined_content)
        if any(t in _txt for t in ("cuanto pagan", "pago", "sueldo", "compensacion", "kilometro", "km")):
            _current_turn_facts["interest.payment"] = "asked"
        if any(t in _txt for t in ("que rutas", "rutas tienen", "bases", "cedis")):
            _current_turn_facts["interest.routes"] = "asked"
        _raw_city = _current_turn_facts.get("candidate.city") or ""
        if _raw_city:
            _current_turn_facts["candidate.city"] = normalize_zm_laguna_city(_raw_city)
        _current_turn_facts["location.is_local_laguna"] = (
            "true"
            if is_zm_laguna_canonical(_current_turn_facts.get("candidate.city") or "")
            else "false"
        )

        result = run_hr_graph_message(
            channel="chatwoot",
            channel_user_id=str(channel_user_id),
            username=username,
            phone=phone,
            message=combined_content,
            external_message_id=external_message_id,
            pre_extraction=_pre_extraction,
            pre_validated=_pre_validated,
        )

        # Primer contacto con entrada de campaña/interés (p. ej. el mensaje
        # default de la publicación de Facebook): Mundo SIEMPRE recibe con su
        # saludo oficial; el current-turn guard no aplica en ese turno.
        first_contact_greeting = (
            last_bot_message is None
            and not result.get("requires_human")
            and is_campaign_or_interest_entry(combined_content)
        )
        if first_contact_greeting:
            from app.orchestrators.knowledge_orchestrator import GREETING_REPLY, greeting_reply_for_facts
            _has_funnel_data = any(
                k.startswith(("candidate.", "license.", "medical.", "documents.", "experience."))
                and k not in {"candidate.vacancy_accepted", "location.is_local_laguna"}
                for k in _current_turn_facts
            )
            _greeting_text = (
                greeting_reply_for_facts(_current_turn_facts) if _has_funnel_data else GREETING_REPLY
            )
            result.update(
                {
                    "reply": _greeting_text,
                    "text": _greeting_text,
                    "selected_route": "profile",
                    "route": "profile",
                    "intent": "greeting",
                    "risk_level": "low",
                    "requires_human": False,
                    "first_contact_greeting_applied": True,
                }
            )
            print(
                "[FIRST_CONTACT_GREETING_APPLIED]",
                json.dumps(
                    {"conversation_id": conversation_id, "channel_user_id": channel_user_id},
                    ensure_ascii=False,
                ),
                flush=True,
            )

        # 6.3: guard usa facts pre-computados (sin re-extracción)
        # funnel.summary_confirmed cuenta como señal: el "sí, es correcto" al resumen
        # debe disparar el guard para persistir la confirmación y emitir el cierre.
        _has_profile_signal = any(
            (k.startswith(("candidate.", "license.", "medical.", "documents.", "experience."))
             or k == "funnel.summary_confirmed")
            and k not in {"candidate.vacancy_accepted"}
            for k in _current_turn_facts
        )
        # Detector ÚNICO (Fase 2/D5): mismo que el orquestador. Sustituye la pareja
        # `signals.has_embedded_question` + `is_question` que antes decidían por
        # separado y en desacuerdo (raíz del bug #3). Si hay pregunta de negocio, el
        # guard NO dispara y deja que el orquestador la responda.
        _guard_should_fire = (
            not first_contact_greeting
            and not result.get("requires_human")
            and not has_business_question(combined_content, _pre_extraction.signals)
            and _has_profile_signal
            and _current_turn_facts
        )
        # fix-compound-summary-confirmation D1: la confirmación del resumen sobrevive
        # a turnos compuestos. Cuando el guard NO dispara porque el mensaje trae
        # pregunta de negocio ("Sí, todo bien... ¿hacen doping?"), el fact
        # funnel.summary_confirmed ya computado por extract_current_turn_facts se
        # persiste SOLO (sin tocar el reply — el orquestador responde la pregunta
        # igual que hoy). Sin esto, el siguiente turno re-emite el resumen ya
        # confirmado (bug en vivo conv 175, 2026-07-10).
        if (
            not _guard_should_fire
            and _current_turn_facts.get("funnel.summary_confirmed") == "true"
            and not result.get("requires_human")
        ):
            try:
                _lm_confirm = get_lead_memory(conversation_key=conversation_key_for_facts)
                _lk_confirm = (
                    (_lm_confirm.get("lead") or {}).get("lead_key")
                    or conversation_key_for_facts
                )
                from app.lead_memory.repository import upsert_lead_fact as _ulf_confirm
                _ulf_confirm(
                    lead_key=_lk_confirm,
                    fact_group="funnel",
                    fact_key="summary_confirmed",
                    fact_value="true",
                    confidence=0.95,
                    source="summary_confirm_compound",
                    source_text=combined_content[:200],
                )
                print(
                    "[SUMMARY_CONFIRM_COMPOUND]",
                    json.dumps({"lead_key": _lk_confirm, "conversation_id": conversation_id}, ensure_ascii=False),
                    flush=True,
                )
            except Exception as _exc_confirm:
                print(f"[SUMMARY_CONFIRM_COMPOUND] error: {_exc_confirm}", flush=True)
        if _guard_should_fire:
            lead_memory = get_lead_memory(conversation_key=conversation_key_for_facts)
            saved_facts = {
                f"{row['fact_group']}.{row['fact_key']}": row['fact_value']
                for row in (lead_memory.get("facts") or [])
            }
            lead_key_for_ctx = (
                (lead_memory.get("lead") or {}).get("lead_key")
                or conversation_key_for_facts
            )
            merged_facts = {**saved_facts, **_current_turn_facts}
            # Solo el PREFIJO del ack se restringe a facts nuevos del turno: si el
            # extractor parrotea los "DATOS YA CONOCIDOS" (echo típico del 8b), esos
            # facts ya guardados con el mismo valor no deben re-confirmarse. La
            # siguiente pregunta del funnel sigue derivando de merged_facts (estado
            # completo), no de _fresh_facts.
            _fresh_facts = {
                k: v for k, v in _current_turn_facts.items()
                if saved_facts.get(k) != v
            }
            # Nombre recién conocido este turno: se evalúa contra el snapshot PRE-turno
            # (`_known_facts`), no contra `saved_facts` recargado, porque el orquestador
            # ya persistió el nombre antes de llegar aquí (lo cual vaciaría _fresh_facts).
            _name_just_learned = (
                bool(_current_turn_facts.get("candidate.name"))
                and not _known_facts.get("candidate.name")
            )
            guarded_reply = build_current_turn_ack(
                combined_content, merged_facts, last_bot_message,
                pre_current_facts=_fresh_facts,
                name_just_learned=_name_just_learned,
            )

            # Persist current-turn facts so funnel doesn't re-ask
            if lead_key_for_ctx:
                from app.lead_memory.repository import upsert_lead_fact, save_lead_message as _slm
                _PERSIST_KEYS = {
                    "candidate.name",
                    "candidate.age",
                    "medical.apto_status",
                    "medical.apto_expiration_text",
                    "license.status",
                    "license.expiration_text",
                    "license.category",
                    "experience.vehicle_type",
                    "experience.years",
                    "documents.proof",
                    "documents.labor_letters",
                    "documents.renewal_proof",
                    "candidate.city",
                    # Resumen de confirmación (gemini-natural-recruiter D6)
                    "funnel.summary_confirmed",
                }
                context_new = {
                    k: v for k, v in _current_turn_facts.items()
                    if k not in saved_facts and k in _PERSIST_KEYS
                }
                for _k, _v in context_new.items():
                    _parts = _k.split(".", 1)
                    if len(_parts) == 2:
                        try:
                            upsert_lead_fact(
                                lead_key=lead_key_for_ctx,
                                fact_group=_parts[0],
                                fact_key=_parts[1],
                                fact_value=str(_v),
                                confidence=0.75,
                                source="guard_context",
                                source_text=combined_content[:300],
                            )
                        except Exception:
                            pass
                # Save guard reply so next turn has correct last_bot_message context.
                # Passive capture (Fase B): enrich the assistant row with the canonical
                # field the guard just asked, so route-1 shadow can read it next turn.
                # Only when the guard asked a clean single field (mixed/advisory → []).
                from app.knowledge.guard_asked_field import asked_field_keys_for_guard

                guard_keys = asked_field_keys_for_guard(merged_facts)
                guard_meta = (
                    {
                        "asked_field_keys": guard_keys,
                        "asked_field_source": "current_turn_guard",
                        "asked_field_key_space": "canonical",
                    }
                    if guard_keys
                    else None
                )
                try:
                    _slm(
                        lead_key=lead_key_for_ctx,
                        conversation_key=conversation_key_for_facts,
                        role="assistant",
                        message=guarded_reply,
                        external_metadata=guard_meta,
                    )
                except Exception:
                    pass

            result.update(
                {
                    "reply": guarded_reply,
                    "text": guarded_reply,
                    "selected_route": "profile",
                    "route": "profile",
                    "intent": "candidate_profile_signal",
                    "risk_level": "low",
                    "requires_human": False,
                    "current_turn_guard_applied": True,
                    "current_turn_facts": _current_turn_facts,
                    "funnel_stage": (
                        "closed"
                        if guarded_reply.startswith("Gracias por su interés. Por el momento")
                        else "profile_hint_collected"
                    ),
                    "next_best_action": (
                        # Copy de cierre por edad replicado en 3 módulos (deuda D-4,
                        # docs/deuda_tecnica.md). No editar aquí de forma aislada.
                        "Cierre automático: edad fuera de perfil."
                        if guarded_reply.startswith("Gracias por su interés. Por el momento")
                        else "Validar datos del perfil y solicitar únicamente lo que falte."
                    ),
                    "memory_summary": "El candidato proporcionó datos explícitos de perfil en el último mensaje.",
                }
            )

            print(
                "[CURRENT_TURN_GUARD_APPLIED]",
                json.dumps(
                    {
                        "conversation_id": conversation_id,
                        "channel_user_id": channel_user_id,
                        "facts": _current_turn_facts,
                        "reply": guarded_reply[:300],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )

        # ── Expediente B1: si este turno recibió documento(s), el reply es el ACUSE
        # específico (nombra lo recibido + qué falta / pide re-toma si ilegible),
        # no la respuesta genérica del pipeline. Datos deterministas del registro;
        # redacción LLM con fallback. ────────────────────────────────────────────
        if _docs_received_now or _docs_ilegible_now or _apto_gate_fired:
            try:
                _facts_now = dict(_known_pre)
                for _t in _docs_received_now:
                    _facts_now[f"expediente.{_t}.status"] = "recibido"
                for _t in _docs_ilegible_now:
                    _facts_now[f"expediente.{_t}.status"] = "ilegible"
                if _apto_gate_fired:
                    # B2: apto sin consentimiento expreso → pedir autorización (el
                    # documento NO se registró; visión descartada).
                    _acuse = _exp.CONSENT_APTO_REQUEST
                else:
                    _acuse = _exp.build_acuse(_facts_now, _docs_received_now, _docs_ilegible_now)
                # B2: aviso de confidencialidad la PRIMERA vez que sube un documento.
                if _acuse and not _exp.has_consent_notice(_known_pre):
                    _acuse = f"{_acuse}\n\n{_exp.AVISO_CONFIDENCIALIDAD}"
                    if not _apto_gate_fired:
                        _exp.register_consent_notice(_pause_lead_key)
                if _acuse:
                    result["reply"] = _acuse
                    import logging as _lg3
                    _lg3.getLogger(__name__).info(
                        "[EXPEDIENTE_ACUSE] lead=%s recibidos=%s ilegibles=%s apto_gate=%s",
                        _pause_lead_key, _docs_received_now, _docs_ilegible_now, _apto_gate_fired,
                    )
            except Exception:
                traceback.print_exc()

        reply = (result.get("reply") or result.get("text") or "").strip()
        reply = _maybe_prepend_first_reply_intro(
            reply, result, is_first_reply=(last_bot_message is None)
        )

        # ── TURN_DECISION_SHADOW (fase 1/D1) ────────────────────────────────
        # Read-only: construye TurnDecision equivalente y loggea divergencia
        # entre el reply que vio el candidato y el que se persistió en memoria.
        # No gobierna nada; solo evidencia los P0 (H1/H2) del auditor.
        try:
            from app.knowledge.turn_decision import TurnDecision
            from app.knowledge.funnel_state_planner import compute_funnel_state, CanonicalFact

            _persisted_reply = (result.get("reply") or result.get("text") or "").strip()
            _delivered_reply = reply  # post-intro (lo que recibe el candidato)
            _td_shadow = TurnDecision(
                reply=_delivered_reply,
                delivery_policy=(
                    "suppress" if result.get("requires_human") and not result.get("human_handoff_ack")
                    else "ack_then_handoff" if result.get("requires_human")
                    else "send"
                ),
                requires_human=bool(result.get("requires_human")),
                handoff_reason=result.get("intent") if result.get("requires_human") else None,
                should_continue_profile=not result.get("requires_human", False),
            )
            _divergence = _persisted_reply != _delivered_reply
            print(
                "[TURN_DECISION_SHADOW]",
                json.dumps(
                    {
                        "conversation_id": conversation_id,
                        "delivery_policy": _td_shadow.delivery_policy,
                        "reply_divergence": _divergence,
                        "persisted_len": len(_persisted_reply),
                        "delivered_len": len(_delivered_reply),
                        "persisted_preview": _persisted_reply[:80],
                        "delivered_preview": _delivered_reply[:80],
                        "guard_applied": result.get("current_turn_guard_applied", False),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
        except Exception as _e_shadow:
            print("[TURN_DECISION_SHADOW_ERROR]", str(_e_shadow), flush=True)
        # ── fin shadow ───────────────────────────────────────────────────────

        if not reply:
            return {
                "status": "ok",
                "processed": True,
                "sent_to_chatwoot": False,
                "reason": "empty_reply",
                "batch_size": len(messages),
                "orchestrator_result": result,
            }

        # Handoff humano: el bot deja de responder al candidato, pero la nota
        # privada + labels sí se generan para que el reclutador tome el caso.
        public_reply_suppressed = False
        if result.get("requires_human"):
            print(
                "[HUMAN_HANDOFF_PUBLIC_ACK]",
                json.dumps(
                    {
                        "conversation_id": conversation_id,
                        "channel_user_id": channel_user_id,
                        "reason": result.get("intent") or "requires_human",
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
        chatwoot_response = asyncio.run(
            _send_chatwoot_message(
                account_id=account_id,
                conversation_id=conversation_id,
                content=reply,
            )
        )

        conversation_key = make_conversation_key("chatwoot", str(channel_user_id))

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
            note_sync = asyncio.run(
                sync_chatwoot_candidate_note(
                    lead_key=conversation_key,
                    account_id=account_id,
                    conversation_id=conversation_id,
                    fallback_last_message=combined_content,
                    channel_label=channel_label,
                )
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

            # Fallback al comportamiento anterior si falla la nota/memoria v2.
            try:
                asyncio.run(
                    _set_chatwoot_labels(
                        account_id=account_id,
                        conversation_id=conversation_id,
                        labels=labels,
                    )
                )
                labels_applied = True
            except Exception as label_exc:
                labels_error = str(label_exc)
                print(
                    "[CHATWOOT_DEBOUNCE_LABELS_ERROR]",
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
                    content=combined_content,
                    channel_label=channel_label,
                )

                asyncio.run(
                    _send_chatwoot_private_note(
                        account_id=account_id,
                        conversation_id=conversation_id,
                        content=note,
                    )
                )
                note_created = True
            except Exception as fallback_note_exc:
                note_error = str(fallback_note_exc)
                print(
                    "[CHATWOOT_DEBOUNCE_NOTE_ERROR]",
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
            "sent_to_chatwoot": not public_reply_suppressed,
            "batch_size": len(messages),
            "combined_content": combined_content,
            "chatwoot_message_id": chatwoot_response.get("id"),
            "selected_route": result.get("selected_route"),
            "reason": result.get("reason"),
            "current_stage": result.get("current_stage"),
            "risk_level": result.get("risk_level"),
            "requires_human": result.get("requires_human"),
            "labels": labels,
            "labels_applied": labels_applied,
            "labels_error": labels_error,
            "note_created": note_created,
            "note_error": note_error,
            "note_sync": note_sync,
        }

    except Exception as exc:
        traceback.print_exc()
        return {
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "batch_size": len(messages),
            "combined_content": combined_content[:500],
        }
