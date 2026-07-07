"""Registro del expediente documental por candidato (document-expediente-vision-v2).

Estado por documento en ``rh_lead_facts_v2`` (grupo ``expediente``):
- ``expediente.<tipo>.status``  → pendiente | declarado | recibido | analizado | ilegible
- ``expediente.<tipo>.dato``    → dato extraído mínimo (Bloque 3, shadow primero)
- ``expediente.<tipo>.discrepancia`` → "declaró X, documento muestra Y" (Bloque 4)
- ``expediente.<tipo>.received_at``  → ISO timestamp de recepción

Reglas (specs candidate-expediente-registry / data-privacy-consent):
- Las IMÁGENES nunca se persisten; solo estado + datos mínimos (minimización LFPDPPP).
- Declarar (texto) ≠ enviar (imagen): solo el envío palomea recibido/analizado.
- Re-subir el mismo tipo ACTUALIZA el registro (upsert único = dedupe gratis).
- El estado "declarado" de licencia/apto/comprobante laboral se DERIVA de los facts de
  perfil ya existentes (license.category, apto_expiration_text, documents.proof) — no se
  duplica la extracción de texto.
"""
from __future__ import annotations

import datetime as _dt
import logging
import re
from typing import Any

log = logging.getLogger(__name__)

# Líneas de clasificación que el prompt de visión antepone al texto de perfilamiento.
_TIPO_RE = re.compile(r"^\s*tipo_documento\s*:\s*(\S+)\s*$", re.IGNORECASE | re.MULTILINE)
_LEGIBLE_RE = re.compile(r"^\s*legible\s*:\s*(si|sí|no)\s*$", re.IGNORECASE | re.MULTILINE)


def parse_vision_classification(vision_text: str) -> tuple[str, str | None, bool]:
    """Separa la clasificación (tipo_documento/legible) del texto de perfilamiento.

    Devuelve ``(texto_limpio, tipo_canónico | None, legible)``. El tipo se valida
    contra el catálogo (fuera de catálogo o 'desconocido' → None). Las líneas de
    clasificación se REMUEVEN del texto para que el pipeline de facts no las vea.
    Determinista: nunca inventa tipo si el LLM no lo emitió.
    """
    text = vision_text or ""
    m_tipo = _TIPO_RE.search(text)
    m_leg = _LEGIBLE_RE.search(text)
    tipo = canonical_doc_type(m_tipo.group(1)) if m_tipo else None
    legible = (m_leg.group(1).lower() in {"si", "sí"}) if m_leg else True
    clean = _TIPO_RE.sub("", text)
    clean = _LEGIBLE_RE.sub("", clean)
    clean = "\n".join(l for l in clean.splitlines() if l.strip()).strip()
    return clean, tipo, legible

# Catálogo de tipos de documento del expediente (validación determinista del clasificador
# de visión — cualquier valor fuera del catálogo se trata como "desconocido").
DOC_TYPES: dict[str, str] = {
    "licencia_federal":            "Licencia federal",
    "apto_medico":                 "Apto médico",
    "ine":                         "INE",
    "carta_laboral":               "Carta laboral",
    "semanas_imss":                "Semanas cotizadas IMSS",
    "comprobante_pago_renovacion": "Comprobante de pago (renovación)",
    "curp":                        "CURP",
    "rfc":                         "RFC",
    "acta_nacimiento":             "Acta de nacimiento",
    "nss":                         "NSS",
    "comprobante_domicilio":       "Comprobante de domicilio",
    "comprobante_estudios":        "Comprobante de estudios",
}

# Orden del checklist en la Nota IA. carta_laboral y semanas_imss se muestran como un
# solo renglón "Comprobante laboral" (cualquiera de los dos satisface — regla D3 #18/B2).
NOTE_CHECKLIST: tuple[tuple[str, str], ...] = (
    ("licencia_federal",      "Licencia federal"),
    ("apto_medico",           "Apto médico"),
    ("ine",                   "INE"),
    ("comprobante_laboral",   "Comprobante laboral (2 cartas o IMSS)"),
    ("curp",                  "CURP"),
    ("rfc",                   "RFC"),
    ("acta_nacimiento",       "Acta de nacimiento"),
    ("nss",                   "NSS"),
    ("comprobante_domicilio", "Comprobante de domicilio"),
    ("comprobante_estudios",  "Comprobante de estudios"),
)

_RECEIVED_STATES = {"recibido", "analizado", "ilegible"}


