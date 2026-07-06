"""live-first-contact-and-fact-guards — tests RED primero.

Contrato:
  openspec/changes/live-first-contact-and-fact-guards/specs/

Cuatro fixes del camino vivo (smokes conv. 80/81 y 2026-06-12):
  1. Entrada de campaña FB en primer contacto → saludo oficial, no "lo dejo registrado".
  2. candidate.vacancy_accepted no es señal del current-turn guard.
  3. Facts geo no se extraen de preguntas sin marcador de residencia.
  4. Captura de ciudad acotada (no se traga la frase).

Sin DB, sin Chatwoot, sin LLM.
"""
from __future__ import annotations

import os

import pytest

import app.knowledge.current_turn as CT
import app.orchestrators.knowledge_orchestrator as KO
from app.lead_memory.profile_extractor import extract_profile_facts_as_dict
from app.knowledge.turn_intent_classifier import TurnIntentSignals

FB_ENTRY = "Me interesa la vacante de operador de quinta rueda"


# ── 1. Entrada de campaña / interés ───────────────────────────────────────────

class TestCampaignEntry:
    def test_helper_detecta_entrada_fb(self):
        helper = getattr(CT, "is_campaign_or_interest_entry", None)
        assert helper is not None, "falta is_campaign_or_interest_entry en current_turn"
        assert helper(FB_ENTRY) is True

    def test_interes_simple_tambien_es_entrada(self):
        helper = getattr(CT, "is_campaign_or_interest_entry", None)
        assert helper is not None
        assert helper("hola, me interesa la vacante de operador") is True

    def test_pregunta_no_es_entrada(self):
        # Con pregunta, el flujo normal debe responder (no saludo forzado).
        helper = getattr(CT, "is_campaign_or_interest_entry", None)
        assert helper is not None
        assert helper("me interesa la vacante, cuanto pagan?") is False

    def test_mensaje_de_perfil_no_es_entrada(self):
        helper = getattr(CT, "is_campaign_or_interest_entry", None)
        assert helper is not None
        assert helper("soy de torreon y manejo full") is False

    def test_saludo_oficial_menciona_full_o_sencillo(self):
        # El saludo que recibe la entrada de campaña es el oficial (vocabulario canónico).
        assert "tracto full o sencillo" in KO.GREETING_REPLY
        assert "quinta rueda" not in KO.GREETING_REPLY


# ── 2. Interés no es señal del guard ─────────────────────────────────────────

class TestInteresNoEsSenalDeGuard:
    def test_interes_puro_no_dispara_guard(self):  # FAILS hoy
        assert CT.has_current_turn_profile_signal(FB_ENTRY) is False

    def test_interes_con_saludo_no_dispara_guard(self):  # FAILS hoy
        assert CT.has_current_turn_profile_signal(
            "Hola, buenas tardes. Me interesa la vacante de operador."
        ) is False

    def test_respuesta_de_ciudad_si_dispara_guard(self):
        # No deconstruir: un dato real de perfil sigue siendo señal.
        assert CT.has_current_turn_profile_signal("soy de torreon") is True

    def test_licencia_si_dispara_guard(self):
        assert CT.has_current_turn_profile_signal("tengo licencia tipo e") is True


# ── 3. Geo no se extrae de preguntas ─────────────────────────────────────────

def _geo_filter():
    fn = getattr(KO, "_drop_geo_facts_from_questions", None)
    assert fn is not None, "falta _drop_geo_facts_from_questions en knowledge_orchestrator"
    return fn


def _facts_nld() -> list[dict]:
    return [
        {"fact_group": "candidate", "fact_key": "city", "fact_value": "Nuevo Laredo", "confidence": 0.92},
        {"fact_group": "license", "fact_key": "category", "fact_value": "e", "confidence": 0.9},
    ]


