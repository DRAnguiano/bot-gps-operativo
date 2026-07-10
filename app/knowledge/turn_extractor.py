"""Extractor unificado de turno (unified-turn-extractor).

Una sola pasada LLM T=0 por turno que devuelve TODOS los datos del candidato:
facts crudos (con evidencia observable), pregunta embebida y señales de turno.

Arquitectura por capas (design.md D1):
  Capa 1 (este módulo, LLM):  lenguaje → concepto crudo + evidencia
  Capa 2 (validate_extraction): concepto → válido (catálogo determinista)
  Capa 3 (en código de negocio): concepto → política (B→sencillo, escuelita, ...)

El LLM NUNCA devuelve confianza (D2) ni toma decisiones de negocio (D1).
Reporta hechos observables: explicit_marker, answered_direct_question.
La confianza se computa en código (Capa 2) a partir de esa evidencia.

Fail-safe (D-degradación): si Groq falla o el JSON no parsea, retorna un
TurnExtraction vacío — el funnel re-pregunta. NUNCA cae a regex-adivinanza.

Estado: SHADOW. Este módulo no está wireado al path vivo todavía (sección 6 de
tasks). Se valida en log-only contra el path actual antes de cortar.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from app.knowledge.agent_decision import AgentDecision, parse_agent_decision
from app.knowledge.turn_intent_classifier import TurnIntentSignals
from app.knowledge.geo_utils import normalize_zm_laguna_city
from app.knowledge.llm_errors import LLMUnavailableError

# Proveedor único: Gemini (gemini-full-provider-migration 2026-07-07). El modelo
# vive en gemini_client (GEMINI_MODEL); UNIFIED_EXTRACTOR_MODEL/GROQ_MODEL quedan
# obsoletas (se retiran de .env en D7).

# Campos de perfil que el extractor puede reportar (clave canónica).
# Texto libre (sin Capa 2 que valide): name, license_expiration, apto_expiration.
# Con catálogo (Capa 2 valida): city, vehicle_type, age, license_category.
_PROFILE_FIELDS = (
    "candidate.name",
    "candidate.city",
    "candidate.age",
    "experience.vehicle_type",
    "experience.years",
    "license.category",
    "license.expiration_text",
    "medical.apto_expiration_text",
    "documents.proof",
)


@dataclass
class FieldValue:
    """Un campo extraído con su evidencia observable (NO confianza — D2)."""
    value: str | None = None
    explicit_marker: bool = False          # hubo "me llamo"/"soy de"/"vence en"...
    answered_direct_question: bool = False  # last_bot pidió este campo y esto lo responde


@dataclass
class TurnExtraction:
    """Resultado único de la extracción de un turno (D5)."""
    fields: dict[str, FieldValue] = field(default_factory=dict)
    embedded_question: str | None = None
    signals: TurnIntentSignals = field(default_factory=TurnIntentSignals)
    # controlled-agentic-profiling B1 (SHADOW): decisión del agente, sin autoridad
    # propia — nada de esto llega a BD/reply/labels sin pasar por
    # agent_decision_validator (Bloque 2).
    agent_decision: AgentDecision = field(default_factory=AgentDecision)

    def value(self, key: str) -> str | None:
        fv = self.fields.get(key)
        return fv.value if fv else None


_TURN_EXTRACTOR_SYSTEM = """Eres un extractor de datos de reclutamiento para operadores de camión (tracto full / sencillo).
El candidato escribió un mensaje. El bot le había hecho una pregunta (te la doy como contexto).
También te doy los datos que YA conocemos del candidato.

Extrae TODO lo que el candidato dijo en ESTE mensaje, en una sola pasada. Devuelve EXACTAMENTE este JSON:

