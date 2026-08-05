"""Override determinista: turno de datos secuestrado por aliases del diccionario.

Clase conv-166/172 (D6 gemini-full-provider-migration): un mensaje que solo APORTA
datos de perfil ("tengo licencia E vigente y cartas laborales...") contiene palabras
que son aliases del Term `documentos_requisitos` en Neo4j, y el clasificador de
Terms lo enruta a rag como si preguntara los requisitos. El override revierte esa
ruta al funnel de perfilamiento cuando el extractor unificado (juicio LLM) dice que
NO hay pregunta embebida y el turno sí trae facts extraídos.

Todo puro: sin LLM, sin Neo4j, sin Postgres.
"""
from __future__ import annotations

from app.knowledge.turn_extractor import TurnExtraction, FieldValue
from app.knowledge.turn_intent_classifier import TurnIntentSignals
from app.orchestrators.knowledge_orchestrator import _override_rag_hijack_on_data_turn


def _rag_contract(**extra) -> dict:
    base = {
        "intent": "requirements_documents",
        "route": "rag",
        "risk_level": "low",
        "recognized_terms": ["documentos_requisitos"],
        "reason": "term_documentos_requisitos_suggests_requirements_documents",
    }
    base.update(extra)
    return base


def _extraction_with_fields(**fields) -> TurnExtraction:
    return TurnExtraction(
        fields={k: FieldValue(value=v, explicit_marker=True) for k, v in fields.items()},
    )


_DATA_ONLY_MESSAGE = (
    "Juan Esteban Munera, tengo 37 años, 10 años de experiencia en full, "
    "dispongo de apto y licencia tipo E vigente y tengo cartas laborales."
)


class TestDataTurnReroutedToFunnel:
    def test_data_only_turn_reverts_rag_to_profile(self):
        # El candidato declara datos (sin preguntar nada) pero los aliases del
        # diccionario dispararon rag: la ruta vuelve al perfilamiento.
        out = _override_rag_hijack_on_data_turn(
            _rag_contract(),
            _DATA_ONLY_MESSAGE,
            _extraction_with_fields(**{"license.category": "E", "experience.years": "10"}),
            TurnIntentSignals(has_embedded_question=False),
        )
        assert out["route"] == "profile"
        assert out["intent"] == "candidate_profile_signal"
        assert out["requires_rag"] is False
        assert out["reason"] == "rag_hijack_data_turn_override"

    def test_original_contract_not_mutated(self):
        contract = _rag_contract()
        _override_rag_hijack_on_data_turn(
            contract,
            _DATA_ONLY_MESSAGE,
            _extraction_with_fields(**{"candidate.age": "37"}),
            TurnIntentSignals(),
        )
        assert contract["route"] == "rag"  # el override trabaja sobre copia


class TestRagRoutePreservedWhenQuestionExists:
    def test_embedded_question_signal_keeps_rag(self):
        # Mensaje compuesto real (datos + duda): la señal LLM manda y rag responde.
        out = _override_rag_hijack_on_data_turn(
            _rag_contract(),
            "tengo licencia E, y que documentos piden aparte",
            _extraction_with_fields(**{"license.category": "E"}),
            TurnIntentSignals(has_embedded_question=True),
        )
        assert out["route"] == "rag"

    def test_literal_question_mark_keeps_rag(self):
        # Cinturón: un "?" explícito nunca se silencia, aunque la señal LLM
        # (p. ej. degradada a neutra por fallo) diga que no hay pregunta.
        out = _override_rag_hijack_on_data_turn(
            _rag_contract(),
            "tengo licencia E vigente, ¿qué más piden?",
            _extraction_with_fields(**{"license.category": "E"}),
            TurnIntentSignals(has_embedded_question=False),
        )
        assert out["route"] == "rag"

    def test_no_extracted_fields_keeps_rag(self):
        # Sin datos en el turno no hay evidencia de que sea un turno de perfil:
        # la clasificación del diccionario se respeta (pregunta pura sin "?").
        out = _override_rag_hijack_on_data_turn(
            _rag_contract(),
            "que papeles piden",
            TurnExtraction(),
            TurnIntentSignals(has_embedded_question=False),
        )
        assert out["route"] == "rag"

    def test_extraction_missing_keeps_rag(self):
        out = _override_rag_hijack_on_data_turn(
            _rag_contract(), "que papeles piden", None, TurnIntentSignals()
        )
        assert out["route"] == "rag"


class TestNonRagRoutesUntouched:
    def test_handoff_route_never_overridden(self):
        # requires_human/handoff deterministas tienen prioridad absoluta: el
        # override solo conoce la ruta rag.
        contract = _rag_contract(route="human_handoff", intent="business_route_us", requires_human=True)
        out = _override_rag_hijack_on_data_turn(
            contract,
            _DATA_ONLY_MESSAGE,
            _extraction_with_fields(**{"license.category": "E"}),
            TurnIntentSignals(),
        )
        assert out is contract

    def test_profile_route_untouched(self):
        contract = _rag_contract(route="profile", intent="candidate_profile_signal")
        out = _override_rag_hijack_on_data_turn(
            contract,
            _DATA_ONLY_MESSAGE,
            _extraction_with_fields(**{"candidate.age": "37"}),
            TurnIntentSignals(),
        )
        assert out is contract