class TestGeoDesdePreguntas:
    def test_pregunta_de_rutas_no_fija_ciudad(self):
        out = _geo_filter()(_facts_nld(), "que rutas maneja para nuevo laredo?")
        keys = {(f["fact_group"], f["fact_key"]) for f in out}
        assert ("candidate", "city") not in keys
        assert ("license", "category") in keys  # solo geo se filtra

    def test_pregunta_con_marcador_de_residencia_conserva_ciudad(self):
        out = _geo_filter()(_facts_nld(), "soy de nuevo laredo, a donde salen las corridas?")
        keys = {(f["fact_group"], f["fact_key"]) for f in out}
        assert ("candidate", "city") in keys

    def test_afirmacion_no_se_filtra(self):
        out = _geo_filter()(_facts_nld(), "vivo en nuevo laredo")
        keys = {(f["fact_group"], f["fact_key"]) for f in out}
        assert ("candidate", "city") in keys

    def test_state_tambien_se_filtra_en_preguntas(self):
        facts = [{"fact_group": "candidate", "fact_key": "state", "fact_value": "Tamaulipas", "confidence": 0.88}]
        out = _geo_filter()(facts, "tienen rutas en tamaulipas?")
        assert out == []


# ── 4. Captura de ciudad acotada ─────────────────────────────────────────────

class TestCiudadAcotada:
    def test_ciudad_no_se_traga_la_frase(self):  # FAILS hoy
        facts = extract_profile_facts_as_dict("soy de Laredo ahí de donde a donde me toca ir?")
        assert facts.get("candidate.city") == "Laredo"

    def test_ciudad_corta_en_a_donde(self):  # FAILS hoy
        facts = extract_profile_facts_as_dict("soy de laredo a donde salen las corridas")
        assert facts.get("candidate.city") == "Laredo"

    def test_alias_multipalabra_sigue_funcionando(self):
        facts = extract_profile_facts_as_dict("vivo en san luis potosi")
        assert facts.get("candidate.city") == "San Luis Potosí"

    def test_ciudad_desconocida_se_acota_a_4_tokens(self):
        facts = extract_profile_facts_as_dict("soy de ciudad acuna coahuila zona centro norte")
        city = facts.get("candidate.city") or ""
        assert len(city.split()) <= 4

    def test_ciudad_simple_no_regresa(self):
        facts = extract_profile_facts_as_dict("radico en torreon")
        assert facts.get("candidate.city") == "Torreón"


_NO_GROQ = not os.getenv("GROQ_API_KEY")

# ── 5. Contrato A — normalize_text solo estructural; catálogo gestiona aliases ──

class TestTypoCanonicalizacion:
    def test_normalize_text_es_estructural(self):
        # Con Contrato A, normalize_text NO corrige typos. Solo: minúsculas,
        # sin acentos, puntuación→espacio. El LLM recibe el mensaje original.
        from app.knowledge.text_normalizer import normalize_text
        assert normalize_text("licensia E vijente") == "licensia e vijente"

    def test_normalize_text_no_corrige_frases(self):
        from app.knowledge.text_normalizer import normalize_text
        assert normalize_text("soy d gomez palasio") == "soy d gomez palasio"

    def test_tipo_d_no_se_rompe(self):
        # "d" suelta NO se sustituye: tipo D es categoría de licencia válida.
        from app.knowledge.text_normalizer import normalize_text
        assert normalize_text("licencia tipo d") == "licencia tipo d"

    @pytest.mark.skipif(_NO_GROQ, reason="requiere GROQ_API_KEY — ciudad usa LLM T=0")
    def test_ciudad_con_typo_y_jerga(self):
        facts = extract_profile_facts_as_dict("soy d gomez palasio, que rutas ay?")
        assert facts.get("candidate.city") == "Gómez Palacio"

    @pytest.mark.skipif(_NO_GROQ, reason="requiere GROQ_API_KEY — ciudad usa LLM T=0")
    def test_compuesto_jergoso_del_smoke(self):
        # Smoke 2026-06-12 12:15. license/apto con typos ("licensia","vijente")
        # son extractores aún pendientes de migrar a LLM; no se asertan aquí.
        facts = extract_profile_facts_as_dict(
            "tengo 41 soy d rio bravo tams, licensia E vijente apto vijente, "
            "6 años en sencillo y si tengo cartas"
        )
        assert facts.get("candidate.city") == "Río Bravo"
        assert facts.get("experience.vehicle_type") == "sencillo"

    def test_sensillo_typo_confirma_unidad(self):
        # "sensillo" es alias documentado en catálogo (normalize_vehicle, sin LLM).
        facts = extract_profile_facts_as_dict("manejo sensillo")
        assert facts.get("experience.vehicle_type") == "sencillo"


