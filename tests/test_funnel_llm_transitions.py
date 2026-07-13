"""Transición del funnel generada por LLM situado (FUNNEL_LLM_TRANSITIONS).

Feedback usuario 2026-07-09: el conector enlatado ("Va.") + pregunta pegada se
siente robótico. El acuse primario lo genera el LLM con contexto (mensaje del
candidato, datos capturados este turno, único dato faltante); el conector +
pregunta literal quedan SOLO como degradación (D8: enlatado = fallback).

Contrato clave: la generación NUNCA cambia QUÉ dato se pide ni el orden del
funnel (eso sigue determinista); solo la voz. Todo mockeado, sin LLM real.
"""
from __future__ import annotations

import os
from unittest import mock

from app.knowledge import current_turn as CT


_FALLBACK = "Bien. ¿En qué ciudad se encuentra actualmente?"
_QUESTION = "¿En qué ciudad se encuentra actualmente?"
_MESSAGE = "tengo 10 años en full y licencia E vigente"
_FRESH = {"experience.years": "10", "license.category": "E"}


def _call(**kwargs):
    defaults = dict(
        message=_MESSAGE, fresh_facts=_FRESH, question=_QUESTION, fallback=_FALLBACK,
    )
    defaults.update(kwargs)
    return CT.generate_funnel_transition_reply(**defaults)


class TestFlagGate:
    def test_flag_off_returns_fallback_without_llm_call(self):
        with mock.patch.dict(os.environ, {"FUNNEL_LLM_TRANSITIONS": "false"}), \
             mock.patch("app.gemini_client.dispatch_generation") as m:
            assert _call() == _FALLBACK
        m.assert_not_called()

    def test_flag_absent_defaults_off(self):
        env = {k: v for k, v in os.environ.items() if k != "FUNNEL_LLM_TRANSITIONS"}
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch("app.gemini_client.dispatch_generation") as m:
            assert _call() == _FALLBACK
        m.assert_not_called()


@mock.patch.dict(os.environ, {"FUNNEL_LLM_TRANSITIONS": "true"})
class TestStructuredQuestionVerbatim:
    """El resumen de datos NUNCA se reformula (conv 176: la reescritura 'válida'
    entregó la pregunta de confirmación SIN la lista de datos).

    El resumen se construye con el builder REAL (build_funnel_summary) sobre datos
    arbitrarios: el guard detecta el esqueleto estructural del sistema, no un
    literal, así que candidato/datos distintos dan el mismo comportamiento.
    """

    def test_summary_question_returns_fallback_for_any_candidate_data(self):
        candidates = [
            {"candidate.name": "Juan Raul Ramos", "candidate.city": "Guadalajara",
             "experience.vehicle_type": "full", "license.category": "E"},
            {"candidate.name": "María Zúñiga", "candidate.city": "Torreón",
             "experience.vehicle_type": "sencillo", "license.category": "B",
             "experience.years": "8"},
        ]
        for facts in candidates:
            summary_q = CT.build_funnel_summary(facts)
            fb = f"Gracias.\n\n{summary_q}"
            with mock.patch("app.gemini_client.dispatch_generation") as m:
                out = _call(question=summary_q, fallback=fb)
            assert out == fb, f"resumen reformulado para {facts.get('candidate.name')}"
            m.assert_not_called()

    def test_bulleted_content_returns_fallback_without_llm_call(self):
        # Cualquier pregunta con viñetas de datos porta contenido estructurado,
        # aunque no sea el resumen canónico completo.
        q = f"Le leo lo que tengo:{CT.SUMMARY_BULLET}Licencia: E{CT.SUMMARY_BULLET}Experiencia: 15\n¿Está bien?"
        with mock.patch("app.gemini_client.dispatch_generation") as m:
            out = _call(question=q, fallback="FB")
        assert out == "FB"
        m.assert_not_called()

    def test_atomic_question_still_reformulated(self):
        with mock.patch(
            "app.gemini_client.dispatch_generation",
            return_value="Va, gracias. ¿Me podría indicar su ciudad?",
        ) as m:
            out = _call()
        assert out == "Va, gracias. ¿Me podría indicar su ciudad?"
        m.assert_called_once()

    def test_guard_markers_are_the_builders_markers(self):
        # Regresión de fuente única: si alguien cambia la redacción del resumen en
        # build_funnel_summary sin tocar las constantes, esta prueba truena antes
        # de que el guard quede ciego en producción.
        summary = CT.build_funnel_summary({"candidate.name": "X", "candidate.city": "Y"})
        assert CT.SUMMARY_HEADER in summary
        assert CT.SUMMARY_BULLET in summary