def canonical_doc_type(raw: str | None) -> str | None:
    """Valida el tipo emitido por visión contra el catálogo; fuera de catálogo → None."""
    t = str(raw or "").strip().lower().replace(" ", "_")
    return t if t in DOC_TYPES else None


def mark_received(lead_key: str, tipo: str, legible: bool = True) -> bool:
    """Registra la recepción de un documento (imagen verificada por visión).

    ``legible=False`` marca estado "ilegible" (se pedirá re-toma) sin tocar ningún
    fact de perfil. Re-subida del mismo tipo actualiza (última gana). La imagen NUNCA
    se persiste aquí — solo estado + timestamp.
    """
    tipo_c = canonical_doc_type(tipo)
    if not lead_key or not tipo_c:
        return False
    try:
        from app.lead_memory.repository import upsert_lead_fact
        status = "recibido" if legible else "ilegible"
        upsert_lead_fact(
            lead_key=lead_key, fact_group="expediente",
            fact_key=f"{tipo_c}.status", fact_value=status,
            confidence=1.0, source="vision_document",
        )
        upsert_lead_fact(
            lead_key=lead_key, fact_group="expediente",
            fact_key=f"{tipo_c}.received_at",
            fact_value=_dt.datetime.now(_dt.timezone.utc).isoformat(),
            confidence=1.0, source="vision_document",
        )
        return True
    except Exception as exc:  # degradación segura: la recepción no rompe el turno
        log.warning("[EXPEDIENTE] mark_received falló (%s): %s", tipo, exc)
        return False


def _status_of(facts: dict[str, Any], tipo: str) -> str | None:
    return facts.get(f"expediente.{tipo}.status")


def derive_declared(facts: dict[str, Any]) -> set[str]:
    """Tipos con estado DECLARADO derivado de los facts de perfil existentes.

    Declarar ≠ enviar: esto nunca palomea recepción; solo refleja que el candidato
    DIJO tener el documento (o dio el dato que lo implica) en texto.
    """
    declared: set[str] = set()
    if facts.get("license.category") or facts.get("license.expiration_text"):
        declared.add("licencia_federal")
    if (
        facts.get("medical.apto_expiration_text")
        or facts.get("medical.apto_status") in {"vigente", "sí", "si"}
    ):
        declared.add("apto_medico")
    proof = facts.get("documents.proof")
    if proof == "cartas" or facts.get("documents.labor_letters") in {"sí", "si"} or \
            facts.get("documents.labor_letters_status") in {"available", "sí", "si"}:
        declared.add("carta_laboral")
    if proof == "semanas_imss":
        declared.add("semanas_imss")
    if facts.get("license.renewal_proof") == "si" or facts.get("medical.renewal_proof") == "si" \
            or facts.get("documents.renewal_proof") == "si":
        declared.add("comprobante_pago_renovacion")
    return declared


def expediente_snapshot(facts: dict[str, Any]) -> list[dict[str, str]]:
    """Estado por renglón del checklist para la Nota IA.

    Devuelve [{key, display, status, dato, discrepancia}] donde status es
    pendiente|declarado|recibido|analizado|ilegible. "comprobante_laboral" combina
    carta_laboral/semanas_imss (el mejor estado de los dos gana).
    """
    declared = derive_declared(facts)

    def _entry(tipo: str) -> tuple[str, str, str]:
        status = _status_of(facts, tipo)
        if status in _RECEIVED_STATES or status == "analizado":
            pass
        elif tipo in declared:
            status = "declarado"
        else:
            status = status or "pendiente"
        return (
            status,
            facts.get(f"expediente.{tipo}.dato") or "",
            facts.get(f"expediente.{tipo}.discrepancia") or "",
        )

    _rank = {"pendiente": 0, "declarado": 1, "ilegible": 2, "recibido": 3, "analizado": 4}
    rows: list[dict[str, str]] = []
    for key, display in NOTE_CHECKLIST:
        if key == "comprobante_laboral":
            # El mejor estado entre cartas e IMSS satisface el renglón combinado.
            best = max(
                (_entry("carta_laboral"), _entry("semanas_imss")),
                key=lambda e: _rank.get(e[0], 0),
            )
            status, dato, disc = best
        else:
            status, dato, disc = _entry(key)
        rows.append({
            "key": key, "display": display, "status": status,
            "dato": dato, "discrepancia": disc,
        })
    return rows


