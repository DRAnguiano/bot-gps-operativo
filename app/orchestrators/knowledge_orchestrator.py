from __future__ import annotations

import logging
import os
import random
import re
import time


log = logging.getLogger(__name__)
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.db import get_conversation_state, log_event, make_conversation_key, save_message, update_stage, upsert_conversation
from app.indexer import call_llm
from app.knowledge.context_builder import build_generation_prompt, estimate_llm_cost, retrieve_preferred_context
from app.knowledge.domain_catalog import NON_TARGET, VEHICLE_TERMS
from app.knowledge.normalize_domain_values import normalize_vehicle
from app.knowledge.neo4j_client import resolve_message
from app.knowledge.text_normalizer import normalize_text
from app.lead_memory.repository import (
    get_lead_memory,
    log_lead_event,
    save_lead_message,
    update_lead_summary,
    upsert_lead_fact,
    upsert_lead_identity,
)


CONTROLLED_CLARIFICATION_REPLY = (
    "Para responderte bien, ¿me puedes explicar a qué te refieres? "
    "Así evitamos malinterpretar tu mensaje."
)

CONTROLLED_FALLBACK_REPLY = (
    "No quiero darte información incorrecta. Puedo ayudarte con pago, documentos, "
    "requisitos, ubicación, licencia, apto médico o disponibilidad."
)

NO_CONTEXT_REPLY = (
    "No encontré información interna suficiente para responder eso con seguridad. "
    "Para ese dato llámenos de 8:00 a 17:30 hrs y le confirmamos."
)

DOCUMENT_ACK_REPLY = (
    "Gracias, ya tenemos parte de su información registrada. "
    "Continuamos con las preguntas pendientes para completar su perfil."
)

FAREWELL_REPLY = (
    "Gracias a usted. Que tenga buen día y maneje con cuidado. Dejamos su seguimiento abierto; "
    "cuando guste retomar el proceso, por aquí lo apoyamos."
)

# Saludo/contrato de apertura aprobado por negocio (2026-06-12): anuncia el
# perfilamiento, invita a preguntar primero, y adelanta documentación + agente.
_GREETING_INTRO = (
    "Hola, soy Mundo del equipo de reclutamiento de Transmontes. "
    "Con gusto le platico de la vacante de operador de tracto full o sencillo. "
    "Le haré unas preguntas breves para conocer su perfil; si antes tiene dudas "
    "de pago, rutas o requisitos, pregúnteme con confianza. "
)

GREETING_REPLY = _GREETING_INTRO + "¿Me podría decir su nombre y apellido, por favor?"


def greeting_reply_for_facts(current_turn_facts: dict) -> str:
    """Saludo inicial adaptado: si el candidato ya dio datos en el primer mensaje,
    salta los campos conocidos y pregunta el siguiente faltante."""
    from app.knowledge.current_turn import next_question_from_missing_facts
    next_q = next_question_from_missing_facts(current_turn_facts)
    if not next_q:
        return (
            _GREETING_INTRO
            + "Con los datos que me compartió, su perfil está listo. "
            "En breve nuestro equipo le contactará."
        )
    return _GREETING_INTRO + next_q

def _greeting_followup_question(lead_memory: dict[str, Any]) -> str:
    """Siguiente dato del funnel SIN el intro de saludo de Mundo.

    Se usa cuando, en primer contacto, el mensaje trae una pregunta embebida cuya
    respuesta ya saluda: evita repetir "Hola, soy Mundo…" dos veces (F1). Si no
    queda nada por preguntar, devuelve cadena vacía (la respuesta embebida basta)."""
    known = {
        f"{row['fact_group']}.{row['fact_key']}": str(row["fact_value"])
        for row in (lead_memory.get("facts") or [])
        if row.get("fact_value")
    }
    from app.knowledge.current_turn import next_question_from_missing_facts
    return next_question_from_missing_facts(known) or ""


def _greeting_reply(lead_memory: dict[str, Any]) -> str:
    """Primera visita → GREETING_REPLY completo. Candidato que regresa → ack corto + siguiente campo."""
    known: dict[str, str] = {
        f"{row['fact_group']}.{row['fact_key']}": str(row["fact_value"])
        for row in (lead_memory.get("facts") or [])
        if row.get("fact_value")
    }
    if not known:
        return GREETING_REPLY
    from app.knowledge.current_turn import next_question_from_missing_facts
    next_q = next_question_from_missing_facts(known)
    if not next_q:
        return "¡Hola de nuevo! Su perfil está completo, lo canalizamos pronto con el equipo de reclutamiento."
    return f"¡Hola de vuelta! Continuamos donde quedamos.\n\n{next_q}"


_GREETING_TERMS = (
    "hola", "buen dia", "buen día", "buenos dias", "buenos días",
    "buenas tardes", "buenas noches", "buenas", "ola", "hey", "hi",
)


PROFILE_ACK_HINTS = (
    "ya mande", "ya mandé", "ya envie", "ya envié", "ya subi", "ya subí",
    "ya cargue", "ya cargué", "ya lo mande", "ya lo mandé", "ya los mande",
    "ya los mandé", "ya quedo", "ya quedó", "listo", "ahi esta", "ahí está",
    # candidato reclama que ya dio sus datos en este chat
    "ya habia pasado", "ya había pasado", "ya les pase", "ya les pasé",
    "ya tenia mis datos", "ya tenía mis datos", "ya le di mis datos",
    "ya le habia dado", "ya había dado", "ya le pase mis datos", "ya le pasé mis datos",
)

DOCUMENT_WORDS = (
    "documento", "documentos", "doc", "docs", "papel", "papeles", "informacion",
    "información", "datos", "licencia", "apto", "ine", "curp", "comprobante", "cartas",
)

# Origen ÚNICO en current_turn (Fase 2/D5): evita dos listas divergentes.
from app.knowledge.current_turn import BUSINESS_QUESTION_TERMS  # noqa: E402

FAREWELL_HINTS = (
    "gracias señor", "gracias senor", "gracias muy amable", "muchas gracias",
    "gracias", "pase buen dia", "pase buen día",
    "hasta luego", "nos vemos", "saludos", "que este bien", "que esté bien",
    "luego le escribo", "luego le marco", "lo retomo luego",
)

# "buen dia" / "buen día" alone are ambiguous (greeting OR farewell).
# Block farewell detection when the message opens with a clear greeting word.
GREETING_GUARD_TERMS = (
    "hola", "ola", "holaa", "hey", "ei",
    "buenos dias", "buenos días", "buenas tardes", "buenas noches", "buenas",
    "buen dia", "buen día",
)

DISALLOWED_FREE_CHAT_TERMS = (
    "droga", "drogas", "mota", "marihuana", "mariguana", "cristal", "perico",
    "cocaina", "cocaína", "metanfetamina", "huachicol", "robo", "arma",
    "licencia falsa", "documento falso", "evadir", "burlar",
)


STAGE_LABELS = {
    "new": "Nuevo lead",
    "interested": "Interesado",
    "vacancy_info_shared": "Información de vacante compartida",
    "profile_hint_collected": "Perfil preliminar detectado",
    "documents_pending": "Documentos pendientes",
    "documents_received": "Documentos recibidos / por validar",
    "apto_pending_update": "Apto médico por actualizar",
    "safety_review": "Revisión de seguridad",
    "followup_pending": "Seguimiento pendiente",
    "human_review": "Revisión humana",
    "lost": "Perdido / abandonó",
    "closed": "Cerrado",
}


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _route_flags(route: str, risk_level: str) -> dict[str, bool]:
    route = route or "fallback"
    risk = (risk_level or "low").lower()
    return {
        "requires_rag": route == "rag",
        "requires_human": route in {"human_handoff", "policy_boundary"} or risk == "high",
        "requires_clarification": route == "clarification",
    }


def _clean_reply(text: str) -> str:
    """Limpia la respuesta del LLM — delega al cleaner unificado (rag-corpus #13)."""
    from app.knowledge.reply_cleaner import clean_reply

    return clean_reply(text)


# ── Humor LLM con barda (decisión 2026-06-12) ────────────────────────────────
# El Term smalltalk_joke detecta el chiste de forma determinista; la respuesta
# la genera el LLM bajo reglas estrictas. La plantilla del seed es el FALLBACK
# si el LLM falla, devuelve vacío o el chiste viola la barda. El puente al
# funnel lo agrega el código (no el modelo) para que sea idéntico siempre.

_JOKE_PROMPT = (
    "Eres Mundo, asistente de reclutamiento de Transmontes. Cuenta UN chiste "
    "corto y blanco sobre traileros, tractocamiones o la vida en carretera, en "
    "español mexicano. Reglas estrictas: máximo 2 frases; prohibido doble "
    "sentido, albures, sustancias, alcohol, accidentes, muerte, religión, "
    "política o burlas a personas; tono amable. Devuelve SOLO el chiste, sin "
    "comillas, sin saludo y sin cierre."
)

_JOKE_BRIDGE = "🚛 Ahora sí, seguimos con su registro."

# Términos vetados (sobre texto normalizado): si el chiste generado toca
# cualquiera, se usa el fallback determinista del seed.
_JOKE_BANNED = (
    "drog", "alcohol", "cerveza", "borrach", "muert", "accident", "choc",
    "sexo", "sexual", "albur", "desnud", "matar", "pistol", "narco",
    "secuestr", "religio", "politic", "vieja", "gord",
)


def _generate_joke_reply(fallback: str) -> str:
    try:
        joke = (call_llm(_JOKE_PROMPT) or "").strip().strip('"').strip()
    except Exception:
        return fallback
    if not (10 <= len(joke) <= 240):
        return fallback
    normalized = normalize_text(joke)
    if any(term in normalized for term in _JOKE_BANNED):
        return fallback
    return f"{joke} {_JOKE_BRIDGE}"


def _controlled_reply_from_contract(contract: dict[str, Any]) -> str:
    template = contract.get("reply_template")
    if isinstance(template, dict) and template.get("text"):
        text = str(template["text"])
        if template.get("id") == "static_joke":
            return _generate_joke_reply(fallback=text)
        return text
    if contract.get("requires_clarification"):
        return CONTROLLED_CLARIFICATION_REPLY
    if contract.get("requires_human"):
        return "Ese punto debe revisarlo nuestro equipo antes de continuar. Lo dejo anotado para seguimiento."
    return CONTROLLED_FALLBACK_REPLY


def _message_has_any(message: str, terms: tuple[str, ...]) -> bool:
    text = normalize_text(message)
    return any(normalize_text(term) in text for term in terms)


def _is_time_question(message: str) -> bool:
    text = normalize_text(message)
    return any(
        phrase in text
        for phrase in (
            "que hora es", "qué hora es", "hora es", "me dices la hora",
            "tiene la hora", "sabes la hora",
        )
    )


def _time_reply() -> str:
    now = datetime.now(ZoneInfo("America/Mexico_City"))
    time_text = now.strftime("%-I:%M %p").lower().replace("am", "a. m.").replace("pm", "p. m.")
    return f"En Torreón son las {time_text}; es la misma zona horaria del centro de México."


