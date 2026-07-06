import os
from typing import Any

import httpx

from .db import get_conn
from .knowledge.business_route_schema import VALID_VEHICLE_TYPES
from .knowledge.current_turn import is_valid_expiration_text, profile_funnel_complete
from .knowledge.geo_utils import is_zm_laguna_canonical, normalize_zm_laguna_city
from .knowledge.text_normalizer import normalize_text

PENDING_TEXT = "Pendiente"


def _apto_status_display(medical_status_raw: str, apto_exp_text: str) -> str:
    """Muestra el estado del apto: vigente si hay texto de vencimiento real, Pendiente si no."""
    if _is_vigente(medical_status_raw):
        return "Vigente"
    if apto_exp_text not in {"Pendiente", ""} and is_valid_expiration_text(apto_exp_text):
        return "Vigente"
    return _human_fact(medical_status_raw)


def _exp_display(exp_text: str) -> str:
    """Normaliza el texto de vencimiento para mostrarlo sin prefijo 'vence' duplicado."""
    t = (exp_text or "").strip()
    if not t or t == PENDING_TEXT:
        return t
    tl = t.lower()
    # Ya contiene un verbo de vencimiento propio → mostrar tal cual
    if tl.startswith("vence") or tl.startswith("vencid") or tl.startswith("al mismo"):
        return t
    return f"vence en {t}"

OFFICIAL_LABELS: frozenset[str] = frozenset({
    "aclaracion_pendiente",
    "bot_activo",
    "cecati_sugerido",
    "considerar_escuelita_transmontes",
    "considerar_operador_b1",
    "descartado_edad",
    "documentos",
    "falta_apto",
    "falta_ciudad",
    "falta_experiencia",
    "falta_licencia",
    "falta_unidad",
    "foraneo",
    "insistencia",
    "jerga_ambigua",
    "llamada_pendiente",
    "local_laguna",
    "objetivo_full",
    "objetivo_sencillo",
    "perfil_listo",
    "reingreso_verificar",
    "requiere_agente",
    "requiere_revision_ch",
    "riesgo_alto",
    "seguimiento",
    "urgente",
    "validar_traslado",
})

# Labels terminales: su presencia remueve bot_activo en todo path de emisión
# (openspec/specs/chatwoot-label-taxonomy — "Labels terminales remueven bot_activo").
TERMINAL_LABELS: frozenset[str] = frozenset({
    "perfil_listo",
    "requiere_agente",
    "requiere_revision_ch",
    "riesgo_alto",
    "reingreso_verificar",
    "descartado_edad",
})

# Aliases fantasma → label oficial. La vista SQL `v_rh_work_queue.suggested_chatwoot_labels`
# y otras fuentes emiten nombres fuera del catálogo; se mapean al equivalente oficial en el
# único chokepoint (`_filter_official_labels`) para no llegar crudos a Chatwoot (B11.1/B11.2).
# `requiere_humano`→`requiere_agente` y `falta_cartas`→`documentos` los manda el spec
# (chatwoot-label-taxonomy); el resto preserva la señal con el nombre oficial.
LABEL_ALIASES: dict[str, str] = {
    "requiere_humano":      "requiere_agente",
    "falta_cartas":         "documentos",
    "ubicacion_extranjero": "foraneo",
    "validar_ch":           "requiere_revision_ch",
    "posible_abandono":     "seguimiento",
}

# Display humano de labels en la nota privada
_LABEL_DISPLAY: dict[str, str] = {
    "cecati_sugerido":                  "CECATI sugerido",
    "considerar_escuelita_transmontes": "Considerar Escuelita Transmontes",
    "considerar_operador_b1":           "Considerar operador B1 (EUA)",
    "llamada_pendiente":                "Llamada pendiente",
    "objetivo_full":                    "Objetivo full",
    "objetivo_sencillo":                "Objetivo sencillo",
    "perfil_listo":                     "Perfil listo",
    "requiere_agente":                  "Requiere agente",
    "requiere_revision_ch":             "Requiere revisión CH",
    "reingreso_verificar":              "Reingreso — verificar",
    "riesgo_alto":                      "Riesgo alto",
    "aclaracion_pendiente":             "Aclaración pendiente",
    "jerga_ambigua":                    "Jerga ambigua",
    "foraneo":                          "Foráneo",
    "local_laguna":                     "Local Laguna",
    "validar_traslado":                 "Validar traslado",
    "falta_licencia":                   "Falta licencia",
    "falta_apto":                       "Falta apto",
    "falta_ciudad":                     "Falta ciudad",
    "falta_experiencia":                "Falta experiencia",
    "falta_unidad":                     "Falta unidad",
    "documentos":                       "Documentos",
    "seguimiento":                      "Seguimiento",
    "urgente":                          "Urgente",
    "bot_activo":                       "Bot activo",
    "insistencia":                      "Insistencia",
    "descartado_edad":                  "Descartado por edad",
}


def _text(value: Any, default: str = "No disponible") -> str:
    if value is None:
        return default
    value = str(value).strip()
    return value or default