{
  "fields": {
    "candidate.name":             {"value": <str|null>, "explicit_marker": <bool>, "answered_direct_question": <bool>},
    "candidate.city":             {"value": <str|null>, "explicit_marker": <bool>, "answered_direct_question": <bool>},
    "candidate.age":              {"value": <str|null>, "explicit_marker": <bool>, "answered_direct_question": <bool>},
    "experience.vehicle_type":    {"value": <str|null>, "explicit_marker": <bool>, "answered_direct_question": <bool>},
    "experience.years":           {"value": <str|null>, "explicit_marker": <bool>, "answered_direct_question": <bool>},
    "license.category":           {"value": <str|null>, "explicit_marker": <bool>, "answered_direct_question": <bool>},
    "license.expiration_text":    {"value": <str|null>, "explicit_marker": <bool>, "answered_direct_question": <bool>},
    "medical.apto_expiration_text":{"value": <str|null>, "explicit_marker": <bool>, "answered_direct_question": <bool>},
    "documents.proof":            {"value": <str|null>, "explicit_marker": <bool>, "answered_direct_question": <bool>}
  },
  "embedded_question": <str|null>,
  "signals": {
    "is_ya_reclamo": <bool>, "is_memory_claim": <bool>, "has_embedded_question": <bool>,
    "call_requested": <bool>, "renewal_proof": <"si"|"no"|null>, "no_road_experience": <bool>,
    "has_expiry_context": <bool>, "experience_context": <bool>, "is_joke_request": <bool>,
    "conversational_purpose": <"smalltalk"|"queja"|"agradecimiento"|"despedida"|"animo"|"none">
  },
  "agent_decision": {
    "public_reply": <str>,
    "proposed_facts": [{"field": <str>, "value": <str>, "evidence": <str>, "confidence": <0.0-1.0>}],
    "next_action": <"ask_field:<campo>"|"answer_question"|"acknowledge"|"close_profile"|"handoff"|"wait">,
    "missing_fields": [<str>],
    "uncertainty_flags": [<str>],
    "crm_private_note": <str|null>,
    "handoff_recommendation": {"recommended": <bool>, "reason": <str|null>}
  }
}

REGLAS DE VALOR (qué dijo el candidato — NO interpretes política de negocio):
- candidate.name: nombre propio. Ignora saludos ("hola"), afirmaciones ("si","no") y términos de unidad. Si no hay nombre, null.
  Muchos mensajes vienen TRANSCRITOS de nota de voz y la transcripción daña apellidos
  hispanos: los divide como artículo + fragmento o los deforma fonéticamente. Si el bot
  preguntó el nombre y el texto trae "el/él " + fragmento que junto forma un nombre o
  apellido hispano plausible, ÚNELO y repara al apellido real:
  · "eliezer el lizondo" → candidate.name="Eliezer Elizondo" (el+lizondo = Elizondo)
  · "me llamo juan el ías" → candidate.name="Juan Elías"
  · "soy pedro el lisa" (bot preguntó nombre) → candidate.name="Pedro Elías" si es la
    lectura hispana plausible; si el fragmento no da un nombre hispano claro, conserva
    el texto tal cual — NUNCA inventes un apellido sin fragmento que lo soporte.
  Esta reparación aplica SOLO a candidate.name (no toques ciudades ni otros campos con
  esta regla) y solo cuando la lectura como artículo no tiene sentido gramatical.
- candidate.city: ciudad de RESIDENCIA (no destinos ni rutas). Sin marcador de residencia → null.
  El candidato casi siempre reside en MÉXICO (zona de operación: La Laguna/Coahuila/Durango y
  alrededores — Torreón, Gómez Palacio, Lerdo, Saltillo, Monterrey, etc.). Ante un nombre con
  errores/typos, resuelve SIEMPRE hacia la ciudad MEXICANA real más parecida y plausible por el
  contexto — NUNCA hacia una ciudad extranjera de nombre parecido aunque coincida más letras
  (p. ej. "Torreano" es un typo de "Torreón", NO una localidad italiana). Una ciudad de ESTADOS
  UNIDOS solo es válida si el candidato menciona la vacante "B1" (ruta a EEUU) en el mismo mensaje
  o contexto reciente; sin esa mención, interpreta el nombre como mexicano o, si de verdad no hay
  lectura mexicana plausible, deja null (no inventes ni una ciudad ni un país).