def _resolve_embedded_question(
    message: str,
    contract: dict[str, Any],
    lead_memory: dict[str, Any] | None,
    turn_signals: Any = None,
) -> dict[str, Any] | None:
    """answer_primary_question (multi-intent al path vivo).

    Cuando el mensaje es compuesto (respuesta de perfil + pregunta) y la ruta
    principal NO es ya RAG, resuelve la pregunta embebida con fundamento para que
    el path vivo la responda en vez de solo avanzar el funnel. Hereda el
    fail-closed de `_generate_rag_answer`: para intents que exigen fuente
    autorizada (pago) sin contexto, deriva a Capital Humano en vez de inventar.

    Devuelve {"answer", "derive_to_human", "intent"} o None si no aplica.
    Nunca propaga errores: ante fallo, devuelve None y el path vivo sigue intacto.
    """
    if contract.get("requires_rag") or contract.get("requires_human"):
        return None
    # Detector ÚNICO (Fase 2/D5): mismo que consume el guard del worker. Con
    # turn_signals cubre el compuesto "sin ? ni término conocido"; sin señal es
    # determinista (gate barato, no dispara LLM).
    from app.knowledge.current_turn import has_business_question
    if not has_business_question(message, turn_signals):
        return None
    try:
        from app.knowledge.intent_classifier import classify_message
        from app.knowledge.intent_enricher import enrich_classification
        from app.knowledge.intent_orchestrator import _generate_rag_answer

        last_q: str | None = None
        for row in reversed((lead_memory or {}).get("messages") or []):
            if isinstance(row, dict) and row.get("role") != "user" and row.get("message"):
                last_q = str(row["message"])
                break

        classification = classify_message(message, last_bot_question=last_q)
        enriched = enrich_classification(classification)
        questions = [q for q in (enriched.get("questions") or []) if q.get("requires_rag")]
        if not questions:
            return None
        q = questions[0]
        # Inyecta la residencia determinista (catálogo ZM Laguna) para que el LLM
        # no deduzca local/foráneo del nombre crudo de la ciudad. Combina los facts
        # persistidos con los extraídos en este mismo turno (mensaje compuesto).
        _rag_facts = {
            f"{row['fact_group']}.{row['fact_key']}": row['fact_value']
            for row in ((lead_memory or {}).get("facts") or [])
            if isinstance(row, dict) and row.get("fact_group") and row.get("fact_key")
        }
        for _ans in (enriched.get("answers_to_persist") or []):
            if _ans.get("field") and _ans.get("value") is not None:
                _rag_facts[str(_ans["field"])] = str(_ans["value"])
        answer_text, derive = _generate_rag_answer(q, message, _rag_facts)
        # Limpia por el limpiador unificado (igual que _answer_rag_message): elimina
        # `<think></think>` vacío y `> ` residuales antes de anteponer al reply.
        answer_text = _clean_reply(answer_text or "")
        if not answer_text:
            return None
        return {
            "answer": answer_text,
            "derive_to_human": bool(derive),
            "intent": q.get("intent"),
        }
    except Exception as exc:  # nunca romper el path vivo por esta mejora
        log.warning("[ANSWER_PRIMARY_QUESTION] omitido por error: %s", exc)
        return None


def _looks_like_farewell(message: str) -> bool:
    text = normalize_text(message)
    if not text:
        return False
    if not any(normalize_text(hint) in text for hint in FAREWELL_HINTS):
        return False
    if "?" in message or "¿" in message:
        return False
    # A message that opens with a greeting word is not a farewell.
    # Use startswith so "pase buen dia" (farewell) is not confused with
    # "buen dia" / "hola buen dia" (greetings).
    if any(text.startswith(normalize_text(g)) for g in GREETING_GUARD_TERMS):
        return False
    if _message_has_any(message, BUSINESS_QUESTION_TERMS) and len(text) > 80:
        return False
    return True


def _looks_like_profile_ack(message: str, contract: dict[str, Any]) -> bool:
    has_ack = _message_has_any(message, PROFILE_ACK_HINTS)
    has_document_word = _message_has_any(message, DOCUMENT_WORDS)
    return bool(has_ack and has_document_word)


def _apply_profile_guards(message: str, contract: dict[str, Any]) -> dict[str, Any]:
    if _looks_like_profile_ack(message, contract):
        guarded = dict(contract)
        guarded.update(
            {
                "recognized_terms": list(dict.fromkeys(list(guarded.get("recognized_terms") or []) + ["document_ack"])),
                "intent": "document_submission_ack",
                "route": "profile",
                "risk_level": "low",
                "requires_rag": False,
                "requires_human": False,
                "requires_clarification": False,
                "preferred_sources": [],
                "reply_template": {"id": "document_ack", "text": DOCUMENT_ACK_REPLY},
                "reason": "profile_guard_document_submission_ack",
                "profile_guard_applied": True,
            }
        )
        return guarded
    return contract


_CALL_ACCEPT_HINTS = (
    "sí", "si", "claro", "por supuesto", "adelante", "está bien", "esta bien",
    "me parece", "de acuerdo", "ok", "okay", "acepto", "con gusto",
)

_CALL_TIME_HINTS = (
    "de ", "entre ", "mañana", "tarde", "noche", "lunes", "martes", "miércoles",
    "miercoles", "jueves", "viernes", "sábado", "sabado", "am", "pm",
    "hrs", "hora", "horas", "disponible",
)