# ── 6. Intro en la primera respuesta (bug: evento jamás emitido) ──────────────

class TestFirstReplyIntro:
    def test_primera_respuesta_lleva_intro(self, monkeypatch):
        from app.tasks_chatwoot import _maybe_prepend_first_reply_intro
        monkeypatch.setenv("FIRST_REPLY_INTRO_ENABLED", "true")
        out = _maybe_prepend_first_reply_intro("Le platico de la vacante.", {}, is_first_reply=True)
        assert out.startswith("Hola, soy Mundo")

    def test_respuestas_posteriores_sin_intro(self, monkeypatch):
        from app.tasks_chatwoot import _maybe_prepend_first_reply_intro
        monkeypatch.setenv("FIRST_REPLY_INTRO_ENABLED", "true")
        out = _maybe_prepend_first_reply_intro("Claro, le explico.", {}, is_first_reply=False)
        assert out == "Claro, le explico."

    def test_no_duplica_si_ya_se_presento(self, monkeypatch):
        from app.tasks_chatwoot import _maybe_prepend_first_reply_intro
        monkeypatch.setenv("FIRST_REPLY_INTRO_ENABLED", "true")
        saludo = "Hola, soy Mundo del equipo de reclutamiento de Transmontes. ¿En qué ciudad se encuentra?"
        assert _maybe_prepend_first_reply_intro(saludo, {}, is_first_reply=True) == saludo

    def test_sin_flag_no_antepone(self, monkeypatch):
        # Comportamiento legacy: sin is_first_reply explícito y sin evento → no intro.
        from app.tasks_chatwoot import _maybe_prepend_first_reply_intro
        monkeypatch.setenv("FIRST_REPLY_INTRO_ENABLED", "true")
        out = _maybe_prepend_first_reply_intro("Respuesta.", {})
        assert out == "Respuesta."


# ── 7. Pregunta embebida + ciudad anclada a residencia (smoke 13:07) ──────────

JERGOSO = "soy d gomez palasio, que rutas ay y dan voleto pa ir a torreon"


class TestPreguntaEmbebida:
    @pytest.mark.skipif(_NO_GROQ, reason="requiere GROQ_API_KEY — has_embedded_business_question usa LLM T=0")
    def test_detecta_pregunta_sin_signos(self):
        assert CT.has_embedded_business_question(JERGOSO) is True

    def test_guard_no_secuestra_el_turno(self):
        # El orquestador debe responder rutas/boleto; los facts se persisten igual.
        assert CT.should_prioritize_current_turn(JERGOSO) is False

    def test_respuesta_pura_de_perfil_sigue_al_guard(self):
        assert CT.should_prioritize_current_turn("soy de torreon, licencia tipo e") is True

    @pytest.mark.skipif(_NO_GROQ, reason="requiere GROQ_API_KEY — has_embedded_business_question usa LLM T=0")
    def test_dan_boleto_tambien_es_pregunta(self):
        assert CT.has_embedded_business_question("dan boleto para el traslado") is True