- candidate.age: edad en años, entero como string. Convierte palabras ("cincuenta y uno"→"51"). NO de "N años de experiencia". Rango plausible 18-70, fuera de eso → null.
- experience.vehicle_type: reporta el término CRUDO tal como lo dijo ("full","sencillo","torton","quinta rueda","trailer"). NO clasifiques si es objetivo o no — eso lo decide el sistema.
- experience.years: años manejando como número o aproximación numérica ("10 años","más de 5","como 3 años"). Expresiones vagas sin número ("toda la vida","de siempre","muchos años","bastante","siempre") → null. Distínguelo del vencimiento de licencia.
- license.category: tipo de licencia federal (A/B/E) tal como lo dijo.
- license.expiration_text: cuánto falta para que venza la licencia ("2 años","6 meses","vencido"). Solo si habla de vigencia de LICENCIA.
- medical.apto_expiration_text: vigencia del apto médico. Si dice "igual/lo mismo que mi licencia" y conoces license.expiration_text, usa ESE valor.
- documents.proof: "cartas" si tiene cartas laborales, "semanas_imss" si tiene semanas del IMSS, "ninguno" si dice que NO tiene. Si no menciona, null.

is_joke_request: el candidato PIDE que le cuenten un chiste/broma para animarlo. Distingue del uso
IDIOMÁTICO de "chiste"/"broma" como queja o sarcasmo (= "qué ridículo"), que NO es una petición.
  true: "cuéntame un chiste", "no sabe contar chistes?", "échese una broma para animarme"
  false: "así que chiste", "qué chiste de proceso", "esto es una broma verdad"

conversational_purpose: la FINALIDAD conversacional del mensaje cuando NO es dar un dato de perfil
ni hacer una pregunta de negocio.
  "smalltalk": plática casual sin tema de negocio ("qué calorón hoy", "ando comiendo, ahorita sigo")
  "queja": molestia/frustración con el proceso ("son bien lentos", "puro trámite y trámite")
  "agradecimiento": gracias genuinas ("muchas gracias por la info", "muy amable")
  "despedida": cierre de conversación ("hasta luego", "nos vemos, buenas noches")
  "animo": busca motivación/confianza sobre su proceso ("usted cree que sí quede?", "estoy nervioso")
  "none": dato de perfil, pregunta de negocio, o cualquier otra cosa ("soy de Torreón", "cuánto pagan")
  Si el mensaje MEZCLA dato/pregunta con finalidad conversacional, el dato/pregunta manda: usa "none"
  salvo que la parte conversacional sea el punto principal del mensaje.

REGLAS DE EVIDENCIA:
- explicit_marker = true cuando el candidato usó un marcador explícito ("me llamo","soy de","vivo en","mi licencia vence en","tengo X años").
- answered_direct_question = true cuando la pregunta del bot pedía ESE campo y el mensaje lo responde.

embedded_question / has_embedded_question: si el candidato PREGUNTA por pago, rutas, prestaciones,
requisitos, documentos, licencia, apto, antidoping, vacantes, base, reingreso, entrevista/horario o
proceso, pon la duda reescrita en español claro y marca has_embedded_question=true. Si no pregunta,
null / false.

LENGUAJE INFORMAL Y JERGA OPERATIVA (glosario derivado de chats reales):
- El candidato escribe con faltas, sin signos, abreviaturas y mensajes cortados. Lee el texto CRUDO;
  NO apliques un corrector ortográfico palabra por palabra. Puedes normalizar mentalmente para
  comprender, pero conserva el valor DICHO.
- Usa el contexto completo (pregunta previa del bot + datos conocidos + mensaje actual). El candidato
  puede dar un dato Y hacer una duda en el mismo turno → extrae AMBOS.