def _pending_call_request(lead_key: str) -> bool:
    """True si el lead tiene una solicitud de llamada enviada en los últimos 7 días."""
    try:
        from datetime import datetime, timedelta, timezone
        from app.db import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1 FROM rh_seguimiento_tareas
                    WHERE lead_key = %(lead_key)s
                      AND tipo = 'solicitud_llamada'
                      AND estado = 'enviado'
                      AND enviado_en >= now() - interval '7 days'
                    LIMIT 1
                    """,
                    {"lead_key": lead_key},
                )
                return cur.fetchone() is not None
    except Exception:
        return False


def _save_call_preference_note(
    *,
    lead_key: str,
    message: str,
    lead_memory: dict[str, Any],
) -> None:
    """Guarda nota privada en Chatwoot con el horario preferido del candidato."""
    try:
        from app.followup.templates import nota_horario_llamada
        from app.followup.sender import _ids_chatwoot, _enviar_nota_privada

        lead = lead_memory.get("lead") or {}
        nombre = lead.get("display_name")
        telefono = lead.get("phone")
        etapa = lead.get("funnel_stage", "")

        nota = nota_horario_llamada(nombre, message, etapa, telefono)
        account_id, conversation_id = _ids_chatwoot(lead_key)
        if account_id and conversation_id:
            _enviar_nota_privada(account_id, conversation_id, nota)
            print(f"[CALL_PREF_SAVED] lead={lead_key}", flush=True)
    except Exception as exc:
        print(f"[CALL_PREF_ERROR] lead={lead_key} error={exc}", flush=True)


def _looks_like_greeting(message: str) -> bool:
    text = normalize_text(message).strip()
    if not text or len(text.split()) > 5:
        return False
    if "?" in message or "¿" in message:
        return False
    if _message_has_any(message, BUSINESS_QUESTION_TERMS):
        return False
    return any(normalize_text(t) in text for t in _GREETING_TERMS)


# Marcadores de residencia en primera persona: solo con uno presente se acepta
# geo (city/state) extraído de un mensaje-pregunta. "¿qué rutas maneja para
# nuevo laredo?" NO fija ciudad; "soy de laredo, ¿a dónde salen?" SÍ.
_RESIDENCE_MARKERS = (
    "soy de", "soy d ",   # "soy d " = abreviatura sin typo-canon
    "soi de", "soi d ",
    "vivo en", "vivo n ",
    "radico en", "resido en", "estoy en", "me encuentro en",
)


def _drop_geo_facts_from_questions(facts: list[dict[str, Any]], message: str) -> list[dict[str, Any]]:
    """Filtra candidate.city/state cuando el mensaje es pregunta sin marcador de residencia."""
    from app.knowledge.current_turn import is_question

    if not is_question(message):
        return facts
    text = normalize_text(message or "")
    if any(marker in text for marker in _RESIDENCE_MARKERS):
        return facts
    return [
        f for f in facts
        if not (f.get("fact_group") == "candidate" and f.get("fact_key") in {"city", "state"})
    ]


def _drop_unanchored_neo4j_geo(facts: list[dict[str, Any]], message: str) -> list[dict[str, Any]]:
    """Con marcador de residencia presente, el geo de Neo4j se descarta.

    Los nodos GeoArea matchean CUALQUIER mención de ciudad (incl. destinos:
    "para ir a torreon"), mientras el regex de profile_extractor ancla la ciudad
    al marcador "soy de / vivo en". Si hay marcador, la fuente anclada gana y
    aquí se remueve el geo de Neo4j ANTES del dedup para que no la suprima.
    """
    text = normalize_text(message or "")
    if not any(marker in text for marker in _RESIDENCE_MARKERS):
        return facts
    return [
        f for f in facts
        if not (
            f.get("fact_group") == "candidate"
            and f.get("fact_key") in {"city", "state"}
            and f.get("neo4j_node_id")
        )
    ]


def _apply_deterministic_overrides(message: str, contract: dict[str, Any]) -> dict[str, Any]:
    # Greeting check first — prevents "hola buen dia" from hitting farewell
    if _looks_like_greeting(message):
        updated = dict(contract)
        updated.update(
            {
                "recognized_terms": ["greeting"],
                "matched_aliases": ["greeting"],
                "intent": "greeting",
                "route": "profile",
                "risk_level": "low",
                "requires_rag": False,
                "requires_human": False,
                "requires_clarification": False,
                "preferred_sources": [],
                "reply_template": {"id": "greeting", "text": GREETING_REPLY},
                "reason": "deterministic_greeting_reply",
            }
        )
        return updated

    if _looks_like_farewell(message):
        updated = dict(contract)
        updated.update(
            {
                "recognized_terms": ["farewell"],
                "matched_aliases": ["farewell"],
                "intent": "farewell",
                "route": "profile",
                "risk_level": "low",
                "requires_rag": False,
                "requires_human": False,
                "requires_clarification": False,
                "preferred_sources": [],
                "reply_template": {"id": "farewell", "text": FAREWELL_REPLY},
                "reason": "deterministic_farewell_reply",
            }
        )
        return updated

    if _is_time_question(message):
        updated = dict(contract)
        updated.update(
            {
                "recognized_terms": ["local_time"],
                "matched_aliases": ["hora"],
                "intent": "local_time",
                "route": "friendly_smalltalk",
                "risk_level": "low",
                "requires_rag": False,
                "requires_human": False,
                "requires_clarification": False,
                "preferred_sources": [],
                "reason": "deterministic_local_time_reply",
            }
        )
        return updated

    return contract


# ── Guard determinista de reglas de negocio (live-business-rule-enforcement) ──
# Política operativa que NO vive en el seed Neo4j (vocabulario): se aplica en código
# determinista sobre el camino vivo, por lo que también obliga cuando Neo4j está en
# fallback. La detección es léxica con límites de palabra (sobre texto normalizado:
# minúsculas, sin acentos) para no atrapar subcadenas ("usa" en "usar", "visa" en
# "revisar"). La detección del concepto puede migrar luego a catálogo/LLM; la DECISIÓN
# de política permanece determinista.
_B1_US_RE = re.compile(
    r"\b(b1|b-1|estados unidos|eeuu|ee uu|eua|usa|ruta americana|lado americano|"
    r"laredo texas|laredo tx|cruce|cruzar|visa|americana)\b"
)
_REINGRESO_RE = re.compile(
    r"\breingres\w*\b"
    r"|volver a trabajar"
    r"|\bya\b.*\btrabaj\w*\b.*\b(ustedes|la empresa|transmontes|aqui|aca)\b"
    r"|\btrabaj\w*\b.*\b(antes|anteriormente)\b.*\b(ustedes|la empresa|transmontes|aqui|aca)\b"
)
# Experiencia no-objetivo (escuelita): reusa el catálogo de dominio en vez de duplicar.
_NON_TARGET_RE = re.compile(
    r"\b(" + "|".join(
        re.escape(term)
        for term, res in VEHICLE_TERMS.items()
        if res.status == NON_TARGET
    ) + r")\b"
)

# B9 — datos sensibles / costo al candidato. Detecta que al candidato le PIDEN pagar/
# depositar o le piden datos bancarios (NO el sueldo: "cuánto pagan" es salario y va por
# RAG). El reclutamiento legítimo nunca cobra al candidato por este medio.
_PAID_SENSITIVE_RE = re.compile(
    r"\b("
    r"tengo que pagar|hay que pagar|debo pagar|tengo que dar dinero|piden dinero|"
    r"me piden dinero|me cobran|cobran algo|tiene costo|tiene algun costo|algun costo|"
    r"cuanto cuesta|cuanto sale|costo del curso|curso tiene costo|pagar inscripcion|"
    r"costo de inscripcion|anticipo|enganche|deposito|cuenta bancaria|numero de cuenta|"
    r"clabe|tarjeta de credito|hacer una transferencia|hacer transferencia"
    r")\b"
)
_SENSITIVE_PAID_REPLY = (
    "Por seguridad, no manejamos pagos, depósitos ni cobros por este medio, y nunca le "
    "pediremos datos bancarios por aquí. Si hubiera algún costo o trámite, nuestro equipo "
    "se lo confirma directamente por el canal autorizado. ¿Le comparto algo más de la vacante?"
)


def _apply_business_rule_overrides(message: str, contract: dict[str, Any], turn_signals=None) -> dict[str, Any]:
    """Aplica políticas de negocio deterministas al contrato del camino vivo."""
    text = normalize_text(message or "")

    # B1 / Estados Unidos / Laredo Texas / cruce → revisión humana, sin perfilar.
    if _B1_US_RE.search(text):
        updated = dict(contract)
        updated.update({
            "route": "human_handoff",
            "intent": "business_route_us",
            "requires_human": True,
            "requires_rag": False,
            "requires_clarification": False,
            "reply_template": {
                "id": "b1_us_handoff",
                "text": "Gracias por comentarlo. Las vacantes B1 o para Estados Unidos las revisa directamente nuestro equipo de Capital Humano. Lo dejo canalizado para que validen su caso.",
            },
            "reason": "deterministic_b1_us_handoff",
        })
        return updated

    # Reingreso (no confundir con "ya conseguí otro trabajo", que es dropoff) → humano.
    if _REINGRESO_RE.search(text):
        updated = dict(contract)
        updated.update({
            "route": "human_handoff",
            "intent": "reingreso_verificar",
            "requires_human": True,
            "requires_rag": False,
            "requires_clarification": False,
            "reply_template": {
                "id": "reingreso_handoff",
                "text": "Gracias por avisarnos. Los reingresos se revisan directamente con Capital Humano; lo dejo canalizado para que validen su historial y le indiquen el siguiente paso.",
            },
            "reason": "deterministic_reingreso_handoff",
        })
        return updated

    # Torton/rabón/reparto/local/camioneta → experiencia no-objetivo (escuelita).
    # No fija vehicle_type full/sencillo; solo agrega la señal para valoración humana.
    # BUG-1: quinta rueda y variantes no están en _NON_TARGET_RE (domain_catalog); se detectan aquí
    _QUINTA_RUEDA_TERMS = ("quinta rueda", "5ta rueda", "kinta rueda", "quintarueda", "quinta_rueda")
    _is_quinta_rueda = any(t in text for t in _QUINTA_RUEDA_TERMS)

    if _NON_TARGET_RE.search(text) or _is_quinta_rueda:
        updated = dict(contract)
        signals = list(updated.get("business_signals") or [])
        if "considerar_escuelita_transmontes" not in signals:
            signals.append("considerar_escuelita_transmontes")
        updated.update({
            "route": "human_handoff",
            "intent": "considerar_escuelita_transmontes",
            "requires_human": True,
            "requires_rag": False,
            "requires_clarification": False,
            "business_signals": signals,
            "reply_template": {
                "id": "escuelita_handoff",
                "text": "Gracias por compartir su experiencia. Para torton, rabon o reparto, Capital Humano revisa si hay generacion disponible para escuelita interna. Lo dejo canalizado para que validen su caso.",
            },
            "reason": "deterministic_non_target_escuelita",
        })
        return updated

    if turn_signals is not None:
        _no_road_experience = turn_signals.no_road_experience
    else:
        try:
            from app.knowledge.turn_intent_classifier import classify_turn_intent
            _no_road_experience = classify_turn_intent(message).no_road_experience
        except Exception:
            _no_road_experience = False
    if _no_road_experience:
        updated = dict(contract)
        signals = list(updated.get("business_signals") or [])
        if "cecati_sugerido" not in signals:
            signals.append("cecati_sugerido")
        updated.update({
            "route": "human_handoff",
            "intent": "cecati_sugerido",
            "requires_human": True,
            "requires_rag": False,
            "requires_clarification": False,
            "business_signals": signals,
            "reply_template": {
                "id": "cecati_handoff",
                "text": "Gracias por su interes. Por ahora las vacantes son para operadores con experiencia en tracto full o sencillo. Si quiere aprender, puede revisar la opcion del CECATI en Gomez Palacio y, al completar su preparacion, volver a contactarnos para continuar.",
            },
            "reason": "deterministic_cecati_no_experience",
        })
        return updated

    # B8 — corrección explícita a un objetivo claro (full/sencillo) limpia una escuelita
    # PREVIA. El overwrite del vehicle_type ya lo hace el upsert; aquí evitamos que el label
    # escuelita de un turno anterior quede pegado cuando el candidato corrige a un objetivo.
    # No detecta el "acto" de corregir por frase: solo reacciona a que ESTE turno confirma
    # full/sencillo (misma resolución que usa el extractor), sin duplicar la lógica LLM de
    # fact_corrections (shadow/multi-intent).
    veh = normalize_vehicle(message)
    if veh and veh.value:  # full | sencillo confirmados este turno
        signals = list(contract.get("business_signals") or [])
        if "considerar_escuelita_transmontes" in signals:
            updated = dict(contract)
            updated["business_signals"] = [
                s for s in signals if s != "considerar_escuelita_transmontes"
            ]
            updated["reason"] = "deterministic_clear_escuelita_on_target"
            return updated

    # B9 — costo al candidato / datos bancarios → respuesta controlada segura, sin pedir
    # datos sensibles ni perfilar. No es handoff: el bot aclara y sigue disponible.
    if _PAID_SENSITIVE_RE.search(text):
        updated = dict(contract)
        updated.update({
            "route": "profile",
            "intent": "sensitive_or_paid_request",
            "requires_human": False,
            "requires_rag": False,
            "requires_clarification": False,
            "reply_template": {"id": "sensitive_paid_guard", "text": _SENSITIVE_PAID_REPLY},
            "reason": "deterministic_sensitive_paid_guard",
        })
        return updated

    return contract


# Léxico de vigencia: el bot NUNCA emite "caduca/caducidad" al candidato; usa
# "vence/vencimiento/vigencia". Opera sobre el texto de salida (preserva mayúsculas/
# acentos), no sobre texto normalizado. Idempotente.
_CADUCIDAD_RE = re.compile(r"caducidad", re.IGNORECASE)
_CADUCADO_RE = re.compile(r"caducad([ao]s?)", re.IGNORECASE)
_CADUCA_RE = re.compile(r"caduca(n|r)?", re.IGNORECASE)


def _enforce_vigencia_lexicon(text: str) -> str:
    if not text:
        return text
    out = _CADUCIDAD_RE.sub("vigencia", text)
    out = _CADUCADO_RE.sub(lambda m: "vencid" + m.group(1), out)
    out = _CADUCA_RE.sub("vence", out)
    return out


def _is_safe_for_friendly_llm(message: str, contract: dict[str, Any]) -> bool:
    if contract.get("requires_human") or str(contract.get("risk_level") or "low") == "high":
        return False
    if _message_has_any(message, DISALLOWED_FREE_CHAT_TERMS):
        return False
    return True


def _should_use_friendly_llm(message: str, contract: dict[str, Any]) -> bool:
    if not _env_bool("KNOWLEDGE_FRIENDLY_LLM_ENABLED", True):
        return False
    if not _is_safe_for_friendly_llm(message, contract):
        return False

    route = str(contract.get("route") or "fallback")
    intent = str(contract.get("intent") or "unknown")
    if route == "friendly_smalltalk" or intent in {"friendly_smalltalk", "casual_recruiter_reply"}:
        return True
    if route == "fallback" and intent == "unknown":
        return True
    return False


def _format_lead_memory_for_prompt(memory: dict[str, Any] | None) -> str:
    if not memory:
        return "Sin memoria previa útil."
    lead = memory.get("lead") or {}
    facts = memory.get("facts") or []
    messages = memory.get("messages") or []

    fact_text = "; ".join(
        f"{row.get('fact_group')}.{row.get('fact_key')}={row.get('fact_value')}"
        for row in facts[:8]
        if isinstance(row, dict)
    ) or "Sin hechos activos."

    recent = []
    for row in messages[-4:]:
        if not isinstance(row, dict):
            continue
        role = "Candidato" if row.get("role") == "user" else "Asistente"
        msg = str(row.get("message") or "")[:180]
        recent.append(f"{role}: {msg}")

    # NO incluir next_best_action aquí: es una instrucción operativa para el
    # reclutador humano (ej. "invitar a enviar documentos"). El LLM la obedece
    # convirtiéndola en preguntas/peticiones. Solo contexto descriptivo.
    return (
        f"Etapa RH: {lead.get('funnel_stage_label') or lead.get('funnel_stage') or 'N/D'}. "
        f"Resumen: {lead.get('memory_summary') or 'N/D'}. "
        f"Hechos: {fact_text}. "
        f"Historial reciente: {' | '.join(recent) if recent else 'Sin historial previo útil.'}"
    )


def _is_strong_candidate(lead_memory: dict[str, Any] | None) -> bool:
    """True si el candidato ya tiene 3+ hechos clave de perfil registrados."""
    if not lead_memory:
        return False
    key_facts = {
        "candidate.city", "license.category", "license.status",
        "medical.apto_status", "experience.years", "experience.vehicle_type",
        "documents.labor_letters_status",
    }
    active = {
        f"{r.get('fact_group')}.{r.get('fact_key')}"
        for r in (lead_memory.get("facts") or [])
        if r.get("fact_value")
    }
    return len(active & key_facts) >= 3


# No-respuesta / espera del candidato: el bot responde neutral, NO llama al LLM y
# NO inventa facts ni elogia un perfil inexistente.
_NO_ANSWER_HINTS = (
    "ahorita le respondo", "ahorita respondo", "ahorita le paso", "ahorita le digo",
    "ahorita le contesto", "ahorita te digo", "ahorita te paso",
    "luego le digo", "luego le respondo", "luego le paso", "luego te digo",
    "al rato le digo", "al rato te digo", "mas tarde le digo",
    "espereme", "esperame", "pereme", "deme un momento", "deme chance",
    "deme un segundo", "espere un momento",
)
_FRIENDLY_NO_ANSWER_REPLY = "Claro, quedo al pendiente. Cuando pueda, me comparte el dato."
_FRIENDLY_NEUTRAL_REPLY = "Aquí andamos, con gusto seguimos con tu proceso."

# Cardinales (sin "un/uno/una", que son artículos comunes). Los dígitos se cubren aparte.
_NUMBER_WORDS = frozenset({
    "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez",
    "once", "doce", "trece", "catorce", "quince", "dieciseis", "diecisiete",
    "dieciocho", "diecinueve", "veinte", "treinta", "cuarenta", "cincuenta",
})


def _is_no_answer(message: str) -> bool:
    norm = normalize_text(message or "")
    return any(hint in norm for hint in _NO_ANSWER_HINTS)


def _text_has_number(text: str) -> bool:
    norm = normalize_text(text or "")
    if any(ch.isdigit() for ch in norm):
        return True
    return any(tok in _NUMBER_WORDS for tok in norm.split())


def _friendly_introduces_number(reply: str, message: str) -> bool:
    """True si la respuesta introduce una cifra/año que el candidato no dijo."""
    return _text_has_number(reply) and not _text_has_number(message)


def _answer_friendly_message(message: str, contract: dict[str, Any], lead_memory: dict[str, Any] | None = None) -> dict[str, Any]:
    started = time.perf_counter()

    # No-respuesta ("ahorita le respondo", "espéreme", "luego le digo"): respuesta
    # neutral sin LLM, para no fabricar experiencia ni elogiar un perfil inexistente.
    if _is_no_answer(message):
        return {
            "reply": _FRIENDLY_NO_ANSWER_REPLY,
            "llm_prompt_chars": 0,
            "llm_reply_chars": len(_FRIENDLY_NO_ANSWER_REPLY),
            "llm_cost_estimate": estimate_llm_cost("", _FRIENDLY_NO_ANSWER_REPLY),
            "timings": {"friendly_total_ms": round((time.perf_counter() - started) * 1000, 2), "friendly_generate_ms": 0.0},
            "friendly_generation_used": False,
            "friendly_generation_skipped_reason": "no_answer",
        }

    memory_text = _format_lead_memory_for_prompt(lead_memory)
    strong = _is_strong_candidate(lead_memory)

    tono_extra = (
        "Este candidato ya tiene buen perfil registrado. Cierra con algo breve y cálido, "
        "sin prometer contratación ni repetir frases que ya hayas dicho antes en este chat."
        if strong else
        "Responde corto y cordial."
    )

    prompt = f"""
