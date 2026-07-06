"""Guardia anti-spam / flood por lead (Bloque 4b, empathetic-funnel).

El debounce (~6s) ya coalesce ráfagas cortas en un solo turno. Esto cubre el gap
restante: **flood sostenido** — muchos mensajes en turnos separados, cada uno una
llamada LLM (costo + riesgo de 429). Ventana deslizante en Redis por lead: si supera
``FLOOD_LIMIT`` turnos en ``FLOOD_WINDOW`` s → cooldown de ``FLOOD_COOLDOWN`` s durante
el cual el worker suprime la respuesta SIN gastar LLM. Agnóstico de contenido.

Degradación segura: cualquier error de Redis → no bloquea (devuelve False).
"""
from __future__ import annotations

import logging
import os

import redis

log = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    try:
        v = os.getenv(name)
        return int(v) if v not in (None, "") else default
    except (TypeError, ValueError):
        return default


FLOOD_LIMIT = _env_int("ANTISPAM_FLOOD_LIMIT", 12)        # turnos permitidos en la ventana
FLOOD_WINDOW = _env_int("ANTISPAM_FLOOD_WINDOW", 60)      # ventana en segundos
FLOOD_COOLDOWN = _env_int("ANTISPAM_FLOOD_COOLDOWN", 300)  # cooldown en segundos (5 min)


def _redis_url() -> str:
    return (
        os.getenv("CELERY_BROKER_URL")
        or os.getenv("REDIS_URL")
        or "redis://chatwoot_redis:6379/1"
    )


def _r() -> redis.Redis:
    return redis.Redis.from_url(_redis_url(), decode_responses=True)


def is_flood_cooldown(lead_key: str) -> bool:
    """True si el lead está en cooldown por flood (suprimir sin gastar LLM)."""
    if not lead_key:
        return False
    try:
        return bool(_r().get(f"hr:antispam:cd:{lead_key}"))
    except Exception as exc:
        log.warning("[ANTISPAM] lectura cooldown falló: %s", exc)
        return False


def register_and_check(lead_key: str) -> bool:
    """Registra este turno en la ventana deslizante. Si excede ``FLOOD_LIMIT`` fija el
    cooldown y devuelve True (flood detectado). No cuenta si ya está en cooldown."""
    if not lead_key:
        return False
    try:
        r = _r()
        cnt_key = f"hr:antispam:cnt:{lead_key}"
        n = r.incr(cnt_key)
        if n == 1:
            r.expire(cnt_key, FLOOD_WINDOW)
        if n > FLOOD_LIMIT:
            r.set(f"hr:antispam:cd:{lead_key}", "1", ex=FLOOD_COOLDOWN)
            log.warning(
                "[ANTISPAM_FLOOD] lead=%s turnos=%s en %ss → cooldown %ss",
                lead_key, n, FLOOD_WINDOW, FLOOD_COOLDOWN,
            )
            return True
    except Exception as exc:
        log.warning("[ANTISPAM] register_and_check falló: %s", exc)
    return False