def received_documents(facts: dict[str, Any]) -> list[str]:
    """Tipos ya recibidos/analizados (para el acuse: qué llegó)."""
    return [
        t for t in DOC_TYPES
        if _status_of(facts, t) in {"recibido", "analizado"}
    ]


def missing_documents(facts: dict[str, Any]) -> list[str]:
    """Displays de renglones del checklist SIN recibir (para el acuse: qué falta).

    Un documento declarado sigue faltando como envío (declarar ≠ enviar).
    """
    return [
        row["display"] for row in expediente_snapshot(facts)
        if row["status"] in {"pendiente", "declarado"}
    ]


# ── Privacidad / consentimiento (spec data-privacy-consent, LFPDPPP) ──────────

# Versión del aviso: cambiarla invalida consentimientos previos (re-aviso).
AVISO_VERSION = "v1-2026-07"

# Aviso simplificado (D7). La URL del aviso integral está pendiente de definición
# legal (open question 2.5); hasta entonces se refiere al equipo.
AVISO_CONFIDENCIALIDAD = (
    "📋 Aviso de privacidad: sus datos y documentos se usan únicamente para integrar "
    "su expediente del proceso de contratación en Transmontes. No almacenamos las "
    "imágenes; solo el estado de su expediente. Puede solicitar acceso, corrección o "
    "eliminación de sus datos en cualquier momento con nuestro equipo."
)

CONSENT_APTO_REQUEST = (
    "Su apto médico contiene información de salud, por lo que necesitamos su "
    "autorización expresa para usarlo en su expediente. ¿Nos autoriza? "
    "Responda \"sí, acepto\" y con gusto continuamos."
)

# Respuestas afirmativas cortas aceptadas como consentimiento expreso (determinista).
_CONSENT_YES = {
    "si acepto", "sí acepto", "si, acepto", "sí, acepto", "acepto", "si autorizo",
    "sí autorizo", "autorizo", "si", "sí", "claro que si", "claro que sí", "de acuerdo",
}


def _consent_status(facts: dict[str, Any]) -> str | None:
    return facts.get("expediente.consent.status")


def has_consent_notice(facts: dict[str, Any]) -> bool:
    """True si el aviso simplificado ya fue enviado (cualquier estado de consentimiento)."""
    return bool(_consent_status(facts))


def has_express_consent(facts: dict[str, Any]) -> bool:
    """True solo con consentimiento EXPRESO (requerido para el apto médico)."""
    return _consent_status(facts) == "expreso"


def apto_consent_pending(facts: dict[str, Any]) -> bool:
    return _consent_status(facts) == "apto_pendiente"


def _write_consent(lead_key: str, status: str) -> bool:
    try:
        from app.lead_memory.repository import upsert_lead_fact
        upsert_lead_fact(
            lead_key=lead_key, fact_group="expediente", fact_key="consent.status",
            fact_value=status, confidence=1.0, source="privacy_consent",
        )
        upsert_lead_fact(
            lead_key=lead_key, fact_group="expediente", fact_key="consent.timestamp",
            fact_value=_dt.datetime.now(_dt.timezone.utc).isoformat(),
            confidence=1.0, source="privacy_consent",
        )
        upsert_lead_fact(
            lead_key=lead_key, fact_group="expediente", fact_key="consent.version",
            fact_value=AVISO_VERSION, confidence=1.0, source="privacy_consent",
        )
        return True
    except Exception as exc:
        log.warning("[EXPEDIENTE] consentimiento no registrado (%s): %s", status, exc)
        return False


def register_consent_notice(lead_key: str) -> bool:
    """Registra el envío del aviso simplificado (timestamp + versión)."""
    return _write_consent(lead_key, "aviso_enviado")


def request_apto_consent(lead_key: str) -> bool:
    """Marca que se pidió el consentimiento expreso del apto (en espera de 'sí acepto')."""
    return _write_consent(lead_key, "apto_pendiente")


def register_express_consent(lead_key: str) -> bool:
    """Registra el consentimiento EXPRESO (acción afirmativa del candidato)."""
    return _write_consent(lead_key, "expreso")


def is_consent_affirmative(message: str) -> bool:
    """Determinista: ¿el mensaje es una afirmación corta de consentimiento?"""
    from app.knowledge.text_normalizer import normalize_text
    t = normalize_text(message or "").strip().rstrip(".!")
    return t in _CONSENT_YES


# ── Retención / eliminación (LFPDPPP: bloqueo y supresión) ────────────────────