Eres Mundo, del equipo de reclutamiento de Transmontes. Reclutador mexicano: directo, cálido, breve.

TU ÚNICO TRABAJO: hacer un comentario corto y amable. Confirmar, animar o reaccionar a lo que dijo el candidato. Nada más.

El sistema se encarga solo de pedir los datos del proceso. Tú JAMÁS pides datos ni haces preguntas: solo reaccionas con un comentario afirmativo y cierras.

Así suena bien (afirmaciones, nunca preguntas):
- Candidato: "me interesa la vacante" → "Qué bueno, aquí lo apoyamos para que avance."
- Candidato: "y cuánto lleva la empresa?" → "Transmontes tiene años en el transporte de carga."
- Candidato: "soy de Monterrey" → "Anotado, Monterrey."

NUNCA inventes ni menciones cifras, años, experiencia, documentos, licencia, ciudad, apto, unidad ni condiciones que el candidato no haya dicho en SU mensaje. Si el candidato no dio un dato, no lo asumas ni lo elogies.

Reglas: máximo 2 oraciones; nunca termines con '?'; no repitas lo que dijo el candidato; no prometas sueldo ni contratación; nada de "¡Genial!" ni "¡Excelente!" al inicio. {tono_extra}

Contexto del lead: {memory_text}
Mensaje del candidato: {message!r}

Tu comentario (afirmación corta, sin preguntas):
""".strip()

    if not _env_bool("KNOWLEDGE_FRIENDLY_LLM_GENERATION_ENABLED", True):
        debug_reply = "Aquí andamos, sin inventarte datos."
        return {
            "reply": debug_reply,
            "llm_prompt_chars": len(prompt),
            "llm_reply_chars": len(debug_reply),
            "llm_cost_estimate": estimate_llm_cost(prompt, debug_reply),
            "timings": {"friendly_total_ms": round((time.perf_counter() - started) * 1000, 2), "friendly_generate_ms": 0.0},
            "friendly_generation_used": False,
            "friendly_generation_skipped_reason": "generation_disabled",
        }

    gen_started = time.perf_counter()
    raw_reply = call_llm(prompt)
    generate_ms = round((time.perf_counter() - gen_started) * 1000, 2)
    reply = _clean_reply(raw_reply)

    if not reply:
        reply = _FRIENDLY_NEUTRAL_REPLY
    elif _friendly_introduces_number(reply, message):
        # El LLM introdujo una cifra/año que el candidato no dijo → descartar (anti-fabricación).
        reply = _FRIENDLY_NEUTRAL_REPLY

    return {
        "reply": reply,
        "llm_prompt_chars": len(prompt),
        "llm_reply_chars": len(reply),
        "llm_cost_estimate": estimate_llm_cost(prompt, reply),
        "timings": {"friendly_total_ms": round((time.perf_counter() - started) * 1000, 2), "friendly_generate_ms": generate_ms},
        "friendly_generation_used": True,
        "friendly_generation_skipped_reason": None,
    }


def _answer_objection_message(
    message: str,
    lead_memory: dict[str, Any] | None,
    field_label: str = "el documento",
) -> str:
    """Emite acuse empático ante negativa/alternativa de un campo del funnel (D3).

    Estructura: nombre de pila + validación empática + encuadre protocolo/expediente +
    desbloqueo "por lo pronto no se lo pedimos" + invitación a retomar.
    Copy generado por LLM bajo guardas deterministas; nunca inventa mínimos ni promete vacante.
    """
    from app.knowledge.current_turn import first_name

    facts: dict[str, Any] = {}
    if lead_memory:
        for row in (lead_memory.get("facts") or []):
            if row.get("fact_group") and row.get("fact_key") and row.get("fact_value"):
                facts[f"{row['fact_group']}.{row['fact_key']}"] = row["fact_value"]

    nombre = first_name(facts)
    vocativo = f"{nombre}, " if nombre else ""
    memory_text = _format_lead_memory_for_prompt(lead_memory) if lead_memory else "(sin datos previos)"

    prompt = f"""
Eres Mundo, del equipo de reclutamiento de Transmontes. Reclutador mexicano: directo, cálido, breve.

El candidato no cuenta (todavía) con {field_label} o propone una alternativa.
Tu tarea: responder con empatía usando EXACTAMENTE esta estructura (4 partes en 3-4 oraciones):
1. Valida empáticamente lo que el candidato dice o su situación.
2. Encuadra {field_label} como parte del protocolo de su expediente (no como un rechazo).
3. Aclara que por lo pronto no se lo pedimos como condición para continuar.
4. Invita a retomar en cuanto lo tenga o resuelva su situación.

Reglas:
- Si el nombre de pila es "{nombre}", úsalo naturalmente (p.ej. "{vocativo}lo anotamos...").
- Si no hay nombre disponible, omite el vocativo; no uses placeholders como "[nombre]".
- NUNCA inventes mínimos de años, sueldos, ni condiciones que no se hayan mencionado.
- NUNCA prometas la vacante ni uses "Capital Humano" como tercero; usa "nuestro equipo".
- Máximo 3 oraciones. Sin preguntas al final.

Contexto del lead: {memory_text}
Mensaje del candidato: {message!r}
Campo del funnel involucrado: {field_label}

