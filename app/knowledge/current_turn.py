import datetime
import json
import os
import random
import re
from typing import Any

from app.knowledge.business_hours import is_business_hours
from app.knowledge.text_normalizer import normalize_text

# Conectores breves y VARIADOS para la transición del funnel (sin eco de datos).
# Desde FUNNEL_LLM_TRANSITIONS son SOLO la degradación determinista (D8): el acuse
# primario lo genera el LLM situado; el saludo con nombre va aparte.
_FUNNEL_CONNECTORS: tuple[str, ...] = (
    "Va.", "Perfecto.", "Listo.", "Muy bien.", "De acuerdo.", "Bien.", "Claro.",
)


def generate_funnel_transition_reply(
    message: str | None,
    fresh_facts: dict[str, Any] | None,
    question: str,
    fallback: str,
) -> str:
    """Acuse + siguiente pregunta del funnel GENERADOS por el LLM situado.

    Feedback usuario 2026-07-09: el conector enlatado ("Va.") + pregunta pegada se
    siente robótico. Con contexto (mensaje del candidato, datos capturados este
    turno y el ÚNICO dato faltante) el LLM reconoce lo compartido y redirige al
    funnel en una sola respuesta natural, sin re-preguntar lo ya dado. La pregunta
    del funnel sigue siendo deterministra en CONTENIDO (qué dato se pide y en qué
    orden); el LLM solo la reformula. Gate por env FUNNEL_LLM_TRANSITIONS (default
    off) para no volver no-deterministas los caminos existentes; ante flag off,
    fallo del LLM o salida inválida (vacía, sin pregunta, desbordada) degrada al
    conector enlatado + pregunta literal (D8: enlatado = fallback, nunca primario).
    """
    if os.getenv("FUNNEL_LLM_TRANSITIONS", "false").lower() not in {"1", "true", "yes"}:
        return fallback
    try:
        from app.gemini_client import dispatch_generation
        from app.persona_config import SYSTEM_PROMPT

        datos = "; ".join(
            f"{k}: {v}" for k, v in (fresh_facts or {}).items() if v
        ) or "(ninguno nuevo)"
        prompt = (
            f"El candidato acaba de escribir: «{(message or '').strip()[:400]}».\n"
            f"Datos que el sistema ya capturó y guardó de ese mensaje: {datos}.\n"
            f"Único dato que falta pedirle ahora: «{question}»\n"
            "Redacta la respuesta de Mundo en 1-2 frases: reconoce breve y natural lo que "
            "compartió (sin repetirle dato por dato, sin eco literal, sin prometer "
            "contratación ni evaluar si califica) y cierra pidiendo ÚNICAMENTE ese dato "
            "faltante — puedes reformular la pregunta con naturalidad, pero pide ese mismo "
            "dato y ningún otro. No vuelvas a preguntar nada que ya haya proporcionado. "
            "Voz: Mundo habla en PRIMERA PERSONA DEL SINGULAR y trata de usted "
            "(\"¿Me podría indicar...?\") — nunca plural corporativo (\"indicarnos\", "
            "\"necesitamos\") ni tuteo."
        )
        out = (dispatch_generation(SYSTEM_PROMPT, prompt, temperature=0.6, max_tokens=160) or "").strip()
        if not out or ("?" not in out and "¿" not in out) or len(out) > 500:
            return fallback
        return out
    except Exception:
        return fallback



def _profile_complete_closing(facts: dict[str, Any] | None = None) -> str:
    """Cierre cuando el perfil conversacional está completo. Ligero, sin recordatorios
    redundantes (feedback usuario 2026-07-03): acusa el avance y pasa al siguiente paso
    (subir documentos) de forma breve. `facts` permite adaptar el mensaje (etapa visión)."""
    en_horario = is_business_hours()
    msg = (
        "¡Listo! Con esto completamos tu perfil. El siguiente paso es subir tus documentos "
        "(licencia federal, apto médico y tu comprobante laboral) para validarlos."
    )
    if en_horario:
        msg += " En cuanto los tengamos, nuestro equipo continúa con tu proceso."
    else:
        msg += (
            " Puedes subirlos cuando gustes; nuestro horario es de lunes a viernes de 08:00 a "
            "17:30 hrs (centro de México) y en cuanto arranque el equipo seguimos."
        )
    return msg


from app.knowledge.geo_utils import normalize_zm_laguna_city, is_zm_laguna_canonical


def residency_is_local(facts: dict[str, Any]) -> bool:
    """Fuente ÚNICA de residencia local/foránea: el catálogo ZM Laguna.

    Usa la señal canónica ``location.is_local_laguna`` (derivada del catálogo
    aguas arriba) y, como respaldo robusto cuando esa señal no fue computada
    (p. ej. en la ruta del orquestador), evalúa la ciudad directamente contra
    el catálogo. No se usan listas de ciudades hardcodeadas.
    """
    if facts.get("location.is_local_laguna") == "true":
        return True
    # Normaliza alias coloquial → canónico antes de evaluar (p. ej. "Chávez" →
    # Francisco I. Madero), para no depender de que la ciudad ya venga normalizada.
    city = normalize_zm_laguna_city(facts.get("candidate.city") or "")
    return is_zm_laguna_canonical(city)


