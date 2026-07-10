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