@mock.patch.dict(os.environ, {"FUNNEL_LLM_TRANSITIONS": "true"})
class TestGeneratedPrimary:
    def test_generated_reply_is_used(self):
        generated = "Qué buen recorrido trae. ¿En qué ciudad se encuentra ahorita?"
        with mock.patch("app.gemini_client.dispatch_generation", return_value=generated):
            assert _call() == generated

    def test_prompt_carries_message_facts_and_question(self):
        # El LLM decide CÓMO decirlo, pero el contexto (qué dijo el candidato, qué
        # se capturó y qué único dato falta) se le da completo y verbatim.
        captured = {}

        def _spy(system, user, **kw):
            captured["system"] = system
            captured["user"] = user
            return "Va que va. ¿Su ciudad?"

        with mock.patch("app.gemini_client.dispatch_generation", side_effect=_spy):
            _call()
        assert _MESSAGE in captured["user"]
        assert "experience.years: 10" in captured["user"]
        assert _QUESTION in captured["user"]
        assert captured["system"]  # persona Mundo, no vacío

    def test_llm_failure_degrades_to_fallback(self):
        with mock.patch("app.gemini_client.dispatch_generation", side_effect=RuntimeError("503")):
            assert _call() == _FALLBACK

    def test_empty_output_degrades_to_fallback(self):
        with mock.patch("app.gemini_client.dispatch_generation", return_value="  "):
            assert _call() == _FALLBACK

    def test_output_without_question_degrades_to_fallback(self):
        # La transición DEBE pedir el dato faltante: una salida sin pregunta dejaría
        # el funnel sin avanzar y el turno colgado.
        with mock.patch("app.gemini_client.dispatch_generation", return_value="Muy buen perfil, gracias."):
            assert _call() == _FALLBACK

    def test_runaway_output_degrades_to_fallback(self):
        with mock.patch("app.gemini_client.dispatch_generation", return_value="¿bla? " + "x" * 600):
            assert _call() == _FALLBACK


@mock.patch.dict(os.environ, {"FUNNEL_LLM_TRANSITIONS": "true"})
class TestWiredIntoAckPath:
    def test_build_current_turn_ack_uses_generated_transition(self):
        # Path del guard del worker: un turno con datos nuevos y funnel incompleto
        # emite la transición generada en vez del conector enlatado.
        generated = "Se agradece el detalle. ¿En qué ciudad anda actualmente?"
        with mock.patch("app.gemini_client.dispatch_generation", return_value=generated):
            reply = CT.build_current_turn_ack(
                "tengo 10 años en full",
                merged_facts={"experience.years": "10"},
                pre_current_facts={"experience.years": "10"},
            )
        assert reply == generated

    def test_build_current_turn_ack_fallback_keeps_connector_contract(self):
        # Degradación: sin LLM la respuesta conserva el contrato previo
        # (conector del banco + pregunta determinista del funnel).
        with mock.patch("app.gemini_client.dispatch_generation", side_effect=RuntimeError("caído")):
            reply = CT.build_current_turn_ack(
                "tengo 10 años en full",
                merged_facts={"experience.years": "10"},
                pre_current_facts={"experience.years": "10"},
            )
        assert any(reply.startswith(c) for c in CT._FUNNEL_CONNECTORS)
        assert "?" in reply