- "q","k","ke"→"qué/que"; "kiero"→"quiero"; "porq/pq/xq"→"por qué/porque"; "asta"→"hasta";
  "ay/ai/ahy" es AMBIGUO (hay/ahí): decide por contexto, no como una sola palabra.
- Jerga de operación (solo para ENTENDER de qué habla; NO infieras negocio de estos términos):
  "tramo"=ruta; "circuito"=rutas FUERA del corredor principal (Monterrey–Laredo, Torreón–Saltillo–
  Monterrey–Laredo y el noreste); "de qué lado la ruedan"/"pa dónde sale"/"jalones"/"vuelta"/"viaje"
  = habla de RUTAS; "op"/"5ta rueda"/"trailero"/"trucker"=el oficio de operador; "pipi"/"orines"/"el
  vaso"=antidoping.
- Unidades en jerga: "doble articulado"/"doble" (como SU unidad) → repórtalo CRUDO en
  vehicle_type ("doble articulado"); "caja seca" dicho como SU unidad → repórtalo CRUDO
  ("caja seca"). El sistema los mapea (doble=full, caja seca suele ser sencillo).
- "recién renovada"/"renovada" (licencia/apto) NO es un plazo de vencimiento: license.expiration_text
  =null (el sistema preguntará cuándo vence). NO pierdas por eso los demás datos del mismo mensaje
  (tipo de licencia, unidad).
- OJO ambiguo: "pa arriba"/"pal norte" NO tienen destino fijo — pueden ser norte de México O EUA;
  NO los resuelvas a una ciudad/país ni asumas cruce fronterizo. Solo indican pregunta de rutas; el
  destino real se valida después. "MTY"=Monterrey, "NLD"=Nuevo Laredo como topónimos, pero como
  destino/ruta NO son residencia.
- Pago en jerga: "k tanto deja","cuánto deja pa uno","a como sale la vuelta","x viaje cuánto" =
  pregunta de PAGO.
- Marca has_embedded_question=true aunque NO use "?", si pregunta por pago/km/movimiento/viajes/
  tramo/circuito/base/descansos/vacante/requisitos/documentos/licencia/apto/escuelita/reingreso/
  entrevista/antidoping.
- NO marques pregunta solo porque menciona una palabra de dominio. ENUNCIADOS (sobre todo en PASADO)
  NO son pregunta: "mi licencia vence en agosto", "mi ruta ERA laredo", "el pago anterior ERA
  semanal", "tengo caja sencilla desde 2020".
- candidate.city solo con ANCLA de residencia ("soy de","vivo en","radico en","resido en"). "ruta a
  Monterrey" y "tramo a Laredo" NO son residencia — MTY/NLD sin ancla pueden ser destino/base.
- "pipi"/"orines" refieren al antidoping SOLO cuando el contexto indica pregunta de ingreso. No
  inventes política ni resultado de examen. Que mande imagen/PDF/sticker NO autoriza OCR.

Ejemplos:
- "d a komo da el km soi d torrion" (bot preguntó ciudad) → candidate.city="Torreón", embedded_question="¿a cómo pagan el kilómetro?", has_embedded_question=true
- "lo de la pipi komo esta" → embedded_question="¿cómo es el antidoping del proceso?", has_embedded_question=true
- "tngo 10 años full pero pa k lado la ruedan" → experience.years="10", experience.vehicle_type="full", embedded_question="¿qué rutas maneja la vacante?", has_embedded_question=true
- "una vuelta d esas k tanto deja pa uno" → embedded_question="¿cuánto pagan por viaje?", has_embedded_question=true
- "ai jalones pa arriba o puro cerka" → embedded_question="¿los viajes son largos o cortos?", has_embedded_question=true (NO resuelvas "pa arriba" a un destino)
- "el pago anterior era semanal" → embedded_question=null, has_embedded_question=false (enunciado en pasado)
- "mi ruta era nuevo laredo" → embedded_question=null, has_embedded_question=false; candidate.city=null (destino, no residencia)
- "E doble articulado, recién renovada" (bot preguntó licencia) → license.category="E", experience.vehicle_type="doble articulado", license.expiration_text=null (renovada NO es plazo)
- "manejo caja seca dese ace 5 años" → experience.vehicle_type="caja seca", experience.years="5"
- "vivo acá en La Amistad, soy de aquí de Torreano" → candidate.city="Torreón" (typo de ciudad
  mexicana real y cercana a la zona — NO una localidad extranjera de nombre parecido)
