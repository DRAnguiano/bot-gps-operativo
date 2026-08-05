"""Guardia de ruego/insistencia + pausa temporal (Bloque 4, empathetic-funnel).

Estado por lead en ``rh_lead_facts_v2`` (grupo ``funnel``):
- ``insistence_count``: nº de insistencias/tonterías consecutivas sin dato válido.
- ``paused_until``: ISO8601 UTC hasta cuando el bot NO responde (delivery suppress).

Reglas de negocio (usuario 2026-07-03):
- Solo cuentan ruegos/tonterías NO relacionadas con el perfilamiento; las dudas
  legítimas (pago, rutas…) NO cuentan (el llamador ya las excluye vía
  ``has_business_question``).
- Aportar un dato válido → reset del contador.
- Tras la 5ª insistencia sin dato válido → mensaje empático final + pausa de 1 h.
  Durante la pausa el worker suprime la respuesta; el avance del perfil se preserva.
- Pasada la hora, el siguiente mensaje reanuda normal desde donde quedó.
"""
from __future__ import annotations

import datetime as _dt
import logging

from app.db import get_conn
from app.lead_memory.repository import upsert_lead_fact

log = logging.getLogger(__name__)

INSISTENCE_LIMIT = 5          # a la 5ª insistencia se pausa
PAUSE_HOURS = 1               # duración de la pausa
_GROUP = "funnel"
_COUNT_KEY = "insistence_count"
_PAUSE_KEY = "paused_until"


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _read_fact(lead_key: str, key: str) -> str | None:
    if not lead_key:
        return None
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT fact_value FROM rh_lead_facts_v2
                    WHERE lead_key = %s AND fact_group = %s AND fact_key = %s
                      AND is_active = true
                    LIMIT 1
                    """,
                    (lead_key, _GROUP, key),
                )
                row = cur.fetchone()
        return row.get("fact_value") if row else None
    except Exception as exc:  # degradación segura: nunca rompe el flujo
        log.warning("[INSISTENCE] lectura %s falló: %s", key, exc)
        return None


def _write_fact(lead_key: str, key: str, value: str) -> None:
    if not lead_key:
        return
    try:
        upsert_lead_fact(
            lead_key=lead_key, fact_group=_GROUP, fact_key=key,
            fact_value=str(value), confidence=1.0, source="insistence_guard",
        )
    except Exception as exc:
        log.warning("[INSISTENCE] escritura %s falló: %s", key, exc)


def read_insistence_count(lead_key: str) -> int:
    v = _read_fact(lead_key, _COUNT_KEY)
    try:
        return int(v) if v else 0
    except (TypeError, ValueError):
        return 0


def paused_until(lead_key: str) -> _dt.datetime | None:
    v = _read_fact(lead_key, _PAUSE_KEY)
    if not v:
        return None
    try:
        dt = _dt.datetime.fromisoformat(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_dt.timezone.utc)
        return dt
    except ValueError:
        return None


def is_paused(lead_key: str) -> bool:
    """True si el lead está en pausa activa (paused_until en el futuro)."""
    pu = paused_until(lead_key)
    return pu is not None and pu > _now()


def increment_insistence(lead_key: str) -> int:
    """Suma 1 al contador y lo devuelve."""
    n = read_insistence_count(lead_key) + 1
    _write_fact(lead_key, _COUNT_KEY, str(n))
    return n


def reset_insistence(lead_key: str) -> None:
    """Reinicia el contador a 0 (al aportar un dato válido). No toca la pausa."""
    if read_insistence_count(lead_key):
        _write_fact(lead_key, _COUNT_KEY, "0")


def set_pause(lead_key: str, hours: int = PAUSE_HOURS) -> _dt.datetime:
    """Fija la pausa hasta ahora + ``hours`` y devuelve el instante final."""
    until = _now() + _dt.timedelta(hours=hours)
    _write_fact(lead_key, _PAUSE_KEY, until.isoformat())
    log.info("[INSISTENCE_PAUSE] lead=%s pausado hasta %s", lead_key, until.isoformat())
    return until