def residency_document_question(facts: dict[str, Any]) -> str:
    """Pregunta de documento laboral según residencia (regla de dominio única).

    Local ZM Laguna → acepta semanas cotizadas del IMSS; foráneo → 2 cartas
    laborales membretadas. Si el candidato ya negó tener cartas
    (``documents.proof == "ninguno"``) ofrece la alternativa local o cierra sin
    loop para foráneo. Voz de equipo (sin "Capital Humano" como tercero).
    """
    is_local = residency_is_local(facts)
    proof = facts.get("documents.proof")
    if proof == "ninguno":
        if is_local:
            return "¿Cuenta con su documento de semanas cotizadas del IMSS?"
        return (
            "Para candidatos foráneos necesitamos 2 cartas laborales membretadas. "
            "Si consigue ese documento, con gusto retomamos. Lo dejo anotado para que "
            "nuestro equipo le indique opciones al contactarle."
        )
    if is_local:
        return "¿Cuenta con cartas laborales o semanas cotizadas del IMSS?"
    return "¿Cuenta con 2 cartas laborales membretadas de sus empleos anteriores?"


def residency_document_requirement_note(facts: dict[str, Any]) -> str:
    """Explicación breve del requisito documental alineada al estado del funnel.

    Cuando la residencia ya es conocida, devuelve solo la política aplicable a ese
    candidato. Si aún no se conoce, devuelve una explicación condicional que no se
    contradice con ninguna de las dos ramas.
    """
    has_signal = facts.get("location.is_local_laguna") in {"true", "false"} or bool(facts.get("candidate.city"))
    if has_signal:
        if residency_is_local(facts):
            return "Si es local de la ZM Laguna, aceptamos cartas laborales membretadas o semanas cotizadas del IMSS."
        return "Para candidatos foráneos necesitamos 2 cartas laborales membretadas."
    return (
        "Si es local de la ZM Laguna, aceptamos cartas laborales membretadas o semanas cotizadas del IMSS; "
        "si es foráneo, necesitamos 2 cartas laborales membretadas."
    )


def vehicle_vacancy_question(facts: dict[str, Any]) -> str:
    """Pregunta de unidad/vacante condicionada por la licencia conocida."""
    cat = (facts.get("license.category") or "").upper()
    if cat == "B":
        return (
            "Con licencia tipo B revisamos vacantes de operador sencillo. "
            "¿Tiene experiencia en sencillo?"
        )
    if cat == "E":
        return (
            "Con licencia tipo E podemos revisar vacantes de sencillo o de full "
            "(doble articulado). ¿En cuál tiene experiencia?"
        )
    return (
        "Le comento, actualmente tenemos vacantes para operador sencillo y para tracto "
        "full (doble articulado). ¿En cuál tiene experiencia?"
    )


def license_requirement_question(facts: dict[str, Any]) -> str:
    """Pregunta de licencia condicionada por el tipo de unidad ya conocido."""
    vehicle = normalize_text(str(facts.get("experience.vehicle_type") or ""))
    if vehicle == "full":
        return "Para vacante de full necesitamos licencia federal tipo E. ¿Cuenta con licencia tipo E y cuándo vence?"
    if vehicle == "sencillo":
        return "Para vacante de sencillo puede aplicar con licencia federal tipo B o E. ¿Qué tipo de licencia tiene y cuándo vence?"
    return "¿Qué tipo de licencia federal tiene y cuándo vence?"

from app.settings import AGE_DISQUALIFICATION_LIMIT as AGE_LIMIT_EXCLUSIVE
RENEWAL_PROOF_QUESTION = (
    "Para continuar con su {documento}, como alternativa aceptamos el comprobante "
    "de pago de su renovación o trámite. ¿Ya cuenta con ese comprobante?"
)
RENEWAL_PROOF_REQUIRED_REPLY = (
    "Entiendo. Para continuar necesitamos el comprobante de pago de su renovación o "
    "trámite. En cuanto lo tenga, seguimos con su registro."
)

_NUMBER_WORDS = {
    "un": 1,
    "una": 1,
    "uno": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
}


def _to_int(value: Any) -> int | None:
    text = normalize_text(str(value or "")).strip()
    if text.isdigit():
        return int(text)
    m = re.search(r"\b(\d{1,2})\b", text)
    if m:
        return int(m.group(1))
    return None


def is_age_disqualified(facts: dict[str, Any]) -> bool:
    age = _to_int(facts.get("candidate.age"))
    return age is not None and age >= AGE_LIMIT_EXCLUSIVE


def age_disqualification_reply(age: int | None = None) -> str:
    from app.gemini_client import dispatch_generation
    from app.persona_config import SYSTEM_PROMPT
    context = (
        f"El candidato indicó que tiene {age} años. " if age else ""
    )
    prompt = (
        f"{context}Aplica la regla de descalificación por edad del perfil de operador. "
        "Genera únicamente el mensaje de respuesta al candidato."
    )
    try:
        out = (dispatch_generation(SYSTEM_PROMPT, prompt, temperature=0.1, max_tokens=120) or "").strip()
        if out:
            return out
    except Exception:
        pass
    # Degradación determinista (dispatch_generation propaga ante fallo de Gemini):
    # el candidato SIEMPRE recibe el mensaje de descalificación, nunca un error.
    return (
        "Le agradecemos mucho su interés en Transmontes. Por política del perfil de "
        "operador no podemos continuar con su proceso en esta vacante. Le deseamos "
        "mucho éxito."
    )


def _number_token_to_int(token: str) -> int | None:
    token = normalize_text(token)
    if token.isdigit():
        return int(token)
    return _NUMBER_WORDS.get(token)


def _expiry_within_three_months(expiration_text: Any) -> bool:
    t = normalize_text(str(expiration_text or ""))
    if not t:
        return False
    # "vencio" cubre "venció/se venció/ya venció" (verbo en pasado, ya vencido); NO
    # matchea "vence en 2 años" (presente/futuro). "vencido/vencida" cubren el adjetivo.
    if any(word in t for word in ("vencido", "vencida", "vencio", "caducado", "caducada", "caduco")):
        return True
    m = re.search(
        r"\b(\d{1,2}|un|una|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\s+"
        r"(dias?|semanas?|mes(?:es)?)\b",
        t,
    )
    if not m:
        return False
    amount = _number_token_to_int(m.group(1))
    unit = m.group(2)
    if amount is None:
        return False
    if unit.startswith("dia") or unit.startswith("semana"):
        return True
    if unit.startswith("mes"):
        return amount <= 3
    return False