- "trabajo con visa, busco lo de la vacante b1, vivo en Houston" → candidate.city="Houston"
  (válido SOLO porque menciona B1 en el mismo mensaje)
- "vivo en Houston" (sin mención de B1) → candidate.city=null (ciudad de EEUU sin contexto B1;
  no hay lectura mexicana plausible del nombre — no la inventes ni la aceptes como residencia)

AGENT_DECISION (controlled-agentic-profiling — MODO SHADOW, no se usa aún en la
respuesta real; solo se loguea para comparar contra el funnel actual):
- public_reply: tu respuesta natural al candidato para ESTE turno — confirma lo que
  dijo, responde su duda si la hizo, y pregunta el SIGUIENTE dato que falte de
  DATOS YA CONOCIDOS. Nunca preguntes algo que ya está en "DATOS YA CONOCIDOS" ni
  algo que el candidato acaba de dar en este mismo mensaje.
- proposed_facts: SOLO datos con evidencia LITERAL en el mensaje de este turno
  (el sistema descarta cualquier fact cuya evidencia no aparezca tal cual en el
  mensaje — no repitas aquí lo que ya viene en "fields", es el mismo espíritu con
  formato distinto). confidence: qué tan explícito fue el dato (marcador claro=0.9+,
  inferencia razonable=0.7-0.8, dudoso=<0.6).
- next_action: qué harías tú a continuación. "ask_field:<campo>" con el campo
  canónico (candidate.name, candidate.city, candidate.age, experience.vehicle_type,
  license.category, license.expiration_text, medical.apto_expiration_text,
  documents.proof). "close_profile" SOLO si de verdad no falta nada de la lista de
  DATOS YA CONOCIDOS + lo dicho en este turno.
- missing_fields: tu lista de campos que crees que faltan (el sistema tiene la
  suya propia y las compara — no se penaliza que difieran, es lo que se mide).