def purge_lead_expediente(lead_key: str) -> int:
    """Elimina TODOS los facts del grupo expediente de un lead (derecho ARCO /
    fin de proceso). Devuelve filas eliminadas."""
    if not lead_key:
        return 0
    from app.db import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM rh_lead_facts_v2 WHERE lead_key = %s AND fact_group = 'expediente'",
                (lead_key,),
            )
            return cur.rowcount or 0


def purge_expired_expedientes(retention_days: int | None = None) -> dict[str, int]:
    """Job de purga por retención: elimina facts `expediente.*` de leads SIN actividad
    (ningún mensaje) en los últimos ``retention_days`` (env EXPEDIENTE_RETENTION_DAYS,
    default 90). Devuelve {leads_purgados, facts_eliminados}."""
    import os
    days = retention_days if retention_days is not None else int(
        os.getenv("EXPEDIENTE_RETENTION_DAYS", "90") or 90
    )
    from app.db import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH inactivos AS (
                    SELECT f.lead_key
                    FROM rh_lead_facts_v2 f
                    WHERE f.fact_group = 'expediente'
                    GROUP BY f.lead_key
                    HAVING COALESCE(
                        (SELECT MAX(m.created_at) FROM rh_lead_messages_v2 m
                         WHERE m.lead_key = f.lead_key),
                        NOW() - INTERVAL '100 years'
                    ) < NOW() - make_interval(days => %s)
                )
                DELETE FROM rh_lead_facts_v2
                WHERE fact_group = 'expediente'
                  AND lead_key IN (SELECT lead_key FROM inactivos)
                RETURNING lead_key
                """,
                (days,),
            )
            rows = cur.fetchall() or []
    leads = len({r["lead_key"] if isinstance(r, dict) else r[0] for r in rows})
    result = {"leads_purgados": leads, "facts_eliminados": len(rows)}
    log.info("[EXPEDIENTE_PURGA] retention_days=%s %s", days, result)
    return result


def build_acuse(
    facts: dict[str, Any],
    received_now: list[str],
    ilegible_now: list[str],
) -> str:
    """Acuse específico por documento (spec: nombra lo recibido + qué falta).

    Contenido determinista (qué llegó / qué falta del registro); la redacción intenta
    la voz de Mundo vía LLM con fallback determinista si el LLM no está disponible.
    ``received_now``/``ilegible_now`` son tipos canónicos recibidos en ESTE turno.
    """
    recibidos = [DOC_TYPES[t] for t in received_now if t in DOC_TYPES]
    ilegibles = [DOC_TYPES[t] for t in ilegible_now if t in DOC_TYPES]
    faltan = missing_documents(facts)

    # Fallback determinista (siempre correcto en contenido).
    parts: list[str] = []
    if recibidos:
        parts.append(f"Gracias por subir su {', '.join(recibidos)} ✓.")
    if ilegibles:
        parts.append(
            f"Recibimos su {', '.join(ilegibles)}, pero la imagen no se alcanza a leer "
            "bien. ¿Nos ayuda tomando la foto de nuevo, con buena luz y el documento completo?"
        )
    if faltan and not ilegibles:
        _lista = ", ".join(faltan[:4]) + (" y otros" if len(faltan) > 4 else "")
        parts.append(f"Para su expediente nos faltaría: {_lista}.")
    elif not faltan and not ilegibles:
        parts.append("¡Con esto su expediente queda completo! Nuestro equipo lo revisa y le damos seguimiento.")
    fallback = " ".join(parts)

    # Redacción natural (voz de Mundo, variada) sobre los MISMOS datos deterministas.
    try:
        from app.indexer import call_groq_with_system
        from app.persona_config import SYSTEM_PROMPT
        prompt = (
            "El candidato acaba de enviar documento(s) de su expediente. Redacta un acuse "
            "breve (2 frases máx.) con estos hechos EXACTOS, sin inventar nada: "
            f"recibidos ahora: {recibidos or 'ninguno'}; ilegibles (pedir re-tomar foto con "
            f"buena luz): {ilegibles or 'ninguno'}; aún faltan: {faltan[:4] or 'ninguno'}. "
            "Agradece nombrando lo recibido; si hay ilegible, pide amablemente re-tomar la "
            "foto; si faltan, menciónalos. No prometas contratación."
        )
        out = (call_groq_with_system(SYSTEM_PROMPT, prompt, temperature=0.4, max_tokens=140) or "").strip()
        return out or fallback
    except Exception as exc:
        log.warning("[EXPEDIENTE] acuse LLM falló, usando fallback: %s", exc)
        return fallback
