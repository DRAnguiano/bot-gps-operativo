"""fix-note-risk-and-situated-denial-replies — contratos de los 4 defectos.

Conv 178 (WhatsApp, 2026-07-13): (1) "…todo el show pa k vea que si se arma"
clasificado como admisión de seguridad → riesgo pegado al lead → 3 notas de
riesgo en turnos low + línea "Riesgo: Alto" redundante; (2) vigencias "dos
años" en palabras; (3) acuses predefinidos apilados (3 fragmentos + pregunta
repetida) en turnos de denegación.

Todo determinista: sin LLM real, sin BD.
"""
from __future__ import annotations

import inspect

from unittest import mock

from app.chatwoot_note_sync import render_candidate_note
from app.knowledge.current_turn import canonicalize_duration_digits


def _context(risk_level_lead: str = "low", requires_human: bool = False) -> dict:
    return {
        "lead": {
            "lead_key": "chatwoot:test",
            "risk_level": risk_level_lead,
            "requires_human": requires_human,
            "display_name": "X",
        },
        "conversation": {},
        "facts": {"candidate.name": "María Zúñiga", "candidate.city": "Torreón"},
        "last_message": {"message": "hola"},
    }


class TestRiskNoteByTurnSignal:
    def test_high_risk_turn_renders_risk_note_without_level_line(self):
        note = render_candidate_note(
            _context("high", True), ["riesgo_alto"],
            fallback_last_message="mensaje con señal",
            current_risk_level="high",
        )
        assert "Señal de Riesgo" in note
        assert "Riesgo: Alto" not in note  # línea redundante eliminada (D1)

    def test_low_risk_turn_ignores_sticky_lead_risk(self):
        # Lead con riesgo histórico (label presente) pero turno actual low →
        # la nota corresponde al contenido del turno, no al riesgo pegado (D2).
        note = render_candidate_note(
            _context("high", False), ["riesgo_alto"],
            fallback_last_message="tengo licencia E",
            current_risk_level="low",
        )
        assert "Señal de Riesgo" not in note

    def test_legacy_caller_without_signal_keeps_label_behavior(self):
        note = render_candidate_note(
            _context("high", True), ["riesgo_alto"],
            fallback_last_message="mensaje",
        )
        assert "Señal de Riesgo" in note


class TestClassifierColloquialCounterexamples:
    def test_prompt_teaches_colloquialisms_are_not_admission(self):
        from app.knowledge import intent_classifier as IC
        src = inspect.getsource(IC)
        # Contraejemplo vivo y regla (el literal del caso es solo ejemplo del patrón).
        assert "se arma" in src
        assert "deme chance" in src
        # La admisión real permanece enseñada.
        assert "antes consumia" in src
        assert '"is_admission":true' in src


class TestDurationDigits:
    def test_written_numbers_become_digits(self):
        assert canonicalize_duration_digits("dos años") == "2 años"
        assert canonicalize_duration_digits("vence en un mes") == "vence en 1 mes"
        assert canonicalize_duration_digits("como en tres semanas") == "como en 3 semanas"

    def test_dates_and_free_text_untouched(self):
        assert canonicalize_duration_digits("31 de diciembre de 2027") == "31 de diciembre de 2027"
        assert canonicalize_duration_digits("vencido") == "vencido"
        # "un" fuera del patrón de duración no se toca.
        assert canonicalize_duration_digits("un comprobante") == "un comprobante"

    def test_extractor_chokepoint_applies_it(self):
        from app.knowledge import turn_extractor as TE
        src = inspect.getsource(TE)
        assert "canonicalize_duration_digits" in src


class TestSituatedDenialReply:
    def test_requires_human_uses_situated_generation(self):
        from app.orchestrators.knowledge_orchestrator import _controlled_reply_from_contract
        with mock.patch(
            "app.gemini_client.dispatch_generation",
            return_value="Le agradezco la confianza; ese punto lo revisa nuestro equipo y le damos seguimiento.",
        ) as m:
            out = _controlled_reply_from_contract({"requires_human": True})
        assert "nuestro equipo" in out
        assert out != "Ese punto debe revisarlo nuestro equipo antes de continuar. Lo dejo anotado para seguimiento."
        m.assert_called_once()

    def test_requires_human_degrades_to_canned_on_failure(self):
        from app.orchestrators.knowledge_orchestrator import _controlled_reply_from_contract
        with mock.patch(
            "app.gemini_client.dispatch_generation", side_effect=RuntimeError("boom"),
        ):
            out = _controlled_reply_from_contract({"requires_human": True})
        assert out == "Ese punto debe revisarlo nuestro equipo antes de continuar. Lo dejo anotado para seguimiento."

    def test_situated_prompt_pins_usted_voice(self):
        from app.orchestrators import knowledge_orchestrator as KO
        src = inspect.getsource(KO._generate_situated_reply)
        assert "usted" in src
        assert "tutees" in src


class TestJoinDedupe:
    def test_nudge_already_in_reply_not_reappended(self):
        from app.orchestrators.knowledge_orchestrator import _join_with_nudge
        q = "¿Cuenta con su documento de semanas cotizadas del IMSS?"
        reply = f"Entiendo su situación.\n\n{q}"
        assert _join_with_nudge(reply, q) == reply

    def test_nudge_appended_once_when_absent(self):
        from app.orchestrators.knowledge_orchestrator import _join_with_nudge
        out = _join_with_nudge("Entiendo su situación.", "¿Su ciudad?")
        assert out.count("¿Su ciudad?") == 1

    def test_empty_cases(self):
        from app.orchestrators.knowledge_orchestrator import _join_with_nudge
        assert _join_with_nudge("", "¿Su ciudad?") == "¿Su ciudad?"
        assert _join_with_nudge("Hola.", "") == "Hola."

    def test_all_join_points_use_dedupe_helper(self):
        # Regresión estructural del apilamiento (conv 178, respuesta 4302): los
        # joins de reply+nudge pasan por _join_with_nudge, no por f-string cruda.
        from app.orchestrators import knowledge_orchestrator as KO
        src = inspect.getsource(KO.handle_message)
        assert 'f"{reply}\\n\\n{nudge}"' not in src
        assert 'f"{reply}\\n\\n{_next_q}"' not in src
        assert "_join_with_nudge" in src