# No-respuestas / evasivas que NO constituyen un vencimiento válido. Se tratan como
# dato faltante: el confirm no afirma "vigente", el funnel vuelve a pedir el dato y
# perfil_listo no se activa. Lista acotada y normalizada; ante texto ambiguo se
# PREFIERE aceptar para no meter al candidato en bucle (design D5/risk) — solo se
# rechaza lo que es claramente una no-respuesta.
_EXPIRATION_NON_ANSWERS = (
    "no sabria", "no se", "no lo se", "no sabe", "no me acuerdo", "no recuerdo",
    "ni idea", "quien sabe", "sabra dios", "no estoy segur", "no tengo idea",
    "al rato", "mas al rato", "luego le digo", "luego te digo", "despues le digo",
    "despues te digo", "ahorita le digo", "ahorita te digo", "te digo al rato",
)


def is_valid_expiration_text(text: Any) -> bool:
    """True si ``text`` puede contar como respuesta de vencimiento (fecha/plazo,
    estado de vigencia, o cualquier texto que NO sea una no-respuesta explícita).
    Una no-respuesta/evasiva ("no sabría decirle", "al rato le digo", vacío) es
    inválida → el dato se trata como faltante: no se afirma "vigente", el funnel lo
    vuelve a pedir y perfil_listo no se activa. No inventa fechas a partir de plazos."""
    t = normalize_text(str(text or "")).strip()
    if not t:
        return False
    return not any(na in t for na in _EXPIRATION_NON_ANSWERS)


def first_name(facts: dict[str, Any]) -> str:
    """Primer token de ``candidate.name`` capitalizado para trato natural
    ("Joaquín Ramos" → "Joaquín"); cadena vacía si no hay nombre (omite el vocativo
    en vez de fallar)."""
    raw = str((facts or {}).get("candidate.name") or "").strip()
    if not raw:
        return ""
    token = raw.split()[0]
    return token[:1].upper() + token[1:].lower() if token else ""


def _renewal_proof_state(facts: dict[str, Any], document_key: str) -> str:
    specific = facts.get(f"{document_key}.renewal_proof")
    general = facts.get("documents.renewal_proof")
    return normalize_text(str(specific or general or ""))


def _renewal_question_for_short_expiry(facts: dict[str, Any]) -> str | None:
    checks = (
        ("license.expiration_text", "license", "licencia federal"),
        ("medical.apto_expiration_text", "medical", "apto médico"),
    )
    for exp_key, proof_key, label in checks:
        if _expiry_within_three_months(facts.get(exp_key)):
            proof = _renewal_proof_state(facts, proof_key)
            if proof in {"no", "nel", "nop", "ninguno", "sin papel", "sin comprobante"}:
                # 3.3: marcar cierre suave por vencido-sin-trámite (bot deja de empujar funnel)
                facts["funnel.status"] = "vencido_sin_tramite"
                return RENEWAL_PROOF_REQUIRED_REPLY
            if proof not in {"si", "sí", "yes", "true", "tengo", "ya tengo"}:
                return RENEWAL_PROOF_QUESTION.format(documento=label)
    return None


def _has_labor_document(facts: dict[str, Any]) -> bool:
    return (
        facts.get("documents.labor_letters") in {"sí", "si", "available"}
        or facts.get("documents.labor_letters_status") in {"available", "sí", "si"}
        or facts.get("documents.proof") in {"cartas", "semanas_imss", "sí", "si"}
    )


def canonicalize_proof(value: Any) -> str | None:
    """Normaliza cualquier valor de ``documents.proof`` al vocabulario canónico
    ``{"cartas" | "semanas_imss" | "ninguno"}`` antes de persistir.

    El contrato del extractor pide estos valores, pero el LLM a veces devuelve
    texto libre ("cartas laborales", "semanas del IMSS"); sin esto, los
    consumidores deterministas (``_has_labor_document``) no lo reconocen y el
    paso documental nunca cierra (loop de re-pregunta). Devuelve ``None`` cuando
    el valor no es mapeable, para no persistir texto crudo."""
    if value is None:
        return None
    v = normalize_text(str(value)).strip()
    if not v:
        return None
    if v in {"cartas", "semanas_imss", "ninguno"}:
        return v
    # Negaciones explícitas → ninguno
    if any(t in v for t in ("ninguno", "ninguna", "no tengo", "no cuento", "sin ")):
        return "ninguno"
    # Semanas cotizadas del IMSS
    if "imss" in v or "semanas" in v or "cotizad" in v:
        return "semanas_imss"
    # Cartas laborales / membretadas / documento laboral
    if any(t in v for t in ("carta", "membret", "documento laboral", "documentos laborales", "laboral")):
        return "cartas"
    return None


# Detect the topic of the last bot question for context-aware "si" interpretation
# Señal estructural de pregunta cuantitativa embebida: "cuántas necesita",
# "cuánto pagan", etc. OR-fallback para cuando TIPC no clasifica has_embedded_question.
_EMBEDDED_Q_SIGNAL = re.compile(
    r"(?:cuantos?|cuantas?|cuanto\s+es|cuanto\s+queda|cuanto\s+vale)\s+",
    re.IGNORECASE,
)

