"""Clasificador unificado de señales de intención por turno.

Una sola llamada LLM T=0 por turno retorna todos los signals semánticos.
Los extractores downstream consumen este dict — ninguno invoca su propio LLM
por separado ni necesita keyword guards.

Fail-safe: si Groq falla, retorna TurnIntentSignals() con todos los campos
en valor neutro (False / None) — pipeline degrada sin crash.
"""
from __future__ import annotations

import json
from dataclasses import dataclass


# Proveedor único: Gemini (gemini-full-provider-migration 2026-07-07). La selección
# de modelo vive en gemini_client (GEMINI_MODEL); ya no hay constante de modelo Groq.

_TURN_INTENT_SYSTEM = """Eres un clasificador de señales de reclutamiento para operadores de camión (tracto full / sencillo).
Analiza el mensaje del candidato y devuelve EXACTAMENTE este JSON con los 10 campos:

{
  "is_ya_reclamo": <bool>,
  "is_memory_claim": <bool>,
  "has_embedded_question": <bool>,
  "call_requested": <bool>,
  "renewal_proof": <"si" | "no" | null>,
  "no_road_experience": <bool>,
  "has_expiry_context": <bool>,
  "experience_context": <bool>,
  "is_joke_request": <bool>,
  "conversational_purpose": <"smalltalk" | "queja" | "agradecimiento" | "despedida" | "animo" | "none">
}

Definiciones:

is_ya_reclamo — el "ya" expresa RECLAMO (el candidato protesta que ya dio el dato), NO confirmación de que ya tiene algo.
  true: "ya le había dicho", "eso ya se lo mencioné", "ya les mandé eso antes", "ya te lo dije"
  false: "ya tengo la licencia", "ya conseguí el apto", "ya está vigente", "ya tengo todo"

is_memory_claim — el candidato afirma haber dado ESTE dato antes en la conversación.
  true: "como le dije antes", "eso ya lo había comentado", "ya se los mandé", "ya le había dicho que full"
  false: "tengo 10 años manejando", "soy de Torreón", "si tengo cartas"

has_embedded_question — el mensaje contiene una pregunta sobre condiciones laborales aunque no tenga "?".
  true: "soy de Gómez que rutas hay", "tengo licencia E cuánto pagan", "dan boleto para traslado", "cuánto da de comer en viaje", "qué prestaciones tienen"
  false: "soy de Torreón", "tengo 10 años manejando full", "hola buenas"

call_requested — el candidato pide o acepta que le llamen por teléfono.
  true: "me pueden llamar", "prefiero que me hablen", "ponerse en contacto por teléfono", "agéndenme", "quiero una llamada"
  false: "no me llamen", "soy de Torreón", "tengo 10 años"

renewal_proof — indica si tiene o no comprobante de trámite de renovación de licencia o apto.
  "si": "ya pagué la cita", "tengo el comprobante", "tengo el recibo del trámite", "ya tramité"
  "no": "no tengo comprobante", "todavía no tramito", "sin papel todavía", "no he ido al SAT"
  null: cualquier otro caso (no menciona trámite ni comprobante)

no_road_experience — el candidato declara NO tener experiencia en carretera / tracto.
  true: "nunca he manejado tracto", "soy principiante en esto", "quiero aprender a manejar", "no tengo experiencia en carretera", "nunca he manejado en carretera"
  false: "tengo 10 años en full", "manejo sencillo desde hace años", "soy operador"

has_expiry_context — el mensaje menciona un vencimiento o plazo de vigencia de licencia o apto.
  true: "vence en julio", "caduca este año", "se me acaba la vigencia en 3 meses", "me queda un año de vigencia"
  false: "licencia vigente", "apto al corriente", "tengo licencia E"

experience_context — el candidato habla de SU PROPIA experiencia conduciendo vehículos de carga.
  true: "manejo tracto desde hace 5 años", "soy operador de full", "llevo 8 años como transportista", "conduzco sencillo"
  false: "me interesa ser operador", "busco trabajo de tracto", "hola, quiero información"

is_joke_request — el candidato PIDE que le cuenten un chiste/broma para animarlo. Distingue del uso
  IDIOMÁTICO de "chiste"/"broma" como queja o sarcasmo (= "qué ridículo"), que NO es una petición.
  true: "cuéntame un chiste", "no sabe contar chistes?", "échese una broma para animarme", "sabe algún chiste de trailero"
  false: "así que chiste", "qué chiste de proceso", "esto es una broma verdad", "no es cosa de risa esto"

conversational_purpose — la FINALIDAD conversacional del mensaje cuando NO es dar un dato de perfil
  ni hacer una pregunta de negocio. Sirve para que el bot responda humano en vez de con plantilla.
  "smalltalk": plática casual sin tema de negocio ("qué calorón hoy", "ando comiendo, ahorita sigo", "usted es robot o persona?")
  "queja": molestia/frustración con el proceso o la empresa ("así que chiste todo este proceso", "son bien lentos para contestar", "puro trámite y trámite")
  "agradecimiento": gracias genuinas ("muchas gracias por la info", "se lo agradezco", "muy amable")
  "despedida": cierre de conversación ("hasta luego", "nos vemos, buenas noches", "luego le sigo")
  "animo": busca motivación/confianza sobre su proceso ("usted cree que sí quede?", "deme ánimos", "estoy nervioso por la entrevista")
  "none": el mensaje es dato de perfil, pregunta de negocio, o cualquier otra cosa ("soy de Torreón", "cuánto pagan", "tengo licencia E")
  Si el mensaje MEZCLA dato/pregunta con finalidad conversacional, el dato/pregunta manda: usa "none"
  salvo que la parte conversacional sea el punto principal del mensaje.

IMPORTANTE: Responde SOLO el JSON, sin texto extra."""


@dataclass
class TurnIntentSignals:
    is_ya_reclamo: bool = False
    is_memory_claim: bool = False
    has_embedded_question: bool = False
    call_requested: bool = False
    renewal_proof: str | None = None
    no_road_experience: bool = False
    has_expiry_context: bool = False
    experience_context: bool = False
    is_joke_request: bool = False
    conversational_purpose: str = "none"


def classify_turn_intent(message: str) -> TurnIntentSignals:
    """Clasifica todas las señales semánticas del turno en una sola llamada LLM T=0.

    Fail-safe: si Groq falla retorna TurnIntentSignals() con valores neutros.
    """
    if not (message or "").strip():
        return TurnIntentSignals()
    try:
        from app.gemini_client import dispatch_json
        raw = dispatch_json(message, _TURN_INTENT_SYSTEM, temperature=0.0)
        data = json.loads(raw)
        return TurnIntentSignals(
            is_ya_reclamo=bool(data.get("is_ya_reclamo", False)),
            is_memory_claim=bool(data.get("is_memory_claim", False)),
            has_embedded_question=bool(data.get("has_embedded_question", False)),
            call_requested=bool(data.get("call_requested", False)),
            renewal_proof=data.get("renewal_proof") or None,
            no_road_experience=bool(data.get("no_road_experience", False)),
            has_expiry_context=bool(data.get("has_expiry_context", False)),
            experience_context=bool(data.get("experience_context", False)),
            is_joke_request=bool(data.get("is_joke_request", False)),
            conversational_purpose=(
                str(data.get("conversational_purpose") or "none")
                if str(data.get("conversational_purpose") or "none") in
                {"smalltalk", "queja", "agradecimiento", "despedida", "animo", "none"}
                else "none"
            ),
        )
    except Exception:
        return TurnIntentSignals()