class TestCiudadAncladaAResidencia:
    def test_residencia_gana_sobre_destino(self):
        # "soy de gomez palacio ... para ir a torreon" → la residencia, no el destino.
        facts = extract_profile_facts_as_dict(JERGOSO)
        assert facts.get("candidate.city") == "Gómez Palacio"

    def test_alias_mas_cercano_al_marcador(self):
        facts = extract_profile_facts_as_dict("soy de torreon y quiero saber de gomez palacio")
        assert facts.get("candidate.city") == "Torreón"

    def test_neo4j_geo_se_descarta_con_marcador(self):
        fn = getattr(KO, "_drop_unanchored_neo4j_geo", None)
        assert fn is not None
        facts = [
            {"fact_group": "candidate", "fact_key": "city", "fact_value": "Torreón",
             "confidence": 0.92, "neo4j_node_id": "geo_torreon"},
            {"fact_group": "license", "fact_key": "category", "fact_value": "e",
             "confidence": 0.9, "neo4j_node_id": "x"},
        ]
        out = fn(facts, JERGOSO)
        keys = {(f["fact_group"], f["fact_key"]) for f in out}
        assert ("candidate", "city") not in keys
        assert ("license", "category") in keys

    def test_neo4j_geo_se_conserva_sin_marcador(self):
        fn = getattr(KO, "_drop_unanchored_neo4j_geo", None)
        facts = [{"fact_group": "candidate", "fact_key": "city", "fact_value": "Torreón",
                  "confidence": 0.92, "neo4j_node_id": "geo_torreon"}]
        # Respuesta directa a la pregunta de ciudad: sin marcador, Neo4j aplica.
        out = fn(facts, "torreon")
        assert out == facts


# ── 8. "Si" condicional no confirma + typo "vancate" (smoke 19:45/19:46) ──────

PREGUNTA_LICENCIA = "¿Qué tipo de licencia federal tienes y está vigente?"


class TestSiCondicional:
    def test_si_condicional_no_confirma_vigencia(self):
        facts = CT.extract_current_turn_facts(
            "Si me cuentas un chiste de trailero te digo que licencia tengo.",
            PREGUNTA_LICENCIA,
        )
        assert facts.get("license.status") != "vigente"

    def test_guard_no_pisa_el_chiste(self):
        assert CT.should_prioritize_current_turn(
            "Si me cuentas un chiste de trailero te digo",
            PREGUNTA_LICENCIA,
        ) is False

    def test_si_afirmativo_sigue_confirmando(self):
        # No deconstruir: el "sí" real tras la pregunta de apto sigue infiriendo.
        facts = CT.extract_current_turn_facts("si", "¿Tu apto médico está vigente?")
        assert facts.get("medical.apto_status") == "vigente"

    def test_si_con_detalle_sigue_confirmando(self):
        facts = CT.extract_current_turn_facts(
            "si de hace 6 meses me queda todavia", "¿Tu apto médico está vigente?"
        )
        assert facts.get("medical.apto_status") == "vigente"


class TestTypoVacante:
    def test_vancate_es_entrada_de_campania(self):
        assert CT.is_campaign_or_interest_entry(
            "Me interesa la vancate de operador de quinta rueda"
        ) is True

    def test_bacante_tambien(self):
        assert CT.is_campaign_or_interest_entry("me interesa la bacante de operador") is True


# ── 10. Reclamo "ya...", años elípticos y pregunta de cartas (smoke 16:16) ────

PREGUNTA_DOBLE_VIGENCIA = "¿Tiene vigentes su licencia federal y apto médico?"
PREGUNTA_ANIOS = "¿Cuántos años de experiencia tienes como operador?"


class TestYaReclamoNoConfirma:
    def test_ya_le_habia_dicho_no_confirma_apto(self):
        facts = CT.extract_current_turn_facts("Ya le habia dicho que 10 años", PREGUNTA_DOBLE_VIGENCIA)
        assert facts.get("medical.apto_status") != "vigente"
        assert facts.get("license.status") != "vigente"

    def test_ya_solo_sigue_confirmando(self):
        facts = CT.extract_current_turn_facts("ya", "¿Tu apto médico está vigente?")
        assert facts.get("medical.apto_status") == "vigente"