# Sustantivos-tema RAG-contestables (pago, rutas, documentos, licencia, apto…).
# Origen ÚNICO: el orquestador reimporta desde aquí (evita dos listas divergentes).
BUSINESS_QUESTION_TERMS: tuple[str, ...] = (
    "pago", "pagan", "sueldo", "salario", "documento", "documentos", "papeles",
    "requisitos", "licencia", "apto", "ruta", "rutas", "vacante", "vacantes",
    "antidoping", "prueba", "orina", "base", "bases",
)


def _message_has_any(message: str | None, terms: tuple[str, ...]) -> bool:
    text = normalize_text(message or "")
    return any(normalize_text(term) in text for term in terms)

_TOPIC_APTO = re.compile(r"\bapto\b", re.IGNORECASE)
_TOPIC_LICENSE_VIGENTE = re.compile(
    r"\blicencia\b.{0,80}(?:\bvigente\b|\bvigencia\b|\bal\s+corriente\b)"
    r"|(?:\bvigente\b|\bvigencia\b).{0,80}\blicencia\b",
    re.IGNORECASE | re.DOTALL,
)
_TOPIC_LETTERS = re.compile(r"\bcartas?\s+laborales?\b", re.IGNORECASE)
# Pregunta de comprobante/papel de renovación ("¿Ya tiene el papel o comprobante de
# renovación?"). Cubre "comprobante de renovacion" y "papel ... renovacion".
_TOPIC_RENEWAL_PROOF = re.compile(
    r"\b(?:comprobante|papel|tramite|trámite)\b.{0,40}\brenovaci",
    re.IGNORECASE | re.DOTALL,
)


def _extract_context_confirmation_facts(norm_message: str, last_bot_message: str, _turn_signals=None) -> dict[str, Any]:
    """Infer profile facts when the candidate gives a short affirmation.

    Example: bot asks '¿Tu apto médico está vigente?' and candidate replies
    'si de hace 6 meses me queda todavia' → infer medical.apto_status=vigente.
    """
    t = norm_message.strip()

    # Negaciones / desinterés: si aparecen, NO se interpreta como confirmación.
    # Cubre "ya no", "ya conseguí trabajo", "ya me hablaron de otro trabajo", etc.
    _neg_hints = {
        "no", "nel", "nop", "tampoco", "nunca",
        "otro", "otra",
        "consegui", "conseguí", "encontre", "encontré",
        "vencido", "vencida", "vencio", "venció", "caducado", "caducada",
    }
    has_negation = any(tok in _neg_hints for tok in t.split())

    # "si" CONDICIONAL (if), no afirmativo: "si me cuentas un chiste te digo..."
    # no confirma nada — sin esta guarda, el guard infería license.status=vigente
    # y pisaba la respuesta correcta (smoke 2026-06-12 19:46). Acotado a
    # pronombre+verbo de petición para NO bloquear confirmaciones reales tipo
    # "si me queda todavia un año".
    _conditional_si = bool(re.match(
        r"^si\s+(?:me|te|le|nos|les|usted|tu)\s+"
        r"(?:cuenta|cuentas|dice|dices|da|das|pasa|pasas|explica|explicas|manda|mandas|dan|dicen)\b",
        t,
    ))
    strong_yes = not _conditional_si and (
        t == "si"
        or (t.startswith("si ") and not t.startswith("si no "))
        or t.startswith("si,")
        or t.startswith("claro")
        or t.startswith("correcto")
        or t.startswith("exacto")
        or t in {"simon", "sip"}
    )
    # "ya" de RECLAMO no es confirmación: "ya le habia dicho que 10 años".
    # Guarda estructural: bare "ya" nunca es reclamo; solo cuando va seguido de
    # texto puede serlo. TIPC clasifica la intención dentro de ese sub-caso.
    _ya_reclamo = False
    if t.startswith("ya "):
        if _turn_signals is not None:
            _ya_reclamo = _turn_signals.is_ya_reclamo
        else:
            try:
                from app.knowledge.turn_intent_classifier import classify_turn_intent
                _ya_reclamo = classify_turn_intent(norm_message).is_ya_reclamo
            except Exception:
                _ya_reclamo = False
    # Confirmaciones suaves/ambiguas: solo válidas si no hay negación en el mensaje.
    soft_yes = not _ya_reclamo and (
        t in {"ok", "okay", "oka", "va", "sale", "dale", "ya"}
        or t.startswith(("ok ", "va ", "sale ", "dale ", "ya "))
    )
    # La negación bloquea cualquier confirmación (incluye "si no, ...").
    is_yes = (strong_yes or soft_yes) and not has_negation
    _asks_renewal = bool(_TOPIC_RENEWAL_PROOF.search(last_bot_message))
    _is_summary_prompt = bool(_TOPIC_SUMMARY_CONFIRM.search(last_bot_message))
    _summary_yes = _is_summary_prompt and not has_negation and (
        is_yes or _is_summary_affirmation(t) or _llm_summary_affirmation(t)
    )
    if _is_summary_prompt:
        return {"funnel.summary_confirmed": "true"} if _summary_yes else {}
    if not is_yes and not _summary_yes:
        # Negación corta a la pregunta de comprobante de renovación → "no".
        # (El resto de campos no se infiere desde una negación corta.)
        if _asks_renewal and has_negation:
            return {"documents.renewal_proof": "no"}
        return {}

    facts: dict[str, Any] = {}
    if _TOPIC_APTO.search(last_bot_message):
        facts["medical.apto_status"] = "vigente"
    if _TOPIC_LICENSE_VIGENTE.search(last_bot_message):
        facts["license.status"] = "vigente"
    if _TOPIC_LETTERS.search(last_bot_message):
        facts["documents.labor_letters"] = "sí"
    if _asks_renewal:
        facts["documents.renewal_proof"] = "si"
    # Resumen de confirmación (gemini-natural-recruiter D6): "sí/correcto" al
    # "¿Es correcto?" confirma los datos registrados y habilita el cierre.
    return facts