- uncertainty_flags: ambigüedades que NO quisiste resolver solo (p. ej. "dijo caja
  seca, no estoy seguro si es full o sencillo").
- crm_private_note: 1 frase de contexto útil para el reclutador humano, o null si
  no hay nada que agregar (nunca inventes ni repitas los facts, eso ya está en la
  Nota IA).
- handoff_recommendation: recommended=true SOLO si detectas algo que un humano
  debería revisar (duda seria, señal de riesgo, situación fuera de lo normal) —
  nunca lo uses para decidir si el candidato califica o no.

Ejemplos de agent_decision (formato abreviado, solo lo relevante):
- "soy de Lerdo, manejo full desde hace 10 años y mi licencia E vence en 2027" (bot
  preguntó el nombre) → proposed_facts=[city=Lerdo, vehicle_type=full, years=10,
  license.category=E, license.expiration_text=2027 (todos con evidencia literal)],
  next_action="ask_field:candidate.name" (lo único que sigue faltando)
- "no sé, tal vez unos 8 años, no me acuerdo bien" → proposed_facts=[] (sin
  evidencia firme, confidence bajo no vale la pena proponerlo),
  uncertainty_flags=["años de experiencia inciertos"], next_action="ask_field:experience.years"
- "así que chiste todo esto, ya llevo rato esperando" → agent_decision.public_reply
  reconoce la molestia con empatía; next_action="acknowledge"; NO se propone ningún fact

IMPORTANTE: Responde SOLO el JSON. value siempre es lo que el candidato DIJO, nunca una inferencia de negocio."""


def _parse_field(raw: Any) -> FieldValue:
    if not isinstance(raw, dict):
        return FieldValue()
    val = raw.get("value")
    val = str(val).strip() if val not in (None, "", "null") else None
    return FieldValue(
        value=val,
        explicit_marker=bool(raw.get("explicit_marker", False)),
        answered_direct_question=bool(raw.get("answered_direct_question", False)),
    )


_CONVERSATIONAL_PURPOSES = {"smalltalk", "queja", "agradecimiento", "despedida", "animo", "none"}


def _parse_signals(raw: Any) -> TurnIntentSignals:
    if not isinstance(raw, dict):
        return TurnIntentSignals()
    _purpose = str(raw.get("conversational_purpose") or "none")
    return TurnIntentSignals(
        is_ya_reclamo=bool(raw.get("is_ya_reclamo", False)),
        is_memory_claim=bool(raw.get("is_memory_claim", False)),
        has_embedded_question=bool(raw.get("has_embedded_question", False)),
        call_requested=bool(raw.get("call_requested", False)),
        renewal_proof=raw.get("renewal_proof") or None,
        no_road_experience=bool(raw.get("no_road_experience", False)),
        has_expiry_context=bool(raw.get("has_expiry_context", False)),
        experience_context=bool(raw.get("experience_context", False)),
        is_joke_request=bool(raw.get("is_joke_request", False)),
        conversational_purpose=_purpose if _purpose in _CONVERSATIONAL_PURPOSES else "none",
    )


def extract_turn(
    message: str,
    last_bot_question: str | None = None,
    known_facts: dict[str, Any] | None = None,
) -> TurnExtraction:
    """Extrae todo el turno en una sola pasada LLM. Fail-safe a TurnExtraction vacío."""
    if not (message or "").strip():
        return TurnExtraction()

    known = known_facts or {}
    known_lines = "\n".join(f"- {k}: {v}" for k, v in known.items() if v) or "(ninguno)"
    user_content = (
        f"PREGUNTA DEL BOT: {last_bot_question or '(ninguna)'}\n"
        f"DATOS YA CONOCIDOS:\n{known_lines}\n"
        f"MENSAJE DEL CANDIDATO: {message}"
    )

    try:
        from app.gemini_client import dispatch_json
        raw = dispatch_json(user_content, _TURN_EXTRACTOR_SYSTEM, temperature=0.0)
        data = json.loads(raw)
    except Exception:
        return TurnExtraction()

    if isinstance(data, dict) and data.get("error"):
        # Gemini no disponible (429/timeout — contrato de error del dispatch): se
        # preserva el gate de producción del worker (abort silencioso del turno,
        # sin respuesta basura ni re-preguntas por extracción vacía).
        raise LLMUnavailableError(f"Gemini no disponible: {data.get('error')}")

    fields_raw = data.get("fields") or {}
    fields = {
        key: _parse_field(fields_raw.get(key))
        for key in _PROFILE_FIELDS
        if fields_raw.get(key) and _parse_field(fields_raw.get(key)).value is not None
    }
    if "candidate.city" in fields and fields["candidate.city"].value:
        fields["candidate.city"].value = normalize_zm_laguna_city(fields["candidate.city"].value)
    if "documents.proof" in fields and fields["documents.proof"].value:
        from app.knowledge.current_turn import canonicalize_proof
        _proof_canon = canonicalize_proof(fields["documents.proof"].value)
        if _proof_canon is None:
            del fields["documents.proof"]  # no mapeable → no persistir texto crudo
        else:
            fields["documents.proof"].value = _proof_canon
    # Vigencia enunciada por el candidato: si el mensaje trae un marcador de
    # vencimiento, marca la vigencia como explícita para que D3 no la descarte
    # cuando se ofrece antes de preguntarla (volunteered-expiration-extraction).
    _mark_stated_expirations(fields, message)
    embedded = data.get("embedded_question") or None
    return TurnExtraction(
        fields=fields,
        embedded_question=str(embedded).strip() if embedded else None,
        signals=_parse_signals(data.get("signals")),
        agent_decision=parse_agent_decision(data.get("agent_decision")),
    )


# ── Capa 2: validación determinista + confianza derivada ──────────────────────

# Campos de texto libre SIN catálogo que valide (D3): requieren anclaje para persistir.
_FREE_TEXT_FIELDS = {
    "candidate.name",
    "license.expiration_text",
    "medical.apto_expiration_text",
}
# Hints de igualdad para resolver "igual que mi licencia" (determinista, no LLM).
_EQUALITY_HINTS = (
    "igual", "mismo", "lo mismo", "al mismo tiempo", "igual que", "mismo que",
    "los dos", "ambos", "misma vigencia", "igualmente",
)
# Marcadores de vencimiento inequívocos (sobre texto normalizado). Si el candidato
# ENUNCIA la vigencia ("vence en...", "vigencia...") su valor debe tratarse como
# explícito aunque el LLM deje explicit_marker=False, para no perderlo por D3 cuando
# se ofrece antes de preguntarlo (volunteered-expiration-extraction).
_EXPIRATION_MARKERS = ("vence", "venci", "vigenc", "vencimiento", "caduc")


def _states_expiration(text: str) -> bool:
    """True si el texto del turno enuncia claramente una vigencia (vencimiento)."""
    from app.knowledge.text_normalizer import normalize_text
    t = normalize_text(text or "")
    return any(m in t for m in _EXPIRATION_MARKERS)


def _mark_stated_expirations(fields: dict[str, "FieldValue"], message: str) -> None:
    """Marca explicit_marker=True en las vigencias con valor cuando el mensaje enuncia
    un vencimiento, para que D3 no las descarte al ofrecerse antes de preguntarlas."""
    if not _states_expiration(message):
        return
    for key in ("license.expiration_text", "medical.apto_expiration_text"):
        fv = fields.get(key)
        if fv is not None and fv.value:
            fv.explicit_marker = True
_NAME_SKIP = {
    "si", "no", "nel", "nop", "ok", "va", "dale", "sale", "claro", "exacto",
    "hola", "ola", "buenas", "buenos", "buen", "hey", "gracias", "perfecto",
    "listo", "entendido", "correcto", "anotado", "registrado",
    "full", "sencillo", "tracto", "torton", "rabon",
}


def _derived_confidence(fv: FieldValue, catalog_validated: bool, base: float = 0.5) -> float:
    conf = base
    if catalog_validated:
        conf += 0.3
    if fv.explicit_marker:
        conf += 0.2
    if fv.answered_direct_question:
        conf += 0.2
    return round(min(conf, 1.0), 2)


def validate_extraction(
    extraction: TurnExtraction,
    known_facts: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Capa 2: valida los campos crudos contra catálogos y deriva confianza.

    Devuelve facts canónicos listos para persistir: cada uno con
    {fact_group, fact_key, fact_value, confidence, is_explicit_correction}.
    Aplica D3 (texto libre sin anclaje no se promueve) y la resolución
    determinista de referencias de igualdad. NO aplica política de negocio (Capa 3).
    """
    from app.knowledge.normalize_domain_values import normalize_vehicle
    from app.knowledge.domain_catalog import NON_TARGET, NEEDS_CLARIFICATION
    from app.knowledge.text_normalizer import normalize_text
    from app.settings import AGE_DISQUALIFICATION_LIMIT  # noqa: F401  (política, no usado aquí)

    known = known_facts or {}
    is_correction = extraction.signals.is_ya_reclamo
    out: list[dict[str, Any]] = []

    def _emit(key: str, value: str, fv: FieldValue, catalog_validated: bool):
        group, fkey = key.split(".", 1)
        out.append({
            "fact_group": group,
            "fact_key": fkey,
            "fact_value": value,
            "confidence": _derived_confidence(fv, catalog_validated),
            "is_explicit_correction": is_correction,
        })

    for key, fv in extraction.fields.items():
        if fv.value is None:
            continue

        # D3: texto libre sin anclaje (ni marcador ni respuesta a pregunta) → no promover
        if key in _FREE_TEXT_FIELDS and not (fv.explicit_marker or fv.answered_direct_question):
            continue

        # "recién renovada"/"renovada" NO es un plazo de vencimiento (regla 2026-07-07,
        # conv 163): descartar como expiration para que el funnel pregunte cuándo vence,
        # sin perder los demás campos del turno (categoría, unidad).
        if key in {"license.expiration_text", "medical.apto_expiration_text"} and \
                "renovad" in normalize_text(fv.value):
            continue

        # candidate.name — texto libre, descartar saludos/ruido
        if key == "candidate.name":
            if fv.value.lower().strip() in _NAME_SKIP or len(fv.value.strip()) < 3:
                continue
            _emit(key, fv.value.strip().title(), fv, catalog_validated=False)
            continue

        # candidate.age — Capa 2: rango plausible 18-70
        if key == "candidate.age":
            digits = "".join(c for c in fv.value if c.isdigit())
            if digits and 18 <= int(digits) <= 70:
                _emit(key, str(int(digits)), fv, catalog_validated=True)
            continue

        # experience.vehicle_type — catálogo decide; solo full/sencillo confirmado se promueve.
        # NON_TARGET/NEEDS_CLARIFICATION NO fija vehicle_type (eso es política, Capa 3).
        if key == "experience.vehicle_type":
            res = normalize_vehicle(fv.value)
            if res and res.value:  # full | sencillo confirmado
                _emit(key, res.value, fv, catalog_validated=True)
            # término crudo (torton, quinta rueda) se preserva para Capa 3
            elif res and res.status in {NON_TARGET, NEEDS_CLARIFICATION}:
                out.append({
                    "fact_group": "experience", "fact_key": "vehicle_type_raw",
                    "fact_value": fv.value, "confidence": _derived_confidence(fv, True),
                    "is_explicit_correction": is_correction,
                })
            continue

        # license.category — solo B/E aplican a estos puestos (regla de negocio
        # 2026-07-07: A es irrelevante para tracto full/sencillo). A se preserva
        # como license.category_raw (mismo patrón que vehicle_type_raw) para que
        # Capa 3 pueda re-encauzar en vez de tratarla como respuesta válida.
        if key == "license.category":
            cat = fv.value.strip().upper().replace("TIPO ", "").strip()
            if cat in {"B", "E"}:
                _emit(key, cat, fv, catalog_validated=True)
            elif cat == "A":
                out.append({
                    "fact_group": "license", "fact_key": "category_raw",
                    "fact_value": cat, "confidence": _derived_confidence(fv, True),
                    "is_explicit_correction": is_correction,
                })
            continue

        # medical.apto_expiration_text — resolver igualdad con la licencia (determinista)
        if key == "medical.apto_expiration_text":
            val = fv.value
            if any(h in val.lower() for h in _EQUALITY_HINTS):
                lic = known.get("license.expiration_text") or extraction.value("license.expiration_text")
                if lic:
                    val = lic
                else:
                    continue  # referencia sin ancla → no inventar
            _emit(key, val, fv, catalog_validated=False)
            continue

        # license.expiration_text, experience.years, documents.proof — pasan con su evidencia
        _emit(key, fv.value, fv, catalog_validated=False)

    # Señal de comprobante de renovación: surface como fact del path activo. Sin esto
    # la señal se descarta y el funnel re-pregunta el comprobante en bucle.
    _renewal = extraction.signals.renewal_proof
    if _renewal in {"si", "no"}:
        out.append({
            "fact_group": "documents",
            "fact_key": "renewal_proof",
            "fact_value": _renewal,
            "confidence": 0.8,
            "is_explicit_correction": is_correction,
        })

    return out