def _human_fact(value: Any, default: str = PENDING_TEXT) -> str:
    raw = _text(value, default)
    mapping = {
        "asked": "Preguntó",
        "sí": "Sí",
        "si": "Sí",
        "yes": "Sí",
        "true": "Sí",
        "vigente": "Vigente",
        "mencionada": "Mencionada",
        "pending_update": "Pendiente de actualización",
        "pending_candidate_will_send": "Pendiente, candidato enviará",
        "pendiente_por_candidato": "Pendiente, candidato enviará",
        "en_ruta_o_no_disponible_ahora": "En ruta / no disponible ahora",
    }
    return mapping.get(raw, raw)


def _is_yes(value: Any) -> bool:
    return str(value or "").strip().lower() in {"sí", "si", "yes", "true", "1"}


def _is_vigente(value: Any) -> bool:
    return str(value or "").strip().lower() in {"vigente", "sí", "si", "yes", "true"}


def _is_truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"sí", "si", "yes", "true", "1", "sÃ­"}


def _age_disqualified(facts: dict[str, Any]) -> bool:
    try:
        from app.settings import AGE_DISQUALIFICATION_LIMIT
        return int(str(facts.get("candidate.age") or "").strip()) >= AGE_DISQUALIFICATION_LIMIT
    except ValueError:
        return False



def _risk(value: str | None) -> str:
    return {"low": "Bajo", "medium": "Medio", "high": "Alto"}.get((value or "").lower(), value or "No disponible")


# _temperatura eliminado (Fase 0 / F26): la "temperatura" del lead es subjetiva si no
# está estrictamente calculada; se deprecó y ya no se muestra en la nota privada.


def _stage(value: str | None) -> str:
    return {
        "new": "Nuevo",
        "interested": "Interesado",
        "vacancy_info_shared": "Información de vacante compartida",
        "profiled_viable": "Perfil viable",
        "potential_candidate_documents_pending": "Pendiente de documentos",
        "followup_pending": "Seguimiento pendiente",
        "documents_pending": "Pendiente de documentos",
        "profile_hint_collected": "Perfil en captura",
        "profile_ready": "Perfil listo",
        "apto_pending_update": "Apto pendiente de actualización",
        "human_review_required": "Revisión de Capital Humano",
        "closed": "Cerrado",
        "discarded": "Descartado",
    }.get((value or "").lower(), value or "No disponible")


def _normalize_labels(labels) -> list[str]:
    return sorted({str(label or "").strip().lower() for label in (labels or []) if str(label or "").strip()})


def _filter_official_labels(labels) -> list[str]:
    # Mapea aliases fantasma → oficial, luego conserva solo labels del catálogo.
    mapped = {LABEL_ALIASES.get(lbl, lbl) for lbl in _normalize_labels(labels)}
    return sorted(lbl for lbl in mapped if lbl in OFFICIAL_LABELS)


def _facts_map(rows: list[dict[str, Any]]) -> dict[str, str]:
    facts = {}
    for row in rows:
        group = str(row.get("fact_group") or "").strip().lower()
        key = str(row.get("fact_key") or "").strip().lower()
        value = str(row.get("fact_value") or "").strip()
        if group and key and value:
            facts[f"{group}.{key}"] = value
    return facts


def _fact(facts: dict[str, str], *keys: str, default: str = PENDING_TEXT) -> str:
    for key in keys:
        if facts.get(key):
            return facts[key]
    return default