def is_question(text: str | None) -> bool:
    raw = text or ""
    norm = normalize_text(raw)
    if "?" in raw or "¿" in raw:
        return True
    return bool(re.match(r"^(cuanto|cuanta|cuantos|cuantas|cuando|donde|que|como|cual|pagan|tienen|hay|manejan)\b", norm))


def extract_current_turn_facts(message: str | None, last_bot_message: str | None = None, turn_signals=None) -> dict[str, Any]:
    """Dict view of profile facts for the debounce guard in tasks_chatwoot.

    Delegates extraction to profile_extractor (single source of truth) and adds
    the debounce-specific fields: interest.payment, interest.routes,
    location.is_local_laguna.

    When last_bot_message is provided, also infers facts from short confirmations
    ("si", "claro") based on what the bot last asked.
    """
    from app.lead_memory.profile_extractor import extract_profile_facts_as_dict

    raw = (message or "").strip()
    if not raw:
        return {}

    if turn_signals is None:
        try:
            from app.knowledge.turn_intent_classifier import classify_turn_intent
            turn_signals = classify_turn_intent(raw)
        except Exception:
            from app.knowledge.turn_intent_classifier import TurnIntentSignals
            turn_signals = TurnIntentSignals()

    facts = extract_profile_facts_as_dict(raw, turn_signals=turn_signals)
    text = normalize_text(raw)

    # Context-aware: infer field from "si" when we know what was last asked
    if last_bot_message:
        for k, v in _extract_context_confirmation_facts(text, last_bot_message, _turn_signals=turn_signals).items():
            if k not in facts:
                facts[k] = v

        # BUG-2: bare negation after docs/cartas question → proof = ninguno (deterministic)
        _bare_neg = text in {"no", "nop", "nel", "nope", "para nada", "tampoco", "negativo", "no tengo", "no cuento"}
        _last_norm_docs = normalize_text(last_bot_message)
        if (_bare_neg
                and any(w in _last_norm_docs for w in ("cartas", "membretadas", "documentos laborales", "documento laboral"))
                and "documents.proof" not in facts):
            facts["documents.proof"] = "ninguno"

        # BUG-3: "igual / los dos" after apto question → inherit license expiration (deterministic)
        _last_norm_apto = normalize_text(last_bot_message)
        _asks_apto = "apto" in _last_norm_apto and ("vence" in _last_norm_apto or "vigencia" in _last_norm_apto)
        _same_as_hints = ("igual", "mismo", "los dos", "ambos", "los 2", "tambien", "también",
                          "al mismo tiempo", "igual que", "igualmente", "los dos vencen")
        if (_asks_apto and any(h in text for h in _same_as_hints)
                and "medical.apto_expiration_text" not in facts):
            _lic_exp = facts.get("license.expiration_text")
            if _lic_exp:
                facts["medical.apto_expiration_text"] = _lic_exp

        # 3.1: extracción de nombre cuando last_bot lo pidió
        _last_norm_name = normalize_text(last_bot_message)
        _asks_name = "nombre" in _last_norm_name and "?" in last_bot_message
        if _asks_name and "candidate.name" not in facts:
            _name_patterns = [
                re.search(r"\bme\s+llamo\s+([A-ZÁÉÍÓÚÜÑa-záéíóúüñ]{2,}(?:\s+[A-ZÁÉÍÓÚÜÑa-záéíóúüñ]{2,})?)", raw, re.IGNORECASE),
                re.search(r"\bsoy\s+([A-ZÁÉÍÓÚÜÑa-záéíóúüñ]{2,}(?:\s+[A-ZÁÉÍÓÚÜÑa-záéíóúüñ]{2,})?)", raw, re.IGNORECASE),
                re.search(r"\bmi\s+nombre\s+es\s+([A-ZÁÉÍÓÚÜÑa-záéíóúüñ]{2,}(?:\s+[A-ZÁÉÍÓÚÜÑa-záéíóúüñ]{2,})?)", raw, re.IGNORECASE),
            ]
            _name_skip = {
                "si", "no", "nel", "nop", "ok", "va", "dale", "sale", "claro", "exacto",
                "hola", "ola", "buenas", "buenos", "buen", "hey", "gracias", "perfecto",
                "listo", "entendido", "correcto", "anotado", "registrado",
                "full", "sencillo", "tracto", "torton", "rabon",
            }
            _name_found = False
            for _nm in _name_patterns:
                if _nm:
                    _cand = _nm.group(1).strip().title()
                    if _cand.lower() not in _name_skip and len(_cand) >= 3:
                        facts["candidate.name"] = _cand
                        _name_found = True
                    break
            if not _name_found:
                # Respuesta corta sin verbo = nombre directo (ej: "Juan García")
                _words = raw.strip().split()
                _candidate_name = raw.strip().title()
                if (1 <= len(_words) <= 3
                        and all(w[0].isupper() or w[0].isalpha() for w in _words if w)
                        and _candidate_name.lower() not in _name_skip
                        and len(_candidate_name) >= 3):
                    facts["candidate.name"] = _candidate_name
                    _name_found = True
            # no LLM fallback — unified extractor (worker path) handles mixed messages

    # Fields only needed by the debounce guard, not persisted to lead_memory.
    if any(t in text for t in ("cuanto pagan", "pago", "sueldo", "compensacion", "kilometro", "km")):
        facts["interest.payment"] = "asked"
    if any(t in text for t in ("que rutas", "rutas tienen", "bases", "cedis")):
        facts["interest.routes"] = "asked"

    raw_city = facts.get("candidate.city") or ""
    if raw_city:
        facts["candidate.city"] = normalize_zm_laguna_city(raw_city)
    facts["location.is_local_laguna"] = "true" if is_zm_laguna_canonical(facts.get("candidate.city") or "") else "false"

    return facts