Tu acuse empático (3 oraciones, sin pregunta final):
""".strip()

    if not _env_bool("KNOWLEDGE_FRIENDLY_LLM_GENERATION_ENABLED", True):
        return f"{vocativo}lo anotamos. Cuando cuente con {field_label}, con gusto lo retomamos."

    raw = call_llm(prompt)
    reply = _clean_reply(raw)
    if not reply:
        reply = f"{vocativo}lo anotamos. En cuanto lo tenga, nuestro equipo lo retoma sin problema."
    return reply


def _answer_rag_message(message: str, contract: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    rag_enabled = _env_bool("KNOWLEDGE_RAG_GENERATION_ENABLED", True)

    context = retrieve_preferred_context(message, preferred_sources=contract.get("preferred_sources") or [])

    if not context.get("items"):
        return {
            "reply": NO_CONTEXT_REPLY,
            "rag_context": context,
            "llm_prompt_chars": 0,
            "llm_reply_chars": len(NO_CONTEXT_REPLY),
            "llm_cost_estimate": estimate_llm_cost("", NO_CONTEXT_REPLY),
            "timings": {"rag_total_ms": round((time.perf_counter() - started) * 1000, 2), "retrieve_context_ms": context.get("timing_ms"), "generate_answer_ms": 0.0},
            "rag_generation_used": False,
            "rag_generation_skipped_reason": context.get("error") or "no_relevant_context",
        }

    prompt = build_generation_prompt(
        message=message,
        knowledge_contract=contract,
        context_text=context.get("context_text") or "",
    )

    if not rag_enabled:
        debug_reply = "RAG detectado y contexto interno recuperado, pero la generación LLM está desactivada por KNOWLEDGE_RAG_GENERATION_ENABLED=false."
        return {
            "reply": debug_reply,
            "rag_context": context,
            "llm_prompt_chars": len(prompt),
            "llm_reply_chars": len(debug_reply),
            "llm_cost_estimate": estimate_llm_cost(prompt, debug_reply),
            "timings": {"rag_total_ms": round((time.perf_counter() - started) * 1000, 2), "retrieve_context_ms": context.get("timing_ms"), "generate_answer_ms": 0.0},
            "rag_generation_used": False,
            "rag_generation_skipped_reason": "generation_disabled",
        }

    gen_started = time.perf_counter()
    raw_reply = call_llm(prompt)
    generate_ms = round((time.perf_counter() - gen_started) * 1000, 2)
    reply = _clean_reply(raw_reply)

    return {
        "reply": reply,
        "rag_context": context,
        "llm_prompt_chars": len(prompt),
        "llm_reply_chars": len(reply),
        "llm_cost_estimate": estimate_llm_cost(prompt, reply),
        "timings": {"rag_total_ms": round((time.perf_counter() - started) * 1000, 2), "retrieve_context_ms": context.get("timing_ms"), "generate_answer_ms": generate_ms},
        "rag_generation_used": True,
        "rag_generation_skipped_reason": None,
    }


def _stage_for_contract(contract: dict[str, Any], message: str) -> str:
    intent = str(contract.get("intent") or "unknown")
    route = str(contract.get("route") or "fallback")
    text = normalize_text(message)

    try:
        from app.settings import AGE_DISQUALIFICATION_LIMIT
        from app.lead_memory.profile_extractor import extract_profile_facts_as_dict
        age = int(str(extract_profile_facts_as_dict(message).get("candidate.age") or "").strip())
        if age >= AGE_DISQUALIFICATION_LIMIT:
            return "closed"
    except Exception:
        pass

    if contract.get("requires_human"):
        return "human_review"
    if intent == "farewell" or route == "candidate_dropoff_recovery" or intent == "candidate_dropoff_risk":
        return "followup_pending"
    if intent == "document_submission_ack":
        return "documents_received"
    if intent == "requirements_documents":
        if "apto" in text and any(term in text for term in ("vence", "vencer", "venc", "renovar", "actualizo", "actualizar")):
            return "apto_pending_update"
        return "documents_pending"
    if intent in {"payment_compensation", "bases_routes_rest"}:
        return "vacancy_info_shared"
    if intent in {"driving_school", "on_route_safety", "callback_request"}:
        return "profile_hint_collected"
    if intent == "drug_testing_urine":
        return "safety_review"
    if intent in {"friendly_smalltalk", "local_time", "greeting"}:
        return "interested"
    return "interested" if route == "friendly_smalltalk" else "new"


def _next_action_for_stage(stage: str, contract: dict[str, Any]) -> str | None:
    intent = str(contract.get("intent") or "unknown")
    if stage == "closed":
        return "Cierre automático: edad fuera de perfil."
    if stage == "apto_pending_update":
        return "Dar seguimiento cuando el candidato actualice apto médico."
    if stage == "documents_pending":
        return "Invitar al candidato a enviar documentos cuando tenga oportunidad, sin presionarlo."
    if stage == "documents_received":
        return "Nuestro equipo debe validar documentos recibidos."
    if stage == "followup_pending":
        return "Mantener seguimiento abierto para retomar conversación."
    if stage == "safety_review":
        return "Responder con política interna y validar con el equipo si escala."
    if intent == "payment_compensation":
        return "Resolver dudas de pago/ruta y luego avanzar suavemente a documentos."
    return None


# B10 — decisión operativa unificada. La verdad del turno es lo que se REGISTRÓ
# (`facts_written`), no el intent tópico (que puede venir mal clasificado para una
# respuesta corta tipo "5"). Estos helpers alinean nota/labels/acción con lo registrado.
_CORE_PROFILE_FACT_KEYS: dict[str, str] = {
    "candidate.city":          "El candidato registró su ciudad.",
    "candidate.age":           "El candidato registró su edad.",
    "experience.vehicle_type": "El candidato registró su tipo de unidad (tracto full o sencillo).",
    "experience.years":        "El candidato registró sus años de experiencia.",
    "license.category":        "El candidato registró su licencia.",
    "medical.apto_status":     "El candidato registró su apto médico.",
}


def _core_fact_written(facts_written: list[str] | None) -> bool:
    return any(k in _CORE_PROFILE_FACT_KEYS for k in (facts_written or []))


def _registered_fact_summary(facts_written: list[str] | None) -> str | None:
    """Resumen de memoria basado en el dato núcleo registrado este turno (en orden)."""
    for key in facts_written or []:
        if key in _CORE_PROFILE_FACT_KEYS:
            return _CORE_PROFILE_FACT_KEYS[key]
    return None


def _should_record_topical_interest(intent: str, facts_written: list[str] | None) -> bool:
    """Una pregunta tópica (pago/documentos) NO se registra como interés cuando el turno ya
    registró un dato núcleo del perfil: el mensaje fue una respuesta al funnel, no una
    pregunta. Evita que nota/labels digan "preguntó por documentos" tras un "5" (B10)."""
    return not _core_fact_written(facts_written)


def _memory_summary_for_stage(stage: str, message: str, contract: dict[str, Any]) -> str | None:
    intent = str(contract.get("intent") or "unknown")
    if stage == "apto_pending_update":
        return "El candidato mencionó que su apto médico está vencido o próximo a vencer."
    if stage == "documents_received":
        return "El candidato indicó que ya envió documentos o información para el proceso."
    if intent == "payment_compensation":
        return "El candidato preguntó por pago/compensación."
    if intent == "requirements_documents":
        return "El candidato preguntó por documentos o requisitos."
    if intent == "farewell":
        return "El candidato se despidió cordialmente; seguimiento queda abierto."
    return None


def _store_lead_memory_updates(
    *,
    lead_key: str,
    conversation_key: str,
    message: str,
    contract: dict[str, Any],
    stage_from: str | None,
    stage_to: str,
    reply: str,
    asked_field_keys: list[str] | None = None,
    turn_signals=None,
    pre_validated_facts: list | None = None,
) -> dict[str, Any]:
    """Write useful memory to v2 without letting it govern the conversation."""
    facts_written: list[str] = []
    text = normalize_text(message)
    intent = str(contract.get("intent") or "unknown")
    route = str(contract.get("route") or "fallback")

    source_msg = save_lead_message(
        lead_key=lead_key,
        conversation_key=conversation_key,
        role="user",
        message=message,
    )
    source_message_id = source_msg.get("id") if source_msg else None

    # Passive capture: record which canonical field(s) the funnel just asked.
    # Only when a nudge with reliable canonical keys was emitted; otherwise no
    # metadata is written (no inference, no legacy/canonical mixing).
    assistant_metadata: dict[str, Any] = {}
    if asked_field_keys:
        assistant_metadata = {
            "asked_field_keys": list(asked_field_keys),
            "asked_field_source": "funnel_nudge",
            "asked_field_key_space": "canonical",
        }

    save_lead_message(
        lead_key=lead_key,
        conversation_key=conversation_key,
        role="assistant",
        message=reply,
        external_metadata=assistant_metadata or None,
    )

    # 6.2: extractor unificado pre-computado en el worker → un solo escritor por turno.
    # Fallback al path anterior (neo4j + regex) solo para el path API sin pre_validated.
    if pre_validated_facts is not None:
        for pf in pre_validated_facts:
            try:
                _fval = str(pf["fact_value"])
                # Canonicaliza documents.proof en el límite de persistencia (todas
                # las rutas): el contrato es {cartas|semanas_imss|ninguno}.
                if pf["fact_group"] == "documents" and pf["fact_key"] == "proof":
                    from app.knowledge.current_turn import canonicalize_proof
                    _canon = canonicalize_proof(_fval)
                    if _canon is None:
                        continue  # no mapeable → no persistir texto crudo
                    _fval = _canon
                upsert_lead_fact(
                    lead_key=lead_key,
                    fact_group=pf["fact_group"],
                    fact_key=pf["fact_key"],
                    fact_value=_fval,
                    confidence=float(pf.get("confidence") or 0.8),
                    source_message_id=source_message_id,
                    source_text=message,
                    is_explicit_correction=bool(pf.get("is_explicit_correction", False)),
                )
                facts_written.append(f"{pf['fact_group']}.{pf['fact_key']}")
            except Exception as exc:
                log.warning("[FACTS_WRITE] lead=%s key=%s.%s error=%s",
                            lead_key, pf.get("fact_group"), pf.get("fact_key"), exc)
    else:
        try:
            from app.knowledge.neo4j_client import extract_profile_facts_from_neo4j
            from app.lead_memory.profile_extractor import extract_profile_facts

            neo4j_facts = _drop_unanchored_neo4j_geo(extract_profile_facts_from_neo4j(message), message)
            neo4j_keys = {(f["fact_group"], f["fact_key"]) for f in neo4j_facts}
            regex_facts = [
                f for f in extract_profile_facts(message, intent, turn_signals=turn_signals)
                if (f["fact_group"], f["fact_key"]) not in neo4j_keys
            ]
            for pf in _drop_geo_facts_from_questions(neo4j_facts + regex_facts, message):
                upsert_lead_fact(
                    lead_key=lead_key,
                    fact_group=pf["fact_group"],
                    fact_key=pf["fact_key"],
                    fact_value=str(pf["fact_value"]),
                    confidence=float(pf.get("confidence") or 0.8),
                    source_message_id=source_message_id,
                    source_text=message,
                )
                facts_written.append(f"{pf['fact_group']}.{pf['fact_key']}")
        except Exception as exc:
            log.warning("[FACTS_EXTRACTION] lead=%s error=%s", lead_key, exc)

    if any(term in text for term in ("quinta rueda", "5ta rueda", "5ta", "kinta rueda")):
        upsert_lead_fact(
            lead_key=lead_key,
            fact_group="role_fit",
            fact_key="operator_type",
            fact_value="operador_5ta_rueda",
            confidence=0.90,
            source_message_id=source_message_id,
            source_text=message,
        )
        facts_written.append("role_fit.operator_type")

    if "apto" in text and any(term in text for term in ("vence", "vencer", "venc", "vencido", "renovar", "actualizar", "dos meses", "2 meses")):
        value = "expires_in_2_months" if any(term in text for term in ("2 meses", "dos meses")) else "pending_update"
        upsert_lead_fact(
            lead_key=lead_key,
            fact_group="document",
            fact_key="apto_status",
            fact_value=value,
            confidence=0.90,
            source_message_id=source_message_id,
            source_text=message,
        )
        facts_written.append("document.apto_status")

    if intent == "document_submission_ack":
        upsert_lead_fact(
            lead_key=lead_key,
            fact_group="documents",
            fact_key="submission_status",
            fact_value="candidate_says_sent",
            confidence=0.85,
            source_message_id=source_message_id,
            source_text=message,
        )
        facts_written.append("documents.submission_status")

    if intent == "payment_compensation" and _should_record_topical_interest(intent, facts_written):
        upsert_lead_fact(
            lead_key=lead_key,
            fact_group="interest",
            fact_key="payment",
            fact_value="asked",
            confidence=0.80,
            source_message_id=source_message_id,
            source_text=message,
        )
        facts_written.append("interest.payment")

    if intent == "requirements_documents" and _should_record_topical_interest(intent, facts_written):
        upsert_lead_fact(
            lead_key=lead_key,
            fact_group="interest",
            fact_key="requirements_documents",
            fact_value="asked",
            confidence=0.80,
            source_message_id=source_message_id,
            source_text=message,
        )
        facts_written.append("interest.requirements_documents")

    event_type = f"intent_{intent}" if intent and intent != "unknown" else "message_processed"
    log_lead_event(
        lead_key=lead_key,
        conversation_key=conversation_key,
        event_type=event_type,
        intent=intent,
        route=route,
        stage_from=stage_from,
        stage_to=stage_to,
        risk_level=str(contract.get("risk_level") or "low"),
        requires_human=bool(contract.get("requires_human")),
        metadata={
            "reason": contract.get("reason"),
            "recognized_terms": contract.get("recognized_terms"),
            "matched_aliases": contract.get("matched_aliases"),
            "facts_written": facts_written,
        },
    )

    update_lead_summary(
        lead_key=lead_key,
        funnel_stage=stage_to,
        next_best_action=_next_action_for_stage(stage_to, contract),
        memory_summary=(
            _registered_fact_summary(facts_written)
            or _memory_summary_for_stage(stage_to, message, contract)
        ),
        facts_summary={"last_intent": intent, "last_route": route, "last_stage": stage_to},
        risk_level=str(contract.get("risk_level") or "low"),
        requires_human=bool(contract.get("requires_human")),
    )

    memory = get_lead_memory(lead_key=lead_key)
    return {"facts_written": facts_written, "memory": memory}


# ---------------------------------------------------------------------------
# Profile acknowledgment — deterministic reply for explicit candidate data.
# No LLM. Reads extracted facts and builds a natural confirmation.
# ---------------------------------------------------------------------------

_ACK_INTROS = [
    "Perfecto, registro que",
    "Anotado,",
    "Registrado,",
    "Queda anotado:",
]


def _build_profile_ack_reply(message: str) -> str | None:
    """Build a short confirmation from facts explicitly stated in the message.

    Returns None when the extractor finds nothing recognizable, letting the
    caller fall through to whatever reply is appropriate.
    """
    try:
        from app.lead_memory.profile_extractor import extract_profile_facts
        raw = extract_profile_facts(message)
    except Exception:
        return None

    if not raw:
        return None

    by_key = {f"{f['fact_group']}.{f['fact_key']}": f["fact_value"] for f in raw}
    try:
        from app.settings import AGE_DISQUALIFICATION_LIMIT
        from app.knowledge.current_turn import age_disqualification_reply, _to_int
        age_val = int(str(by_key.get("candidate.age") or "").strip())
        if age_val >= AGE_DISQUALIFICATION_LIMIT:
            return age_disqualification_reply(age_val)
    except (ValueError, ImportError):
        pass

    parts: list[str] = []

    # City
    city = by_key.get("candidate.city")
    if city:
        parts.append(f"reside en {city}")

    # License — merge category + validity into one phrase when both present
    lic_cat = by_key.get("license.category")
    lic_st = by_key.get("license.status")
    if lic_cat and lic_st in {"vigente", "sí", "si"}:
        parts.append(f"licencia federal tipo {lic_cat} vigente")
    elif lic_cat:
        parts.append(f"licencia federal tipo {lic_cat}")
    elif lic_st in {"vigente", "sí", "si"}:
        parts.append("licencia federal vigente")

    # Apto médico
    apto = by_key.get("medical.apto_status") or by_key.get("document.apto_status")
    if apto in {"vigente", "sí", "si"}:
        parts.append("apto médico vigente")

    # Experience — vehicle_type + years
    years = by_key.get("experience.years")
    vt    = by_key.get("experience.vehicle_type")
    vt_label = {"full": "tracto full", "sencillo": "sencillo"}.get(vt or "", vt or "")
    if years and vt_label:
        parts.append(f"{years} de experiencia en {vt_label}")
    elif years:
        parts.append(f"{years} de experiencia")
    elif vt_label:
        parts.append(f"experiencia en {vt_label}")

    # Labor letters
    labor = by_key.get("documents.labor_letters_status") or by_key.get("documents.labor_letters")
    if labor in {"available", "sí", "si"}:
        parts.append("cartas laborales disponibles")

    # Age (mention only when accompanied by other facts to avoid bare "X años")
    age = by_key.get("candidate.age")
    if age and len(parts) >= 1:
        parts.append(f"{age} años de edad")

    if not parts:
        return None

    intro = random.choice(_ACK_INTROS)
    if len(parts) == 1:
        return f"{intro} {parts[0]}."
    if len(parts) == 2:
        return f"{intro} {parts[0]} y {parts[1]}."
    listed = ", ".join(parts[:-1]) + f" y {parts[-1]}"
    return f"{intro} {listed}."


# ---------------------------------------------------------------------------
# Funnel nudge — one profiling question appended after RAG/friendly answers.
# Order follows the linear recruiting flow. Variants avoid repetition.
# ---------------------------------------------------------------------------

_FUNNEL_STEPS: list[dict] = [
    {
        "keys": {"candidate.name"},
        "variants": [
            "¿Me podría decir su nombre y apellido, por favor?",
            "Para continuar, ¿cuál es su nombre?",
            "¿Cómo se llama usted, por favor?",
        ],
    },
    {
        "keys": {"candidate.city"},
        "variants": [
            "Para su registro, ¿desde qué ciudad o estado nos escribe?",
            "Para continuar con su perfil, ¿en qué ciudad o estado se encuentra?",
            "¿Me puede decir en qué ciudad vive para seguir con su proceso?",
        ],
    },
    {
        "keys": {"candidate.age"},
        "variants": [
            "Para continuar con su perfil, ¿cuántos años tiene?",
            "¿Me puede compartir su edad para seguir con el registro?",
            "¿Cuántos años tiene actualmente?",
        ],
    },
    {
        "keys": {"experience.vehicle_type"},
        "variants": [
            "¿Su experiencia es en tracto full o en sencillo?",
            "¿Maneja tracto full o sencillo?",
            "¿Cuál es su tipo de unidad, tracto full o sencillo?",
        ],
    },
    {
        "keys": {"license.category"},
        "variants": [
            "¿Qué tipo de licencia federal tiene (A, B o E) y cuándo vence?",
            "Para su perfil, ¿su licencia federal es tipo A, B o E, y cuándo vence?",
            "¿Qué tipo de licencia federal tiene y cuándo le vence?",
        ],
    },
    {
        "keys": {"license.expiration_text"},
        "variants": [
            "¿En cuánto tiempo se le vence su licencia federal?",
            "¿Cuándo vence su licencia federal?",
            "¿Qué vigencia le queda a su licencia federal?",
        ],
    },
    {
        "keys": {"medical.apto_expiration_text"},
        "variants": [
            "¿Cuándo vence su apto médico?",
            "Para continuar, ¿en cuánto tiempo se le vence su apto médico?",
            "¿Qué fecha de vencimiento tiene su apto médico?",
        ],
    },
    {
        "keys": {"experience.years"},
        "variants": [
            "¿Cuántos años tiene de experiencia como operador?",
            "¿Cuánto tiempo tiene de experiencia al volante?",
        ],
    },
    {
        "keys": {"documents.labor_letters_status"},
        "variants": [
            "¿Cuenta con cartas laborales de empleos anteriores?",
            "Para el proceso, ¿tiene cartas laborales disponibles?",
            "¿Sus cartas laborales están disponibles para cuando avancemos?",
        ],
    },
]

_NUDGE_SKIP_INTENTS = frozenset({
    "farewell",
    "greeting",
    "sensitive_handoff",
    "rcontrol_or_incident_handoff",
    "candidate_dropoff_risk",
    "document_submission_ack",
    "local_time",
})

_NUDGE_SKIP_ROUTES = frozenset({
    "human_handoff",
    "policy_boundary",
    "clarification",
    "candidate_dropoff_recovery",
})

_NO_FUNNEL_SIGNALS = frozenset({
    "cecati_sugerido",
    "considerar_escuelita_transmontes",
})

# Mapa funnel(legacy) -> espacio canónico. Solo claves con mapeo canónico
# confiable. Si una clave del step NO está aquí, el step no se registra
# (no inventar, no mezclar legacy/canonical, no inferir desde texto).
_FUNNEL_KEY_CANONICAL: dict[str, str] = {
    "candidate.city": "candidate.city",
    "candidate.age": "candidate.age",
    "license.category": "license.type",
    "license.expiration_text": "license.expiration_text",
    "medical.apto_status": "medical.apto_status",
    "medical.apto_expiration_text": "medical.apto_expiration_text",
    "experience.years": "experience.years",
    "experience.vehicle_type": "experience.vehicle_type",
    "documents.labor_letters_status": "documents.proof",
    # license.status (vigencia) se omite a propósito: es advisory (2C.0d) y no
    # tiene campo canónico de perfil; su step no se registra como asked_field.
}


def _canonical_asked_keys(step_keys: set[str]) -> list[str]:
    """Mapea las keys del step funnel al espacio canónico.

    Devuelve ``[]`` si alguna clave del step no es mapeable de forma confiable,
    para no mezclar legacy/canonical ni registrar campos dudosos. Todo o nada.
    """
    if not step_keys:
        return []
    mapped: list[str] = []
    for key in sorted(step_keys):
        canonical = _FUNNEL_KEY_CANONICAL.get(key)
        if not canonical:
            return []  # clave no confiable/mapeable → no registrar el step
        mapped.append(canonical)
    return sorted(set(mapped))


def _build_funnel_nudge(
    message: str,
    contract: dict[str, Any],
    lead_memory: dict[str, Any],
    turn_signals=None,
    pre_validated_facts: list | None = None,
) -> tuple[str | None, list[str]]:
    """Return ``(question, asked_field_keys)`` for the next profiling step.

    ``asked_field_keys`` holds the canonical/reliable key(s) of the field(s)
    the funnel is asking about (e.g. ``["license.type"]``), so the assistant
    message can record which field(s) were asked. Keys are never inferred from
    text. If the step's keys are not reliable or cannot be mapped to the
    canonical space, ``asked_field_keys`` is ``[]`` and nothing is recorded.
    When no nudge is appropriate the tuple is ``(None, [])``.
    """
    intent = str(contract.get("intent") or "")
    route = str(contract.get("route") or "")

    if intent in _NUDGE_SKIP_INTENTS or route in _NUDGE_SKIP_ROUTES:
        return None, []
    if _NO_FUNNEL_SIGNALS & set(contract.get("business_signals") or []):
        return None, []
    if contract.get("requires_human"):
        return None, []

    # Merge persisted facts with facts explicitly stated in the current message
    # so we never ask something the candidate just answered.
    # get_lead_memory returns {"facts": [{"fact_group":..., "fact_key":..., ...}]}
    active_facts: dict[str, str] = {
        f"{row['fact_group']}.{row['fact_key']}": str(row["fact_value"])
        for row in (lead_memory.get("facts") or [])
        if row.get("fact_group") and row.get("fact_key") and row.get("fact_value")
    }
    if pre_validated_facts is not None:
        # 6.2: usar extractor unificado pre-computado en lugar de re-extraer
        for f in pre_validated_facts:
            k = f"{f['fact_group']}.{f['fact_key']}"
            active_facts[k] = str(f["fact_value"])
    else:
        try:
            from app.knowledge.neo4j_client import extract_profile_facts_from_neo4j
            from app.lead_memory.profile_extractor import extract_profile_facts

            neo4j_facts = extract_profile_facts_from_neo4j(message)
            neo4j_keys: set[str] = set()
            for f in neo4j_facts:
                k = f"{f['fact_group']}.{f['fact_key']}"
                active_facts[k] = str(f["fact_value"])
                neo4j_keys.add(k)
            for f in extract_profile_facts(message, intent or None, turn_signals=turn_signals):
                k = f"{f['fact_group']}.{f['fact_key']}"
                if k not in neo4j_keys:
                    active_facts[k] = str(f["fact_value"])
        except Exception as exc:
            log.warning("[FUNNEL_NUDGE] extracción de hechos falló, nudge puede ser impreciso: %s", exc)

    # 3.3: vencido sin trámite → no emitir más nudges
    if active_facts.get("funnel.status") == "vencido_sin_tramite":
        return None, []

    try:
        from app.settings import AGE_DISQUALIFICATION_LIMIT
        age = int(str(active_facts.get("candidate.age") or "").strip())
        if age >= AGE_DISQUALIFICATION_LIMIT:
            return None, []
    except (ValueError, ImportError):
        pass

    from app.knowledge.current_turn import residency_document_question

    # Leer último mensaje del bot (necesario para BUG-2 y BUG-3)
    _last_bot = ""
    for _m in reversed(lead_memory.get("messages") or []):
        if isinstance(_m, dict) and _m.get("role") == "assistant":
            _last_bot = normalize_text(str(_m.get("message") or ""))
            break
    _msg_norm = normalize_text(message)
    _lead_key = (lead_memory.get("lead") or {}).get("lead_key") or ""

    # BUG-2: bare negation ("No") como respuesta a pregunta de cartas → marcar proof=ninguno
    _bare_neg = _msg_norm in {"no", "nop", "nel", "nope", "para nada", "tampoco", "negativo", "no tengo"}
    _last_asks_cartas = any(t in _last_bot for t in ("cartas", "membretadas", "documentos laborales", "documento laboral"))
    if _bare_neg and _last_asks_cartas and "documents.proof" not in active_facts:
        active_facts["documents.proof"] = "ninguno"
        try:
            upsert_lead_fact(lead_key=_lead_key, fact_group="documents", fact_key="proof",
                             fact_value="ninguno", confidence=0.80, source="bare_negation_context",
                             source_text=message[:200])
        except Exception:
            pass

    # BUG-3: "igual / los dos / al mismo tiempo" tras pregunta de apto → heredar vencimiento de licencia
    _last_asks_apto = "apto" in _last_bot and ("vence" in _last_bot or "vigencia" in _last_bot)
    _same_hints = ("igual", "mismo", "los dos", "ambos", "los 2", "tambien", "también",
                   "al mismo tiempo", "igual que", "igualmente")
    _says_same = any(h in _msg_norm for h in _same_hints)
    if _last_asks_apto and _says_same and "medical.apto_expiration_text" not in active_facts:
        _lic_exp = active_facts.get("license.expiration_text")
        if _lic_exp:
            active_facts["medical.apto_expiration_text"] = _lic_exp
            try:
                upsert_lead_fact(lead_key=_lead_key, fact_group="medical", fact_key="apto_expiration_text",
                                 fact_value=_lic_exp, confidence=0.85, source="same_as_license_context",
                                 source_text=message[:200])
            except Exception:
                pass

    for step in _FUNNEL_STEPS:
        if not any(k not in active_facts for k in step["keys"]):
            continue
        # 2.4: vehicle_type conditioned on license category if already known
        if step["keys"] == {"experience.vehicle_type"}:
            cat = (active_facts.get("license.category") or "").upper()
            if cat == "B":
                return (
                    "Con licencia tipo B la vacante disponible es de sencillo. "
                    "¿Le interesa una vacante de operador sencillo?",
                    _canonical_asked_keys(step["keys"]),
                )
            elif cat == "E":
                return (
                    "¿Le interesa una vacante de tracto full o de sencillo?",
                    _canonical_asked_keys(step["keys"]),
                )
        # 2.5 / P0-2: document question by residency; skip if candidate already answered
        if step["keys"] == {"documents.labor_letters_status"}:
            _proof = active_facts.get("documents.proof")
            # Si ya hay un proof positivo el paso está resuelto → no nudge
            if _proof in {"cartas", "semanas_imss", "sí", "si"}:
                continue
            # Regla de dominio única (residencia desde catálogo, incl. proof=ninguno)
            return (
                residency_document_question(active_facts),
                _canonical_asked_keys(step["keys"]),
            )
        return random.choice(step["variants"]), _canonical_asked_keys(step["keys"])

    return None, []  # All profile fields covered — no nudge needed


def _maybe_save_call_preference(
    *,
    message: str,
    lead_key: str,
    lead_memory: dict[str, Any],
    lead_stage_to: str,
) -> None:
    """Guarda nota de horario preferido si el candidato está respondiendo una solicitud de llamada."""
    if lead_stage_to not in {"profile_ready", "human_review", "followup_pending"}:
        return

    text = normalize_text(message)
    # Mensaje debe tener algún indicador de horario o aceptación
    has_time = any(hint in text for hint in _CALL_TIME_HINTS)
    has_accept = any(hint in text for hint in _CALL_ACCEPT_HINTS)
    if not (has_time or has_accept):
        return

    if not _pending_call_request(lead_key):
        return

    _save_call_preference_note(
        lead_key=lead_key,
        message=message,
        lead_memory=lead_memory,
    )


def handle_message(payload: dict[str, Any]) -> dict[str, Any]:
    """Resolve a candidate message through Neo4j and optionally answer with controlled RAG."""
    # [NOTA] Esta función tiene ~240 líneas y 6 responsabilidades distintas:
    #   1. Persistencia de conversación (upsert_conversation, get_conversation_state)
    #   2. Persistencia de lead (upsert_lead_identity, get_lead_memory)
    #   3. Resolución Neo4j + guardas deterministas (resolve_message + overrides)
    #   4. Generación de respuesta (RAG / friendly LLM / template / ACK)
    #   5. Escritura de memoria (stage, facts, events, summary)
    #   6. Construcción del payload de respuesta
    #
    # [RIESGO] Abre ~10 conexiones TCP a Postgres en serie por mensaje:
    #   upsert_conversation → get_conversation_state → upsert_lead_identity →
    #   get_lead_memory → save_message → (facts: N × upsert_lead_fact) →
    #   log_lead_event → update_lead_summary → get_lead_memory → update_stage →
    #   save_message (assistant). Cada una abre y cierra su propia conexión TCP.
    #   Con pool esto costaría 0 overhead adicional.
    #
    # [MEJORA - largo plazo] Separar en 3 módulos cuando se retome la migración LangGraph:
    #   - conversation_writer.py  → responsabilidades 1 y 2
    #   - answer_builder.py       → responsabilidad 4
    #   - memory_writer.py        → responsabilidad 5
    # No hacer ahora — el sistema funciona y el cambio es arquitectónico.
    # Registrado como deuda técnica para la rama migration/langgraph-step2.
    started = time.perf_counter()
    channel = str(payload.get("channel") or "api").strip()
    channel_user_id = str(payload.get("channel_user_id") or "unknown").strip()
    username = payload.get("username")
    phone = payload.get("phone")
    message = str(payload.get("message") or "").strip()

    identity = upsert_conversation(channel=channel, channel_user_id=channel_user_id, username=username, phone=phone)
    conversation_key = identity.get("conversation_key") or make_conversation_key(channel, channel_user_id)
    state = get_conversation_state(conversation_key)
    conversation = state.get("conversation") or {}

    lead_identity = upsert_lead_identity(
        channel=channel,
        channel_user_id=channel_user_id,
        username=username,
        phone=phone,
        chatwoot_account_id=payload.get("account_id"),
        chatwoot_inbox_id=payload.get("chatwoot_inbox_id") or payload.get("inbox_id"),
        chatwoot_conversation_id=payload.get("chatwoot_conversation_id"),
        chatwoot_contact_id=payload.get("chatwoot_contact_id"),
        external_metadata={"source": "knowledge_orchestrator"},
    )
    lead_key = lead_identity["lead_key"]
    lead_memory_before = get_lead_memory(lead_key=lead_key)
    lead_stage_from = (lead_memory_before.get("lead") or {}).get("funnel_stage")

    save_message(conversation_key, "user", message)

    # 6.4: si el worker pre-computó la extracción unificada, sus señales reemplazan TIPC.
    _pre_extraction = payload.get("_pre_extraction")
    _pre_validated: list | None = payload.get("_pre_validated")
    from app.knowledge.turn_intent_classifier import TurnIntentSignals, classify_turn_intent
    if _pre_extraction is not None:
        turn_signals = _pre_extraction.signals
    else:
        try:
            turn_signals = classify_turn_intent(message)
        except Exception:
            turn_signals = TurnIntentSignals()

    contract = resolve_message(message, conversation_state=conversation)
    contract = _apply_profile_guards(message, contract)
    contract = _apply_deterministic_overrides(message, contract)
    contract = _apply_business_rule_overrides(message, contract, turn_signals=turn_signals)

    # ── 5a: Pre-handoff condicional ───────────────────────────────────────────
    # Antes de canalizar a Capital Humano, el bot verifica el dato mínimo que
    # determina si el candidato es viable en su categoría.
    _prehandoff_facts: dict[str, str] = {
        f"{r['fact_group']}.{r['fact_key']}": str(r["fact_value"])
        for r in (lead_memory_before.get("facts") or []) if r.get("fact_value")
    }
    _intent_now = str(contract.get("intent") or "")
    _lic_now = (_prehandoff_facts.get("license.category") or "").upper()
    _has_be = _lic_now in {"B", "E"}
    _has_tramite = (
        _prehandoff_facts.get("license.tramite_comprobante") == "true"
        or _prehandoff_facts.get("medical.tramite_comprobante") == "true"
    )

    # 5a.1/5a.2: escuelita / CECATI — verificar licencia B/E antes de canalizar
    if _intent_now in {"considerar_escuelita_transmontes", "cecati_sugerido"}:
        if _has_be or _has_tramite:
            _esc_acuse = (
                f"Gracias por compartir su experiencia. Con licencia tipo {_lic_now}, "
                "nuestro equipo revisará si hay generación disponible para Escuelita Transmontes. "
                "Lo dejo canalizado para que lo contacten."
            )
            contract = dict(contract)
            contract["reply_template"] = {"id": "escuelita_handoff_con_licencia", "text": _esc_acuse}
        else:
            # Sin licencia B/E confirmada → preguntar antes de canalizar
            contract = dict(contract)
            contract.update({
                "requires_human": False,
                "reply_template": {
                    "id": "escuelita_prehandoff_licencia",
                    "text": (
                        "Para considerar su candidatura, necesitamos saber si cuenta con "
                        "licencia federal tipo B o E vigente (o comprobante de renovación). "
                        "¿Tiene licencia federal B o E?"
                    ),
                },
                "reason": "escuelita_prehandoff_verificar_licencia",
            })

    # 5a.3: B1/EUA — verificar unidad, licencia y apto antes de canalizar
    elif _intent_now == "business_route_us":
        _vt = _prehandoff_facts.get("experience.vehicle_type", "")
        _has_lic_exp = bool(_prehandoff_facts.get("license.expiration_text"))
        _has_apto_exp = bool(_prehandoff_facts.get("medical.apto_expiration_text"))
        if not _vt:
            contract = dict(contract)
            contract.update({
                "requires_human": False,
                "reply_template": {
                    "id": "b1_prehandoff_unidad",
                    "text": "Para las vacantes con ruta B1/EUA, ¿su experiencia es en tracto full o sencillo?",
                },
                "reason": "b1_prehandoff_verificar_unidad",
            })
        elif not (_has_be and _has_lic_exp and _has_apto_exp):
            contract = dict(contract)
            contract.update({
                "requires_human": False,
                "reply_template": {
                    "id": "b1_prehandoff_docs",
                    "text": (
                        "Para las vacantes B1/EUA necesitamos confirmar que su licencia federal "
                        "y apto médico estén vigentes. ¿Qué tipo de licencia federal tiene y cuándo vence?"
                    ),
                },
                "reason": "b1_prehandoff_verificar_licencia",
            })

    # 5a.4: Reingreso — preguntar tipo de vacante (operador u otro)
    elif _intent_now == "reingreso_verificar":
        _tipo_vacante = _prehandoff_facts.get("reingreso.tipo_vacante", "")
        if not _tipo_vacante:
            contract = dict(contract)
            contract.update({
                "requires_human": False,
                "reply_template": {
                    "id": "reingreso_prehandoff_tipo",
                    "text": (
                        "Gracias por contactarnos de nuevo. ¿Busca regresar como operador de tracto, "
                        "o tiene en mente otro tipo de vacante?"
                    ),
                },
                "reason": "reingreso_prehandoff_verificar_tipo",
            })

    # answer_primary_question (multi-intent al path vivo): si el mensaje es compuesto
    # (perfil + pregunta) y la ruta principal no es RAG, resolvemos la pregunta
    # embebida. Si exige fuente autorizada y no la hay (pago), el fail-closed marca
    # requires_human ANTES de calcular flags/stage para que escale a HUMAN_REVIEW.
    embedded_question = _resolve_embedded_question(message, contract, lead_memory_before, turn_signals)
    if embedded_question and embedded_question["derive_to_human"]:
        contract["requires_human"] = True
        contract.setdefault("reason", "embedded_question_no_authorized_source")

    flags = _route_flags(str(contract.get("route") or "fallback"), str(contract.get("risk_level") or "low"))
    contract.update({**flags, "requires_rag": bool(contract.get("requires_rag")) and flags["requires_rag"]})

    current_stage = str(conversation.get("current_stage") or "START")
    next_stage = "HUMAN_REVIEW_REQUIRED" if contract.get("requires_human") else current_stage
    lead_stage_to = _stage_for_contract(contract, message)

    rag_result: dict[str, Any] | None = None
    friendly_result: dict[str, Any] | None = None
    profile_ack_used: bool = False

    if contract.get("intent") == "local_time":
        reply = _time_reply()
    elif contract.get("requires_rag"):
        rag_result = _answer_rag_message(message, contract)
        reply = rag_result["reply"]
    elif _should_use_friendly_llm(message, contract):
        if contract.get("route") == "fallback" and contract.get("intent") == "unknown":
            contract.update({"route": "friendly_smalltalk", "intent": "friendly_smalltalk", "reason": "safe_unknown_routed_to_friendly_llm"})
            lead_stage_to = _stage_for_contract(contract, message)
        friendly_result = _answer_friendly_message(message, contract, lead_memory_before)
        reply = friendly_result["reply"]
    elif contract.get("intent") == "greeting":
        # 2.3: candidato que regresa recibe ack corto + siguiente campo; primer turno → presentación completa
        # F1: si el mensaje trae pregunta embebida (no derivada), su respuesta ya saluda;
        # el saludo se reduce al siguiente dato del funnel para no duplicar el intro de Mundo.
        if embedded_question and not embedded_question["derive_to_human"]:
            reply = _greeting_followup_question(lead_memory_before)
        else:
            reply = _greeting_reply(lead_memory_before)
    elif contract.get("intent") == "candidate_profile_signal":
        ack = _build_profile_ack_reply(message)
        if ack:
            reply = ack
            profile_ack_used = True
        else:
            reply = _controlled_reply_from_contract(contract)
    else:
        reply = _controlled_reply_from_contract(contract)

    # answer_primary_question: antepone la respuesta a la pregunta embebida. En el
    # caso fail-closed (derive_to_human) la respuesta es el handoff y SUSTITUYE al
    # reply normal (no encimar funnel sobre una derivación).
    embedded_derived = bool(embedded_question and embedded_question["derive_to_human"])
    if embedded_question:
        if embedded_derived:
            reply = embedded_question["answer"]
        elif reply:
            reply = f'{embedded_question["answer"]}\n\n{reply}'
        else:
            # Saludo reducido a vacío (perfil completo o nada que preguntar): la
            # respuesta embebida es el reply completo, sin "\n\n" colgando.
            reply = embedded_question["answer"]

    # Route-1 contextual (G2, Fase B): resuelve confirmaciones implícitas del funnel
    # ANTES del nudge para que el campo confirmado no se vuelva a preguntar este turno.
    _r1_ack: str | None = None
    _r1_confirmed = False
    try:
        from app.knowledge.route1_contextual import ROUTE1_ACK, resolve_route1
        from app.lead_memory.last_asked_field import read_current_asked_field_keys

        _fresh_keys = read_current_asked_field_keys(lead_key)
        if _fresh_keys:
            _r1 = resolve_route1(message, _fresh_keys)
            if _r1["status"] == "confirmed":
                _r1_confirmed = True
                _r1_field: str = _r1["field"]
                _r1_value = _r1.get("value")
                _ack_tmpl = ROUTE1_ACK.get(_r1_field, "Entendido.")
                _r1_ack = _ack_tmpl.format(value=_r1_value if _r1_value is not None else "")
                _parts = _r1_field.split(".", 1)
                _r1_fact = {
                    "fact_group": _parts[0],
                    "fact_key": _parts[1] if len(_parts) > 1 else _r1_field,
                    "fact_value": str(_r1_value),
                }
                _pre_validated = list(_pre_validated or []) + [_r1_fact]
                friendly_result = None  # ack reemplaza el comentario amistoso del LLM
                log.info(
                    "[ROUTE1_ACTIVE] lead=%s fresh_keys=%s field=%s value=%s ack=%r",
                    lead_key, _fresh_keys, _r1_field, _r1_value, _r1_ack,
                )
            else:
                log.info(
                    "[ROUTE1_SHADOW] lead=%s fresh_keys=%s status=%s field=%s value=%s reason=%s",
                    lead_key, _fresh_keys, _r1["status"], _r1.get("field"),
                    _r1.get("value"), _r1.get("reason"),
                )
    except Exception as exc:
        log.warning("[ROUTE1] omitido por error: %s", exc)

    # Rama de objeción empática (D3): cuando el candidato declara no tener documento
    # (o propone alternativa) para un campo del funnel, emitir acuse empático y avanzar
    # el funnel al siguiente paso, sin re-preguntar el mismo campo en seco.
    # Detecta: documents.proof=ninguno en pre_validated (turno actual) + ruta no terminal.
    _objection_fired = False
    _TERMINAL_INTENTS = {"cecati_sugerido", "considerar_escuelita_transmontes", "reingreso_verificar"}
    _current_intent = str(contract.get("intent") or "")
    if (
        not _r1_confirmed
        and not embedded_derived
        and not contract.get("requires_human")
        and _current_intent not in _TERMINAL_INTENTS
    ):
        _pv_facts = {
            f"{f['fact_group']}.{f['fact_key']}": str(f["fact_value"])
            for f in (_pre_validated or [])
            if f.get("fact_group") and f.get("fact_key") and f.get("fact_value")
        }
        # Si _pre_validated no aporta la señal, detectar inline desde el texto del mensaje
        if "documents.proof" not in _pv_facts:
            _msg_lc = normalize_text(message)
            _neg_doc_hints = ("no tengo", "no cuento", "sin cartas", "no tengo cartas",
                              "no tengo membretadas", "no cuento con cartas")
            _doc_hints = ("carta", "cartas", "membretada", "membretadas", "documento laboral")
            if any(h in _msg_lc for h in _neg_doc_hints) and any(h in _msg_lc for h in _doc_hints):
                _pv_facts["documents.proof"] = "ninguno"
        _has_proof_ninguno = _pv_facts.get("documents.proof") == "ninguno"
        if _has_proof_ninguno:
            _objection_fired = True
            _FIELD_LABELS = {
                "documents.proof": "las cartas laborales membretadas",
                "documents.labor_letters_status": "las cartas laborales",
            }
            _field_label = _FIELD_LABELS.get("documents.proof", "el documento")
            reply = _answer_objection_message(message, lead_memory_before, _field_label)
            # Marcar como pendiente de envío para avanzar el funnel
            _pre_validated = list(_pre_validated or []) + [{
                "fact_group": "documents",
                "fact_key": "submission_status",
                "fact_value": "pending_candidate_will_send",
            }]
            friendly_result = None
            log.warning("[OBJECTION] lead=%s field=documents.proof → acuse empático + seguimiento", lead_key)
            try:
                from app.lead_memory.repository import upsert_lead_fact
                upsert_lead_fact(
                    lead_key=lead_key,
                    fact_group="documents",
                    fact_key="submission_status",
                    fact_value="pending_candidate_will_send",
                    confidence=0.90,
                    source="objection_empathic_branch",
                    source_text=message[:200],
                )
            except Exception:
                pass

    # Append one funnel profiling question after RAG, friendly, or profile ack.
    # Capture which canonical field(s) the nudge asked about (passive metadata).
    asked_field_keys: list[str] = []
    if (rag_result is not None or friendly_result is not None or profile_ack_used or _r1_confirmed or _objection_fired) and not embedded_derived:
        nudge, asked_field_keys = _build_funnel_nudge(
            message, contract, lead_memory_before,
            turn_signals=turn_signals, pre_validated_facts=_pre_validated,
        )
        if _r1_confirmed:
            # Multi-intención (bug prod conv 159): si además de confirmar el dato hubo
            # respuesta RAG a una pregunta embebida ("full pero ¿cuánto pagan?"), NO la
            # descartes. Compón: ack del dato + respuesta a la pregunta + siguiente
            # pregunta del funnel. Sin RAG, solo ack (+ nudge si hay).
            _rag_ans = reply.strip() if (rag_result is not None and reply and reply.strip()) else ""
            _parts = [p for p in (_r1_ack, _rag_ans, nudge) if p]
            reply = "\n\n".join(_parts) if _parts else (_r1_ack or "")
        elif _objection_fired:
            # Acuse empático ya está en reply; agregar siguiente pregunta del funnel si hay
            if nudge:
                reply = f"{reply}\n\n{nudge}"
            # Si no hay nudge, el acuse es la respuesta completa (perfil avanza al cierre)
        elif nudge:
            # 3.2: puente suave si el RAG respondió una duda en el primer turno (sin nombre aún)
            _facts_before = {
                f"{r['fact_group']}.{r['fact_key']}": r["fact_value"]
                for r in (lead_memory_before.get("facts") or []) if r.get("fact_value")
            }
            _is_first_rag = rag_result is not None and not _facts_before.get("candidate.name")
            if _is_first_rag:
                nudge = f"Si le interesa continuar con la vacante, {nudge[0].lower()}{nudge[1:]}"
            reply = f"{reply}\n\n{nudge}"
        else:
            asked_field_keys = []  # no nudge appended → no field was asked

    # Guard de léxico de vigencia sobre la respuesta final (todas las rutas): el bot
    # nunca emite "caduca/caducidad" al candidato.
    reply = _enforce_vigencia_lexicon(reply)

    # Detect call-time preference response when a solicitud_llamada was recently sent.
    # Saves the candidate's message as a private note in Chatwoot for Capital Humano.
    _maybe_save_call_preference(
        message=message,
        lead_key=lead_key,
        lead_memory=lead_memory_before,
        lead_stage_to=lead_stage_to,
    )

    update_stage(
        conversation_key=conversation_key,
        stage_to=next_stage,
        intent=contract.get("intent"),
        risk_level=contract.get("risk_level") or "low",
        requires_human=bool(contract.get("requires_human")),
    )

    lead_write = _store_lead_memory_updates(
        lead_key=lead_key,
        conversation_key=conversation_key,
        message=message,
        contract=contract,
        stage_from=lead_stage_from,
        stage_to=lead_stage_to,
        reply=reply,
        asked_field_keys=asked_field_keys,
        turn_signals=turn_signals,
        pre_validated_facts=_pre_validated,
    )
    lead_memory_after = lead_write.get("memory") or {}

    metadata = {
        "route": contract.get("route"),
        "recognized_terms": contract.get("recognized_terms"),
        "matched_aliases": contract.get("matched_aliases"),
        "preferred_sources": contract.get("preferred_sources"),
        "reason": contract.get("reason"),
        "all_matches": contract.get("all_matches"),
        "profile_guard_applied": contract.get("profile_guard_applied"),
        "lead_memory_v2": {
            "lead_key": lead_key,
            "stage_from": lead_stage_from,
            "stage_to": lead_stage_to,
            "facts_written": lead_write.get("facts_written"),
        },
    }
    if rag_result:
        metadata.update(
            {
                "rag_generation_used": rag_result.get("rag_generation_used"),
                "rag_generation_skipped_reason": rag_result.get("rag_generation_skipped_reason"),
                "rag_sources": (rag_result.get("rag_context") or {}).get("sources"),
                "rag_source_filter_used": (rag_result.get("rag_context") or {}).get("source_filter_used"),
                "rag_items_count": len((rag_result.get("rag_context") or {}).get("items") or []),
                "llm_cost_estimate": rag_result.get("llm_cost_estimate"),
                "timings": rag_result.get("timings"),
            }
        )
    if friendly_result:
        metadata.update(
            {
                "friendly_generation_used": friendly_result.get("friendly_generation_used"),
                "friendly_generation_skipped_reason": friendly_result.get("friendly_generation_skipped_reason"),
                "llm_cost_estimate": friendly_result.get("llm_cost_estimate"),
                "timings": friendly_result.get("timings"),
            }
        )

    log_event(
        conversation_key=conversation_key,
        event_type="knowledge_contract_resolved",
        stage_from=current_stage,
        stage_to=next_stage,
        intent=contract.get("intent"),
        risk_level=contract.get("risk_level") or "low",
        requires_human=bool(contract.get("requires_human")),
        metadata=metadata,
    )

    save_message(conversation_key, "assistant", reply)

    # Shadow mode multi-intent (Fase 4): corre el pipeline nuevo en paralelo y
    # loggea qué habría respondido, sin afectar la respuesta real. Flag-gated.
    if _env_bool("MULTI_INTENT_SHADOW", False):
        try:
            from app.knowledge.intent_shadow import run_shadow
            run_shadow(message, lead_memory_before, reply)
        except Exception as exc:
            log.warning("[MULTI_INTENT_SHADOW] no se pudo ejecutar: %s", exc)

    timings = {"total_ms": round((time.perf_counter() - started) * 1000, 2)}
    if rag_result and isinstance(rag_result.get("timings"), dict):
        timings.update(rag_result["timings"])
    if friendly_result and isinstance(friendly_result.get("timings"), dict):
        timings.update(friendly_result["timings"])

    sources = []
    if rag_result:
        for item in (rag_result.get("rag_context") or {}).get("items") or []:
            sources.append({"source": item.get("source"), "score": round(float(item.get("score") or 0), 4), "id": item.get("id")})

    cost = rag_result.get("llm_cost_estimate") if rag_result else friendly_result.get("llm_cost_estimate") if friendly_result else None

    return {
        "status": "ok",
        "selected_route": contract.get("route"),
        "intent": contract.get("intent"),
        "risk_level": contract.get("risk_level"),
        "requires_rag": contract.get("requires_rag"),
        "requires_human": contract.get("requires_human"),
        "requires_clarification": contract.get("requires_clarification"),
        "reply": reply,
        "text": reply,
        "conversation_key": conversation_key,
        "lead_key": lead_key,
        "lead_memory": lead_memory_after,
        "sources": sources,
        "knowledge_contract": contract,
        "rag": {
            "used": bool(rag_result and rag_result.get("rag_generation_used")),
            "skipped_reason": rag_result.get("rag_generation_skipped_reason") if rag_result else None,
            "preferred_sources": contract.get("preferred_sources") or [],
            "retrieved_sources": (rag_result.get("rag_context") or {}).get("sources") if rag_result else [],
            "items_count": len((rag_result.get("rag_context") or {}).get("items") or []) if rag_result else 0,
        },
        "friendly": {
            "used": bool(friendly_result and friendly_result.get("friendly_generation_used")),
            "skipped_reason": friendly_result.get("friendly_generation_skipped_reason") if friendly_result else None,
        },
        "cost": cost,
        "timings": timings,
        "graph_trace": {
            "mode": "knowledge",
            "route": contract.get("route"),
            "intent": contract.get("intent"),
            "risk_level": contract.get("risk_level"),
            "requires_rag": contract.get("requires_rag"),
            "requires_human": contract.get("requires_human"),
            "requires_clarification": contract.get("requires_clarification"),
            "lead_memory_v2": {
                "lead_key": lead_key,
                "stage_from": lead_stage_from,
                "stage_to": lead_stage_to,
                "facts_written": lead_write.get("facts_written"),
            },
            "timings": timings,
            "cost": cost,
            "nodes": [
                {
                    "node": "neo4j_knowledge_node",
                    "decision": contract.get("route"),
                    "recognized_terms": contract.get("recognized_terms"),
                    "matched_aliases": contract.get("matched_aliases"),
                    "preferred_sources": contract.get("preferred_sources"),
                    "reason": contract.get("reason"),
                    "profile_guard_applied": contract.get("profile_guard_applied"),
                },
                {
                    "node": "lead_memory_v2_writer",
                    "decision": lead_stage_to,
                    "lead_key": lead_key,
                    "facts_written": lead_write.get("facts_written"),
                },
                {
                    "node": "controlled_rag_generation",
                    "decision": "used" if rag_result and rag_result.get("rag_generation_used") else "skipped",
                    "sources": (rag_result.get("rag_context") or {}).get("sources") if rag_result else [],
                    "items_count": len((rag_result.get("rag_context") or {}).get("items") or []) if rag_result else 0,
                    "skipped_reason": rag_result.get("rag_generation_skipped_reason") if rag_result else None,
                },
                {
                    "node": "friendly_llm_generation",
                    "decision": "used" if friendly_result and friendly_result.get("friendly_generation_used") else "skipped",
                    "skipped_reason": friendly_result.get("friendly_generation_skipped_reason") if friendly_result else None,
                },
            ],
        },
    }