class TestAniosElipticos:
    def test_numero_con_anos_tras_pregunta_de_experiencia(self):
        facts = CT.extract_current_turn_facts(
            "10 años", PREGUNTA_ANIOS, turn_signals=TurnIntentSignals(experience_context=True)
        )
        assert facts.get("experience.years") == "10 años"

    def test_numero_solo_tras_pregunta_de_experiencia(self):
        # `turn_signals` inyectado determinista: en vivo esta señal la calcula
        # classify_turn_intent (LLM); aquí se fija para no depender de una llamada
        # real y no-determinista en el test.
        facts = CT.extract_current_turn_facts(
            "10", PREGUNTA_ANIOS, turn_signals=TurnIntentSignals(experience_context=True)
        )
        assert facts.get("experience.years") == "10 años"

    def test_numero_sin_contexto_no_se_guarda(self):
        facts = CT.extract_current_turn_facts(
            "10", "¿En qué ciudad te encuentras actualmente?",
            turn_signals=TurnIntentSignals(experience_context=False),
        )
        assert "experience.years" not in facts

    def test_numero_tras_pregunta_de_ciudad_no_es_experiencia(self):
        facts = CT.extract_current_turn_facts(
            "10 años", None, turn_signals=TurnIntentSignals(experience_context=False)
        )
        assert "experience.years" not in facts


class TestPreguntaDeCartas:
    @pytest.mark.skipif(_NO_GROQ, reason="requiere GROQ_API_KEY — has_embedded_business_question usa LLM T=0")
    def test_cuantas_necesita_es_pregunta(self):
        assert CT.has_embedded_business_question(
            "Nada más tengo 1 si le sirve o cuantas nececita?"
        ) is True

    @pytest.mark.skipif(_NO_GROQ, reason="requiere GROQ_API_KEY — has_embedded_business_question usa LLM T=0")
    def test_cuantas_cartas_piden(self):
        assert CT.has_embedded_business_question("cuantas cartas piden") is True


# ── 9. Humor LLM con barda (fallback determinista del seed) ───────────────────

FALLBACK_JOKE = "Va uno rapidito: ¿por qué los traileros no juegan a las escondidas? Porque siempre los hallan en su ruta. 🚛 Ahora sí, seguimos con su registro."


class TestHumorLLMConBarda:
    def test_chiste_valido_lleva_puente(self, monkeypatch):
        monkeypatch.setattr(KO, "call_llm", lambda prompt: "¿Qué le dijo un tracto a otro? Nos vemos en la báscula, compa.")
        out = KO._generate_joke_reply(fallback=FALLBACK_JOKE)
        assert out.endswith(KO._JOKE_BRIDGE)
        assert "báscula" in out

    def test_llm_vacio_usa_fallback(self, monkeypatch):
        monkeypatch.setattr(KO, "call_llm", lambda prompt: "")
        assert KO._generate_joke_reply(fallback=FALLBACK_JOKE) == FALLBACK_JOKE

    def test_llm_error_usa_fallback(self, monkeypatch):
        def _boom(prompt):
            raise RuntimeError("timeout")
        monkeypatch.setattr(KO, "call_llm", _boom)
        assert KO._generate_joke_reply(fallback=FALLBACK_JOKE) == FALLBACK_JOKE

    def test_chiste_vetado_usa_fallback(self, monkeypatch):
        monkeypatch.setattr(KO, "call_llm", lambda prompt: "Un trailero borracho llegó a la báscula...")
        assert KO._generate_joke_reply(fallback=FALLBACK_JOKE) == FALLBACK_JOKE

    def test_chiste_kilometrico_usa_fallback(self, monkeypatch):
        monkeypatch.setattr(KO, "call_llm", lambda prompt: "x" * 400)
        assert KO._generate_joke_reply(fallback=FALLBACK_JOKE) == FALLBACK_JOKE

    def test_template_static_joke_pasa_por_llm(self, monkeypatch):
        monkeypatch.setattr(KO, "call_llm", lambda prompt: "¿Cuál es el colmo de un trailero? Que su novia lo traiga cortito.")
        contract = {"reply_template": {"id": "static_joke", "text": FALLBACK_JOKE}}
        out = KO._controlled_reply_from_contract(contract)
        assert out.endswith(KO._JOKE_BRIDGE)

    def test_otros_templates_no_pasan_por_llm(self, monkeypatch):
        def _boom(prompt):
            raise AssertionError("call_llm no debe invocarse para templates normales")
        monkeypatch.setattr(KO, "call_llm", _boom)
        contract = {"reply_template": {"id": "static_greeting", "text": "Hola, soy Mundo."}}
        assert KO._controlled_reply_from_contract(contract) == "Hola, soy Mundo."