# Entradas de campaña/interés (incluye el mensaje default de la publicación de
# Facebook). El interés NO es un dato de perfil: detona la apertura, no el ack.
CAMPAIGN_INTEREST_TERMS = (
    "me interesa la vacante",
    "me interesa la vancate",
    "me interesa la bacante",
    "me interesa la bakante",
    "me interesa el puesto",
    "me interesa el trabajo",
    "me interesa la chamba",
    "informacion de la vacante",
    "info de la vacante",
    "informes de la vacante",
)


def is_campaign_or_interest_entry(message: str | None) -> bool:
    """True si el mensaje es una entrada de campaña/interés sin pregunta.

    En primer contacto debe responderse con el saludo oficial de Mundo, nunca
    con el ack del guard ("Perfecto, lo dejo registrado").
    """
    if is_question(message):
        return False
    t = normalize_text(message or "")
    return any(term in t for term in CAMPAIGN_INTEREST_TERMS)


# Facts que NO cuentan como señal de perfil para el guard: el interés en la
# vacante no es un dato del candidato (regla de negocio 2026-06-12).
_NON_PROFILE_SIGNAL_KEYS = {"candidate.vacancy_accepted"}


def has_current_turn_profile_signal(message: str | None, last_bot_message: str | None = None) -> bool:
    facts = extract_current_turn_facts(message, last_bot_message)
    # location.is_local_laguna is always computed — exclude it from the signal check
    return any(
        key.startswith(("candidate.", "license.", "medical.", "documents.", "experience."))
        and key not in _NON_PROFILE_SIGNAL_KEYS
        for key in facts
    )


def has_embedded_business_question(message: str | None, turn_signals=None) -> bool:
    """True si el mensaje contiene una pregunta de negocio embebida (sin "?").

    Consume turn_signals.has_embedded_question cuando está disponible.
    OR-fallback: _EMBEDDED_Q_SIGNAL cubre casos que TIPC puede subestimar
    (e.g. "cuántas necesita?").
    Sin turn_signals: llama al TIPC internamente (compat tests).
    """
    text = normalize_text(message or "")
    if not text:
        return False
    if _EMBEDDED_Q_SIGNAL.search(text):
        return True
    if turn_signals is not None:
        return bool(turn_signals.has_embedded_question)
    try:
        from app.knowledge.turn_intent_classifier import classify_turn_intent
        return classify_turn_intent(message or "").has_embedded_question
    except Exception:
        return False


def has_business_question(message: str | None, turn_signals=None) -> bool:
    """Detector ÚNICO de pregunta de negocio contestable en el turno.

    (unified-turn-decision-v2-projection, Fase 2 / D5 — raíz del bug #3.)

    Superset de los tres mecanismos que antes decidían por separado y en
    desacuerdo (auditoría):
      1. `is_question` — signo `?`/`¿` y aperturas interrogativas.
      2. sustantivos-tema (`BUSINESS_QUESTION_TERMS`) — lo que usaba el orquestador
         (`_looks_like_question`).
      3. `has_embedded_business_question` — señal LLM (`turn_signals`) + regex de
         cantidad + fallback TIPC — lo que usaba el guard del worker.

    Con esto, guard y orquestador consultan el MISMO detector y coinciden. Cubre el
    caso "compuesto sin `?` ni término conocido" vía la señal LLM (mecanismo 3) cuando
    el caller ya la tiene (worker). NUNCA dispara un LLM fresco: sin `turn_signals` es
    determinista (gate barato para el orquestador).
    """
    if not (message or "").strip():
        return False
    if is_question(message) or _message_has_any(message, BUSINESS_QUESTION_TERMS):
        return True
    if _EMBEDDED_Q_SIGNAL.search(normalize_text(message or "")):
        return True
    if turn_signals is not None:
        return bool(getattr(turn_signals, "has_embedded_question", False))
    return False


def should_prioritize_current_turn(message: str | None, last_bot_message: str | None = None) -> bool:
    """Evita que RAG/memoria pisen una respuesta clara del candidato."""
    if is_question(message) or has_embedded_business_question(message):
        return False
    return has_current_turn_profile_signal(message, last_bot_message)


def _next_funnel_question_or_none(facts: dict[str, Any]) -> str | None:
    """Fuente única del estado del funnel: devuelve la siguiente pregunta pendiente,
    o ``None`` cuando el perfilamiento conversacional está agotado. `next_question_
    from_missing_facts` y `profile_funnel_complete` derivan de aquí para no divergir."""
    if not facts.get("candidate.name"):
        return "¿Me podría decir su nombre y apellido, por favor?"
    if not facts.get("candidate.city"):
        return "¿En qué ciudad se encuentra actualmente?"
    if not facts.get("candidate.age"):
        return "¿Cuántos años tiene?"
    if is_age_disqualified(facts):
        return age_disqualification_reply(_to_int(facts.get("candidate.age")))
    if not facts.get("experience.vehicle_type"):
        return vehicle_vacancy_question(facts)
    if not facts.get("license.category"):
        return license_requirement_question(facts)
    if not is_valid_expiration_text(facts.get("license.expiration_text")):
        return "¿En cuánto tiempo se le vence su licencia federal?"
    renewal_question = _renewal_question_for_short_expiry(facts)
    if renewal_question:
        return renewal_question
    if not is_valid_expiration_text(facts.get("medical.apto_expiration_text")):
        return "¿Cuándo vence su apto médico?"
    renewal_question = _renewal_question_for_short_expiry(facts)
    if renewal_question:
        return renewal_question
    if not facts.get("experience.years"):
        return "Perfecto. ¿Cuántos años de experiencia tiene como operador?"
    if not _has_labor_document(facts):
        # 2.5: documento por residencia — regla de dominio única (incl. P0-2 proof=ninguno)
        return residency_document_question(facts)
    return None