def get_lead_note_context(lead_key: str) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT lead_key, display_name, phone, source_channel, lead_status,
                       funnel_stage, next_best_action, memory_summary, facts_summary,
                       risk_level, requires_human, first_seen_at, last_seen_at, updated_at
                FROM rh_leads_v2
                WHERE lead_key = %(lead_key)s
                LIMIT 1;
                """,
                {"lead_key": lead_key},
            )
            lead = cur.fetchone()

            cur.execute(
                """
                SELECT lead_key, conversation_key, channel, channel_user_id,
                       chatwoot_account_id, chatwoot_inbox_id, chatwoot_conversation_id,
                       chatwoot_contact_id, is_primary, external_metadata, updated_at
                FROM rh_lead_conversations_v2
                WHERE lead_key = %(lead_key)s
                ORDER BY is_primary DESC, updated_at DESC
                LIMIT 1;
                """,
                {"lead_key": lead_key},
            )
            conversation = cur.fetchone()

            cur.execute(
                """
                SELECT fact_group, fact_key, fact_value, confidence, source,
                       source_message_id, source_text, updated_at
                FROM rh_lead_facts_v2
                WHERE lead_key = %(lead_key)s
                ORDER BY fact_group, fact_key, updated_at DESC;
                """,
                {"lead_key": lead_key},
            )
            facts_rows = cur.fetchall()

            cur.execute(
                """
                SELECT role, message, source_message_id, created_at
                FROM rh_lead_messages_v2
                WHERE lead_key = %(lead_key)s
                ORDER BY created_at DESC
                LIMIT 1;
                """,
                {"lead_key": lead_key},
            )
            last_message = cur.fetchone()

    facts_rows = [dict(row) for row in facts_rows or []]
    return {
        "lead": dict(lead) if lead else {},
        "conversation": dict(conversation) if conversation else {},
        "facts_rows": facts_rows,
        "facts": _facts_map(facts_rows),
        "last_message": dict(last_message) if last_message else {},
    }


def _expiry_urgency(expiration_text: str) -> str | None:
    """Classify document expiry urgency from free-text like 'vence en 2 semanas'."""
    if not expiration_text:
        return None
    t = expiration_text.lower()
    # Urgent: days or weeks
    if any(w in t for w in ("día", "dia", "días", "dias", "semana", "semanas")):
        return "urgente"
    # Watch: months 1–5
    for n in range(1, 6):
        if f"{n} mes" in t or f"{n} mes" in t:
            return "revisar"
    # OK: 6+ months or years — no urgency label
    return None


def calculate_candidate_labels(context: dict[str, Any]) -> list[str]:
    lead = context.get("lead") or {}
    facts = context.get("facts") or {}
    facts_summary = lead.get("facts_summary") or {}
    labels = {"bot_activo"}

    if _age_disqualified(facts):
        # Descarte por edad: label terminal (antes cerraba sin label alguno).
        return ["descartado_edad"]

    if lead.get("requires_human"):
        labels.update({"requiere_agente", "requiere_revision_ch"})
    if (lead.get("risk_level") or "").lower() == "high":
        labels.add("riesgo_alto")

    # Bloque 4/5: pausa por insistencia sostenida activa → label para Capital Humano.
    # Se lee de facts (funnel.paused_until, ISO UTC); no requiere llamada extra.
    _paused_until = str(facts.get("funnel.paused_until") or "").strip()
    if _paused_until:
        try:
            import datetime as _dt
            _pu = _dt.datetime.fromisoformat(_paused_until)
            if _pu.tzinfo is None:
                _pu = _pu.replace(tzinfo=_dt.timezone.utc)
            if _pu > _dt.datetime.now(_dt.timezone.utc):
                labels.add("insistencia")
        except ValueError:
            pass

    has_license    = bool(facts.get("license.category"))
    # has_medical: vigente explícito O tiene texto de vencimiento (incluye "al mismo tiempo...")
    _apto_exp_raw  = str(facts.get("medical.apto_expiration_text") or "").strip()
    _apto_equality = any(h in _apto_exp_raw.lower() for h in (
        "al mismo tiempo", "igual que", "mismo que", "igual a", "misma vigencia",
        "los dos", "ambos", "igual", "lo mismo",
    )) if _apto_exp_raw else False
    has_medical    = (
        facts.get("medical.apto_status") in {"vigente", "sí", "si"}
        or bool(_apto_exp_raw not in {"Pendiente", ""} and is_valid_expiration_text(_apto_exp_raw))
        or _apto_equality
    )
    # Unidad confirmada solo si es exactamente full/sencillo; jerga ambigua
    # ("quinta rueda", "tráiler"…) no confirma — la aclara el pipeline de comprensión.
    vehicle_confirmed = facts.get("experience.vehicle_type") in VALID_VEHICLE_TYPES
    has_non_target_experience = bool(facts.get("experience.non_target_vehicle_type"))
    has_no_road_experience = str(facts.get("experience.road_experience") or "").strip().lower() in {
        "none", "no", "sin_experiencia", "sin experiencia"
    }
    has_pending_vehicle_type = bool(facts.get("experience.vehicle_type_pending"))
    has_b1_us_intent = _is_truthy(facts.get("experience.b1_us_intent"))
    has_reingreso = _is_truthy(facts.get("candidate.reingreso"))
    has_experience = (
        vehicle_confirmed
        or bool(facts.get("experience.years"))
        or has_non_target_experience
        or has_no_road_experience
    )
    has_letters    = (
        facts.get("documents.labor_letters_status") in {"available", "sí", "si"}
        or facts.get("documents.labor_letters") in {"available", "sí", "si"}
        or facts.get("documents.proof") in {"cartas", "semanas_imss", "sí", "si"}
    )

    # Tricotomía mutuamente excluyente: objetivo > no-objetivo > sin experiencia.
    if vehicle_confirmed:
        # Label separado por unidad (full/sencillo); cualquiera de los dos completa
        # el campo de unidad para perfil_listo. Se decide por el fact confirmado.
        _vt = normalize_text(str(facts.get("experience.vehicle_type") or ""))
        labels.add("objetivo_sencillo" if "sencillo" in _vt else "objetivo_full")
    elif has_non_target_experience:
        labels.update({"considerar_escuelita_transmontes", "requiere_agente", "requiere_revision_ch"})
    elif has_no_road_experience:
        labels.update({"cecati_sugerido", "requiere_agente", "requiere_revision_ch"})

    if has_pending_vehicle_type and not vehicle_confirmed:
        labels.add("aclaracion_pendiente")

    if has_b1_us_intent:
        labels.update({"considerar_operador_b1", "requiere_agente", "requiere_revision_ch"})

    if has_reingreso:
        labels.update({"reingreso_verificar", "requiere_agente", "requiere_revision_ch"})

    if not has_license:
        labels.add("falta_licencia")
    if not has_medical:
        labels.add("falta_apto")
    if not vehicle_confirmed:
        labels.add("falta_unidad")
    if not facts.get("candidate.city"):
        labels.add("falta_ciudad")
    if not has_experience:
        labels.add("falta_experiencia")
    if not has_letters and (has_license or has_experience):
        labels.add("documentos")

    if has_medical:
        labels.discard("falta_apto")

    if facts.get("documents.submission_status") == "pending_candidate_will_send":
        labels.add("seguimiento")
    if facts.get("candidate.availability_status") == "en_ruta_o_no_disponible_ahora":
        labels.add("seguimiento")

    # Ubicación core (10a.5): local_laguna / foraneo, mutuamente excluyentes.
    # Usa el catálogo ZML/Comarca (geo_utils) como fuente de verdad.
    city_raw = facts.get("candidate.city") or ""
    if city_raw:
        # Resuelve alias del catálogo (p. ej. "Torreón Coahuila", "Cd. Lerdo") antes de
        # comparar contra el set canónico; sin esto, alias reales del catálogo se
        # etiquetaban foraneo por error (bug encontrado en auditoría 2026-07-06).
        if is_zm_laguna_canonical(normalize_zm_laguna_city(city_raw)):
            labels.add("local_laguna")
        else:
            labels.update({"foraneo", "validar_traslado"})

    # perfil_listo: todos los campos núcleo recolectados → Capital Humano toma el caso.
    # La aceptación explícita de la vacante no es requisito; se asume implícita cuando
    # el candidato completó el funnel sin abandonar (candidate.vacancy_accepted era un
    # falso bloqueo: el bot ya preguntó todo, el candidato respondió).
    has_city = bool(facts.get("candidate.city"))
    # perfil_listo deriva de la fuente única del funnel (D1): solo cuando NO queda
    # pregunta pendiente (incluye years explícito, documento laboral y vencimientos
    # VÁLIDOS — una no-respuesta de vencimiento no lo activa).
    if (
        profile_funnel_complete(facts)
        and vehicle_confirmed  # unidad canónica (full/sencillo), no jerga ambigua
        and not (has_non_target_experience or has_no_road_experience or has_reingreso)
    ):
        labels.update({"perfil_listo", "requiere_revision_ch"})
        labels.discard("falta_licencia")
        labels.discard("falta_apto")
        labels.discard("falta_unidad")
        labels.discard("falta_experiencia")
        labels.discard("documentos")

    # B7.4 — llamada pendiente: solo desde decisión determinista cuando perfil_listo o
    # requiere_agente están activos y el candidato pidió llamada (scheduling.call_requested).
    # Antes de perfil listo / handoff → seguimiento (no llamada_pendiente). Sin agenda real.
    call_requested = str(facts.get("scheduling.call_requested") or "").strip().lower() in {
        "true", "sí", "si", "1", "yes"
    }
    if call_requested:
        if {"perfil_listo", "requiere_agente"} & labels:
            labels.add("llamada_pendiente")
        else:
            labels.add("seguimiento")

    # Labels terminales detienen el flujo automático: bot_activo no coexiste.
    if labels & TERMINAL_LABELS:
        labels.discard("bot_activo")

    return _filter_official_labels(labels)


def _render_escuelita_note(lead: dict[str, Any], message: str, facts: dict[str, str], license_category: str) -> str:
    """Nota administrativa de la rama escuelita (experiencia no objetivo).

    Lenguaje para Capital Humano: sin Embudo/Canal/Riesgo/Requiere humano. Muestra el
    mínimo (experiencia no objetivo + licencia B/E). Con licencia B/E → valorar/canalizar;
    sin ella → pedir confirmación de B/E (compuerta de elegibilidad).
    """
    non_target = _fact(facts, "experience.non_target_vehicle_type", default="")
    exp_line = (
        f"Maneja {non_target}" if non_target and non_target != PENDING_TEXT
        else "Experiencia no objetivo (no full/sencillo)"
    )
    has_be = str(license_category or "").strip().upper() in {"B", "E"}

    sabemos = [
        f"Experiencia: {exp_line}",
        "Unidad objetivo: No ha manejado full o sencillo",
    ]
    if has_be:
        sabemos.append(f"Licencia: {license_category} (apta para escuelita)")

    falta_block = ""
    if not has_be:
        falta_block = (
            "⚠️ Falta confirmar\n"
            "Licencia: Confirmar si cuenta con licencia federal B o E vigente\n\n"
        )

    next_action = (
        "Valorar Escuelita Transmontes y revisar generación disponible."
        if has_be
        else "Confirmar licencia B o E. Si no cuenta con licencia B o E vigente, no aplica para esta ruta."
    )

    return (
        "🤖 Nota IA: Seguimiento de candidato escuelita\n\n"
        f"Último mensaje: \"{message}\"\n\n"
        f"{_nota_contacto(lead, facts)}\n\n"
        "📌 Estado del candidato\n"
        "Operador a considerar para Escuelita Transmontes\n\n"
        "✅ Lo que ya sabemos\n"
        + "\n".join(sabemos) + "\n\n"
        + falta_block +
        "👥 Para Capital Humano\n"
        "Valorar si aplica para Escuelita Transmontes (revisar generación disponible).\n"
        "Requiere Agente: Sí\n\n"
        "⏭️ Siguiente acción\n"
        f"{next_action}"
    )


def _nota_header(scenario: str) -> str:
    return f"🤖 Nota IA: {scenario}"


def _nota_contacto(lead: dict[str, Any], facts: dict[str, Any] | None = None) -> str:
    # Nombre solo desde facts['candidate.name']; nunca desde Telegram/WhatsApp display_name
    name_val = (facts or {}).get("candidate.name") or "No disponible"
    return (
        "👤 Contacto\n"
        f"Nombre: {name_val}\n"
        f"Teléfono: {_text(lead.get('phone'))}"
    )


def _next_action_dinamica(facts: dict[str, str], is_local: bool, labels: list[str]) -> str:
    """⏭️ Siguiente acción dinámica según el primer campo núcleo pendiente (task 4.7)."""
    lbl = set(labels or [])
    if "considerar_escuelita_transmontes" in lbl or "cecati_sugerido" in lbl:
        return "Verificar disponibilidad de generación en Escuelita Transmontes."
    if "reingreso" in lbl:
        return "Verificar historial del candidato y confirmar disponibilidad de vacante."
    if "b1_us" in lbl or "business_route_us" in str(facts.get("funnel.status", "")):
        vt = facts.get("experience.vehicle_type", "")
        return f"Revisar vacante B1/EUA para operador de {vt or 'tracto'}."
    if not facts.get("candidate.city"):
        return "Solicitar ciudad de residencia."
    if not facts.get("candidate.age"):
        return "Confirmar edad del candidato."
    if not facts.get("experience.vehicle_type"):
        return "Confirmar tipo de unidad (tracto full o sencillo)."
    if not facts.get("license.category"):
        return "Solicitar tipo y vigencia de licencia federal."
    if not is_valid_expiration_text(facts.get("license.expiration_text")):
        return "Confirmar vigencia de licencia federal."
    if not is_valid_expiration_text(facts.get("medical.apto_expiration_text")):
        return "Confirmar vigencia del apto médico."
    if not facts.get("experience.years"):
        return "Confirmar años de experiencia como operador."
    proof = facts.get("documents.proof", "")
    if proof not in {"cartas", "semanas_imss", "sí", "si"}:
        if is_local:
            return "Solicitar cartas laborales o documento de semanas IMSS."
        return "Solicitar 2 cartas laborales membretadas."
    # Núcleo completo
    if is_local:
        return "Validar documentos y continuar proceso de contratación."
    return "Validar traslado, documentos y continuidad del proceso."


def render_candidate_note(context: dict[str, Any], labels: list[str], fallback_last_message: str | None = None, channel_label: str | None = None) -> str:
    lead = context.get("lead") or {}
    conversation = context.get("conversation") or {}
    facts = context.get("facts") or {}
    last = context.get("last_message") or {}
    lbl = list(labels or [])

    message = _text(fallback_last_message or last.get("message"), "Sin mensaje reciente")[:500]

    # ── Datos del perfil ──────────────────────────────────────────────────────
    name = facts.get("candidate.name") or ""  # solo desde facts, nunca desde display_name
    vehicle_type_raw = _fact(facts, "experience.vehicle_type", default="")
    years = _fact(facts, "experience.years")
    license_category = _fact(facts, "license.category")
    license_exp_text = _fact(facts, "license.expiration_text", default="")
    apto_exp_text_raw = _fact(facts, "medical.apto_expiration_text", default="")
    # Fix 3: "al mismo tiempo / igual que / mismo que la licencia" → resolver al valor de licencia
    _equality_hints = ("al mismo tiempo", "igual que", "mismo que", "igual a", "misma vigencia",
                       "los dos", "ambos", "igual", "lo mismo", "los mismos")
    if apto_exp_text_raw and any(h in apto_exp_text_raw.lower() for h in _equality_hints):
        apto_exp_text = license_exp_text if license_exp_text else apto_exp_text_raw
    else:
        apto_exp_text = apto_exp_text_raw
    medical_status_raw = _fact(facts, "medical.apto_status", "document.apto_status", "documents.general_status")
    proof_raw = _fact(facts, "documents.proof", "documents.labor_letters_status", "documents.labor_letters")
    city = _fact(facts, "candidate.city")
    age = _fact(facts, "candidate.age")

    is_local = is_zm_laguna_canonical(str(city)) or facts.get("location.is_local_laguna") == "true"

    if vehicle_type_raw == "full":
        vt_display = "Tracto full"
    elif vehicle_type_raw == "sencillo":
        vt_display = "Sencillo"
    elif vehicle_type_raw:
        vt_display = _human_fact(vehicle_type_raw)
    else:
        vt_display = PENDING_TEXT

    age_disq = _age_disqualified(facts)
    has_vt = bool(vehicle_type_raw)
    has_lic = license_category not in {PENDING_TEXT, "", None}
    has_apto = bool(apto_exp_text not in {PENDING_TEXT, ""} and is_valid_expiration_text(apto_exp_text)) or _is_vigente(medical_status_raw)
    has_years = years not in {PENDING_TEXT, "", None}
    has_city = city not in {PENDING_TEXT, "", None}
    has_doc = proof_raw in {"cartas", "semanas_imss", "sí", "si", "available"}
    tramite_lic = facts.get("license.tramite_comprobante") == "true"
    tramite_apto = facts.get("medical.tramite_comprobante") == "true"
    vencido_sin_tramite = facts.get("funnel.status") == "vencido_sin_tramite"
    nucleo_completo = has_vt and has_lic and has_apto and has_years and has_city and has_doc

    requires_human_bool = bool(lead.get("requires_human"))
    requiere_agente = "Sí" if requires_human_bool else "No"
    riesgo_alto = "riesgo_alto" in lbl

    # 📞 Llamada (mantener si solicitó llamada)
    llamada_block = ""
    if str(facts.get("scheduling.call_requested") or "").strip().lower() in {"true", "sí", "si", "1", "yes"}:
        window_text = _fact(facts, "scheduling.call_window_text", default="")
        valid = str(facts.get("scheduling.call_window_valid") or "unknown").strip().lower()
        valid_display = {"true": "dentro del horario de atención", "false": "fuera del horario de atención"}.get(valid, "por confirmar")
        ventana_line = f"Ventana: {window_text}\n" if window_text and window_text != PENDING_TEXT else ""
        llamada_block = f"📞 Llamada solicitada ({valid_display})\n{ventana_line}\n"

    # ── Selección de escenario (determinista) ─────────────────────────────────
    # 4.2 Escuelita
    if "considerar_escuelita_transmontes" in lbl:
        return _render_escuelita_note(lead, message, facts, license_category)

    # 4.6 CECATI
    if "cecati_sugerido" in lbl:
        return (
            f"{_nota_header('Candidato referido a CECATI')}\n\n"
            f"Último mensaje: \"{message}\"\n\n"
            f"{_nota_contacto(lead, facts)}\n\n"
            "📌 Estado del candidato\n"
            "Sin experiencia en tracto federal. Se orientó al CECATI Gómez Palacio para formación.\n\n"
            "✅ Lo que ya sabemos\n"
            f"Ciudad: {city}\n"
            f"Edad: {age}\n\n"
            "👥 Para Capital Humano\n"
            "Candidato orientado a CECATI; retomará proceso al completar formación.\n"
            f"Requiere Agente: {requiere_agente}\n\n"
            "⏭️ Siguiente acción\n"
            "Sin acción inmediata; esperar recontacto tras formación CECATI."
        )

    # 4.6 B1 / EUA
    if "b1_us" in lbl or "business_route_us" in lbl:
        return (
            f"{_nota_header('Candidato con Ruta B1/EUA')}\n\n"
            f"Último mensaje: \"{message}\"\n\n"
            f"{_nota_contacto(lead, facts)}\n\n"
            "📌 Estado del candidato\n"
            "Interesado en ruta con cruce a EUA (B1). Requiere revisión de Capital Humano.\n\n"
            "✅ Lo que ya sabemos\n"
            f"Ciudad: {city}\n"
            f"Unidad: {vt_display}\n"
            f"Licencia: {_human_fact(license_category)}" + (f" · {_exp_display(license_exp_text)}" if license_exp_text else "") + "\n\n"
            "👥 Para Capital Humano\n"
            "Revisar vacante B1/EUA disponible y confirmar requisitos de cruce.\n"
            f"Requiere Agente: Sí\n\n"
            "⏭️ Siguiente acción\n"
            f"{_next_action_dinamica(facts, is_local, lbl)}"
        )

    # 4.6 Reingreso
    if "reingreso" in lbl:
        return (
            f"{_nota_header('Candidato de Reingreso')}\n\n"
            f"Último mensaje: \"{message}\"\n\n"
            f"{_nota_contacto(lead, facts)}\n\n"
            "📌 Estado del candidato\n"
            "Candidato que operó anteriormente con Transmontes y solicita reingreso.\n\n"
            "✅ Lo que ya sabemos\n"
            f"Ciudad: {city}\n"
            f"Unidad: {vt_display}\n"
            f"Licencia: {_human_fact(license_category)}" + (f" · {_exp_display(license_exp_text)}" if license_exp_text else "") + "\n\n"
            "👥 Para Capital Humano\n"
            "Verificar historial del candidato en sistema antes de canalizar.\n"
            f"Requiere Agente: Sí\n\n"
            "⏭️ Siguiente acción\n"
            "Verificar historial de reingreso y confirmar disponibilidad de vacante."
        )

    # 4.6 Edad fuera de perfil
    if age_disq:
        return (
            f"{_nota_header('Candidato Fuera de Perfil por Edad')}\n\n"
            f"Último mensaje: \"{message}\"\n\n"
            f"{_nota_contacto(lead, facts)}\n\n"
            "📌 Estado del candidato\n"
            f"Edad fuera del rango requerido. Edad declarada: {age}.\n\n"
            "👥 Para Capital Humano\n"
            "Perfil no aplica por edad. Proceso cerrado automáticamente.\n"
            "Requiere Agente: No\n\n"
            "⏭️ Siguiente acción\n"
            "Ninguna. Cierre automático por edad fuera de perfil."
        )

    # 4.6 Riesgo / sensible
    if riesgo_alto:
        return (
            f"{_nota_header('Candidato con Señal de Riesgo')}\n\n"
            f"Último mensaje: \"{message}\"\n\n"
            f"{_nota_contacto(lead, facts)}\n\n"
            "📌 Estado del candidato\n"
            "Conversación con señal de riesgo detectada. Requiere revisión humana.\n\n"
            "👥 Para Capital Humano\n"
            "Revisar historial de mensajes y determinar continuidad del proceso.\n"
            "Requiere Agente: Sí\n"
            "⚠️ Riesgo: Alto\n\n"
            "⏭️ Siguiente acción\n"
            "Revisar conversación completa antes de continuar."
        )

    # 4.5 Vencido sin trámite
    if vencido_sin_tramite:
        return (
            f"{_nota_header('Candidato con Licencia/Apto Vencido')}\n\n"
            f"Último mensaje: \"{message}\"\n\n"
            f"{_nota_contacto(lead, facts)}\n\n"
            "📌 Estado del candidato\n"
            "Licencia o apto vencido. Sin comprobante de renovación en trámite.\n\n"
            "✅ Lo que ya sabemos\n"
            f"Ciudad: {city}\n"
            f"Unidad: {vt_display}\n"
            f"Licencia: {_human_fact(license_category)}" + (f" · {_exp_display(license_exp_text)}" if license_exp_text else "") + "\n"
            f"Apto médico: {_apto_status_display(medical_status_raw, apto_exp_text)}" + (f" · {_exp_display(apto_exp_text)}" if apto_exp_text else "") + "\n\n"
            "👥 Para Capital Humano\n"
            "Candidato invitado a retomar cuando renueve documentos. Sin acción inmediata.\n"
            "Requiere Agente: No\n\n"
            "⏭️ Siguiente acción\n"
            "Esperar recontacto cuando el candidato tenga documentos vigentes."
        )

    # 4.5 Vencido en trámite (con comprobante)
    if tramite_lic or tramite_apto:
        doc_tramite = []
        if tramite_lic:
            doc_tramite.append("licencia en renovación")
        if tramite_apto:
            doc_tramite.append("apto en renovación")
        return (
            f"{_nota_header('Candidato con Trámite en Proceso')}\n\n"
            f"Último mensaje: \"{message}\"\n\n"
            f"{_nota_contacto(lead, facts)}\n\n"
            "📌 Estado del candidato\n"
            f"Candidato con {', '.join(doc_tramite)}. Tiene comprobante de cita.\n\n"
            "✅ Lo que ya sabemos\n"
            f"Ciudad: {city}\n"
            f"Unidad: {vt_display}\n"
            f"Licencia: {_human_fact(license_category)}" + (f" · {_exp_display(license_exp_text)}" if license_exp_text else "") + "\n"
            f"Apto médico: {_apto_status_display(medical_status_raw, apto_exp_text)}" + (f" · {_exp_display(apto_exp_text)}" if apto_exp_text else "") + "\n\n"
            "👥 Para Capital Humano\n"
            "Continuar perfilamiento. Aclaración pendiente de validación de documentos.\n"
            "Requiere Agente: No\n\n"
            "⏭️ Siguiente acción\n"
            f"{_next_action_dinamica(facts, is_local, lbl)}"
        )

    # 4.3 Perfil listo local / 4.4 Perfil listo foráneo
    if nucleo_completo:
        doc_display = "Cartas laborales o semanas cotizadas del IMSS" if is_local else "2 cartas laborales membretadas"
        traslado_line = "" if is_local else "Traslado: Foráneo (requiere validar viáticos y alojamiento)\n"
        scenario = "Perfil Listo — Candidato Local ZM Laguna" if is_local else "Perfil Listo — Candidato Foráneo"
        return (
            f"{_nota_header(scenario)}\n\n"
            f"Último mensaje: \"{message}\"\n\n"
            f"{_nota_contacto(lead, facts)}\n\n"
            "📌 Estado del candidato\n"
            f"Perfil de operador completo. {'Local de ZM Laguna.' if is_local else 'Candidato foráneo.'}\n\n"
            "✅ Lo que ya sabemos\n"
            f"Ciudad: {city}\n"
            f"Edad: {age}\n"
            f"Unidad: {vt_display}\n"
            f"Experiencia: {years}\n"
            f"Licencia: {_human_fact(license_category)}" + (f" · {_exp_display(license_exp_text)}" if license_exp_text else "") + "\n"
            f"Apto médico: {_apto_status_display(medical_status_raw, apto_exp_text)}" + (f" · {_exp_display(apto_exp_text)}" if apto_exp_text else "") + "\n"
            f"Documento laboral: {doc_display}\n"
            f"{traslado_line}\n"
            + llamada_block +
            "👥 Para Capital Humano\n"
            "Validar documentos y continuar proceso de contratación.\n"
            "Requiere Agente: Sí\n\n"
            "⏭️ Siguiente acción\n"
            f"{_next_action_dinamica(facts, is_local, lbl)}"
        )

    # ── 4.1 Formato base: candidato en perfilamiento ──────────────────────────
    sabemos: list[str] = []
    if name:
        sabemos.append(f"Nombre: {name}")
    if has_city:
        sabemos.append(f"Ciudad: {city}")
    if age and age != PENDING_TEXT:
        sabemos.append(f"Edad: {age}")
    if has_vt:
        sabemos.append(f"Unidad: {vt_display}")
    if has_years:
        sabemos.append(f"Experiencia: {years}")
    if has_lic:
        lic_line = f"Licencia: {_human_fact(license_category)}"
        if license_exp_text:
            lic_line += f" · {_exp_display(license_exp_text)}"
        sabemos.append(lic_line)
    if has_apto:
        apto_line = f"Apto médico: {_apto_status_display(medical_status_raw, apto_exp_text)}"
        if apto_exp_text:
            apto_line += f" · {_exp_display(apto_exp_text)}"
        sabemos.append(apto_line)
    if has_doc:
        sabemos.append(f"Documentos: {_human_fact(proof_raw)}")

    falta: list[str] = []
    if not has_city:
        falta.append("Ciudad de residencia")
    if not age or age == PENDING_TEXT:
        falta.append("Edad")
    if not has_vt:
        falta.append("Tipo de unidad (tracto full o sencillo)")
    if not has_years:
        falta.append("Años de experiencia")
    if not has_lic:
        falta.append("Licencia federal (tipo y vigencia)")
    if not has_apto:
        falta.append("Apto médico (vigencia)")
    if not has_doc:
        doc_req = "Cartas laborales o semanas IMSS" if is_local else "2 cartas laborales membretadas"
        falta.append(f"Documento laboral: {doc_req}")

    falta_block = ""
    if falta:
        falta_block = "⚠️ Falta confirmar\n" + "\n".join(f"· {f}" for f in falta) + "\n\n"

    sabemos_block = ("✅ Lo que ya sabemos\n" + "\n".join(sabemos) + "\n\n") if sabemos else ""

    estado = "Candidato interesado, sin datos de perfil aún." if not sabemos else "Candidato en proceso de perfilamiento."
    scenario = "Candidato en Perfilamiento"

    return (
        f"{_nota_header(scenario)}\n\n"
        f"Último mensaje: \"{message}\"\n\n"
        f"{_nota_contacto(lead, facts)}\n\n"
        "📌 Estado del candidato\n"
        f"{estado}\n\n"
        + sabemos_block
        + falta_block
        + llamada_block
        + "👥 Para Capital Humano\n"
        "Esperar a que el candidato complete su perfil.\n"
        f"Requiere Agente: {requiere_agente}\n\n"
        "⏭️ Siguiente acción\n"
        f"{_next_action_dinamica(facts, is_local, lbl)}"
    )


async def _chatwoot_post(path: str, body: dict[str, Any]) -> dict[str, Any]:
    base_url = os.getenv("CHATWOOT_BASE_URL", "").strip().rstrip("/")
    token = os.getenv("CHATWOOT_API_TOKEN", "").strip()
    if not base_url:
        raise RuntimeError("CHATWOOT_BASE_URL is not configured")
    if not token:
        raise RuntimeError("CHATWOOT_API_TOKEN is not configured")
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{base_url}{path}",
            headers={"api_access_token": token, "Content-Type": "application/json"},
            json=body,
        )
        response.raise_for_status()
        return response.json()


async def sync_chatwoot_candidate_note(*, lead_key: str, account_id: int | str, conversation_id: int | str, fallback_last_message: str | None = None, channel_label: str | None = None) -> dict[str, Any]:
    context = get_lead_note_context(lead_key)
    if not context.get("lead"):
        return {"ok": False, "skipped": True, "reason": "lead_not_found", "lead_key": lead_key}

    labels = calculate_candidate_labels(context)
    note = render_candidate_note(context, labels, fallback_last_message=fallback_last_message, channel_label=channel_label)

    note_response = await _chatwoot_post(
        f"/api/v1/accounts/{account_id}/conversations/{conversation_id}/messages",
        {"content": note, "message_type": "outgoing", "private": True},
    )
    labels_response = await _chatwoot_post(
        f"/api/v1/accounts/{account_id}/conversations/{conversation_id}/labels",
        {"labels": labels},
    )

    return {
        "ok": True,
        "lead_key": lead_key,
        "labels": labels,
        "note_message_id": note_response.get("id"),
        "labels_response": labels_response,
    }