# Marker del resumen de confirmación: la afirmación del candidato se detecta por
# confirmación contextual contra este texto en el último mensaje del bot.
_TOPIC_SUMMARY_CONFIRM = re.compile(r"es correcto", re.IGNORECASE)

_SUMMARY_AFFIRMATIVE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^asi(?:\s+mero)?(?:\s+es)?$"),
    re.compile(r"^esta\s+bien$"),
    re.compile(r"^todo\s+(?:bien|correcto)$"),
    re.compile(r"^correctisimo$"),
)

_SUMMARY_FIELD_DISPLAY: tuple[tuple[str, str], ...] = (
    ("candidate.name", "Nombre"),
    ("candidate.city", "Ciudad"),
    ("candidate.age", "Edad"),
    ("experience.vehicle_type", "Unidad"),
    ("experience.years", "Experiencia"),
    ("license.category", "Licencia"),
    ("license.expiration_text", "Vence licencia"),
    ("medical.apto_expiration_text", "Vence apto médico"),
    ("documents.proof", "Comprobante laboral"),
)


def summary_confirmed(facts: dict[str, Any]) -> bool:
    return facts.get("funnel.summary_confirmed") == "true"


def _is_summary_affirmation(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    return any(pat.match(t) for pat in _SUMMARY_AFFIRMATIVE_PATTERNS)


def _llm_summary_affirmation(text: str) -> bool:
    t = normalize_text(text or "")
    if not t:
        return False
    tokens = t.split()
    if len(tokens) > 5:
        return False

    from app.gemini_client import dispatch_json

    system = (
        "Clasifica si la respuesta corta del candidato confirma afirmativamente un resumen "
        "de datos que el bot acaba de preguntar con '¿Es correcto?'. "
        "Responde SOLO JSON valido con esta forma exacta: "
        '{"affirmative": true|false}.'
    )
    prompt = (
        "Marca affirmative=true solo si la frase equivale claramente a "
        "'sí, mis datos están correctos'. "
        "Marca false si niega, corrige un dato, expresa duda o no confirma.\n"
        'Ejemplos true: "por su pollo", "of course", "clarines", "todo en orden".\n'
        'Ejemplos false: "no", "la ciudad esta mal", "mas o menos", "creo que si".\n'
        f'Respuesta del candidato: "{t}"'
    )
    try:
        raw = dispatch_json(prompt, system, temperature=0.0)
        data = json.loads(raw or "{}")
    except Exception:
        return False
    return data.get("affirmative") is True


def build_funnel_summary(facts: dict[str, Any]) -> str:
    """Resumen determinista de los datos registrados + '¿Es correcto?' (D6).

    Se emite UNA vez al completar el funnel, antes del cierre: red de seguridad para
    que el candidato corrija errores de transcripción/extracción antes de que el
    perfil avance a documentos.
    """
    _display_val = {"cartas": "cartas laborales", "semanas_imss": "semanas del IMSS"}
    lines = []
    for key, label in _SUMMARY_FIELD_DISPLAY:
        val = facts.get(key)
        if val:
            lines.append(f"· {label}: {_display_val.get(str(val), val)}")
    return (
        "¡Listo! Antes de continuar, le confirmo sus datos registrados:\n"
        + "\n".join(lines)
        + "\n¿Es correcto? Si algo está mal, dígame el dato y lo corrijo."
    )


def next_question_from_missing_facts(facts: dict[str, Any]) -> str:
    """Siguiente pregunta del funnel; al completarse, el RESUMEN de confirmación
    (una vez) y, ya confirmado, el mensaje de cierre."""
    question = _next_funnel_question_or_none(facts)
    if question is not None:
        return question
    if not summary_confirmed(facts):
        return build_funnel_summary(facts)
    return _profile_complete_closing()


def profile_funnel_complete(facts: dict[str, Any]) -> bool:
    """True si el funnel conversacional está agotado (no queda pregunta pendiente).
    Fuente única para el gate de `perfil_listo`: equivale a que
    `next_question_from_missing_facts` devolvería el cierre, no una pregunta."""
    return _next_funnel_question_or_none(facts) is None


def next_prehandoff_question(branch: str, facts: dict[str, Any]) -> str | None:
    """Retorna la pregunta de verificación previa al handoff, o None si el dato mínimo ya está.

    branch: 'escuelita' | 'cecati' | 'b1' | 'reingreso'
    facts: dict canónico de facts del lead (group.key → value)
    """
    lic = str(facts.get("license.category") or "").upper()
    has_be = lic in {"B", "E"}
    has_tramite = (
        facts.get("license.tramite_comprobante") == "true"
        or facts.get("medical.tramite_comprobante") == "true"
    )

    if branch in {"escuelita", "cecati"}:
        if has_be or has_tramite:
            return None  # dato mínimo confirmado → handoff puede proceder
        return (
            "Para considerar su candidatura, necesitamos saber si cuenta con "
            "licencia federal tipo B o E vigente (o comprobante de renovación). "
            "¿Tiene licencia federal B o E?"
        )

    if branch == "b1":
        if not facts.get("experience.vehicle_type"):
            return "Para las vacantes con ruta B1/EUA, ¿su experiencia es en tracto full o sencillo?"
        if not has_be or not facts.get("license.expiration_text"):
            return (
                "Para las vacantes B1/EUA necesitamos confirmar que su licencia federal esté vigente. "
                "¿Qué tipo de licencia federal tiene y cuándo vence?"
            )
        if not facts.get("medical.apto_expiration_text"):
            return "¿Cuándo vence su apto médico?"
        return None  # todos los datos confirmados

    if branch == "reingreso":
        if not facts.get("reingreso.tipo_vacante"):
            return (
                "Gracias por contactarnos de nuevo. ¿Busca regresar como operador de tracto, "
                "o tiene en mente otro tipo de vacante?"
            )
        return None

    return None


# Quita un prefijo de cortesía inicial (+ puntuación de cierre, sin tocar ¿/¡) de la
# pregunta cuando el ack ya empieza con la misma palabra, para no duplicarla.
_LEADING_PERFECTO = re.compile(r"^perfecto\s*[,.:;!]*\s*", re.IGNORECASE)
_LEADING_GRACIAS = re.compile(r"^gracias\s*[,.:;!]*\s*", re.IGNORECASE)


def _strip_leading_word(pattern: re.Pattern, text: str) -> str:
    stripped = pattern.sub("", text, count=1)
    if stripped and stripped[0].isalpha() and stripped[0].islower():
        stripped = stripped[0].upper() + stripped[1:]
    return stripped


def _strip_leading_perfecto(text: str) -> str:
    return _strip_leading_word(_LEADING_PERFECTO, text)


def _join_ack_and_question(prefix: str, question: str | None) -> str:
    """Une el ack y la siguiente pregunta evitando prefijos de cortesía duplicados.

    Puro: no extrae facts ni mete lógica de negocio. Si el ack ya abre con
    "Perfecto" o "Gracias" y la pregunta también, se quita ese prefijo de la
    pregunta. Sin ack (prefix vacío), la pregunta se conserva tal cual.
    """
    prefix = (prefix or "").strip()
    question = (question or "").strip()
    if not prefix:
        return question
    if not question:
        return prefix
    if prefix.lower().startswith("perfecto") and question.lower().startswith("perfecto"):
        question = _strip_leading_word(_LEADING_PERFECTO, question)
    if (
        re.match(r"^gracias", prefix, re.IGNORECASE)
        and question.lower().startswith("gracias")
    ):
        question = _strip_leading_word(_LEADING_GRACIAS, question)
    return f"{prefix} {question}".strip()


def build_current_turn_ack(
    message: str | None,
    merged_facts: dict[str, Any] | None = None,
    last_bot_message: str | None = None,
    pre_current_facts: dict[str, Any] | None = None,
    name_just_learned: bool = False,
) -> str:
    current = pre_current_facts if pre_current_facts is not None else extract_current_turn_facts(message, last_bot_message)
    # Invariante: `current` contiene SOLO los facts nuevos del turno (el caller filtra
    # contra lo ya guardado). El prefijo de confirmación se construye únicamente sobre
    # `current` para no re-confirmar datos previos (echo del extractor). La siguiente
    # pregunta del funnel deriva de `facts` (estado completo mergeado), no del prefijo.
    facts = {**(merged_facts or {}), **current}

    if is_age_disqualified(facts):
        return age_disqualification_reply(_to_int(facts.get("candidate.age")))

    # Trato por nombre de pila la primera vez que se conoce el nombre (p. ej.
    # extraído de una INE por visión): genera confianza. `name_just_learned` lo
    # calcula el caller contra el snapshot PRE-turno (no contra `current`, que se
    # vacía porque el orquestador ya persistió el nombre antes del guard). Cuando el
    # nombre es nuevo, el acuse es ÚNICAMENTE "Gracias, <nombre>." + la siguiente
    # pregunta del funnel; no se confirman los demás datos del mismo turno.
    _fname = first_name(facts)
    if name_just_learned and _fname:
        return _join_ack_and_question(f"Gracias, {_fname}.", next_question_from_missing_facts(facts))

    # Resumen de confirmación (D6): si el último mensaje fue el resumen y este turno
    # trae una CORRECCIÓN de dato, re-confirmar SOLO lo corregido (excepción única al
    # sin-eco: el candidato necesita ver que su corrección quedó).
    if (
        last_bot_message
        and _TOPIC_SUMMARY_CONFIRM.search(last_bot_message)
        and current
        and not current.get("funnel.summary_confirmed")
    ):
        _labels = dict(_SUMMARY_FIELD_DISPLAY)
        _fixed = [
            f"{_labels[k]}: {v}" for k, v in current.items() if k in _labels and v
        ]
        if _fixed:
            return f"Queda corregido — {'; '.join(_fixed)}. ¿Así es correcto?"

    # Sin eco de datos (feedback usuario 2026-07-03: se sentía robótico repetir cada
    # dato). Acuse situado GENERADO (FUNNEL_LLM_TRANSITIONS) con el conector enlatado
    # + pregunta literal como degradación. El saludo con nombre (arriba) es la única
    # confirmación con dato. Las respuestas a negativas/absurdos las genera el LLM
    # aparte (empathetic-funnel D1).
    _next_q = _next_funnel_question_or_none(facts)
    if _next_q is not None:
        _connector = random.choice(_FUNNEL_CONNECTORS)
        return generate_funnel_transition_reply(
            message, current, _next_q,
            fallback=_join_ack_and_question(_connector, _next_q),
        )
    # Perfil completo sin confirmar: emite el resumen; confirmado: el cierre.
    if not summary_confirmed(facts):
        return build_funnel_summary(facts)
    return _profile_complete_closing(facts)
