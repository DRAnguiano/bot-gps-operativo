"""fix-compound-summary-confirmation-and-reencauce — contratos de los 3 defectos.

Bug en vivo conv 175 (2026-07-10): (1) la confirmación del resumen se perdía en
turnos compuestos (afirmación + pregunta de negocio → guard no dispara → fact no
persistido); (2) el re-encauce natural moría por NameError (`active_facts` de otro
scope) tragado por el except genérico; (3) voz inconsistente en transiciones
("indicarme"/"indicarnos").

Todo determinista: sin LLM real, sin BD.
"""
from __future__ import annotations

import inspect

from app.knowledge.current_turn import _extract_context_confirmation_facts
from app.knowledge.text_normalizer import normalize_text
from app.knowledge.turn_intent_classifier import TurnIntentSignals


_SUMMARY_BOT_MSG = (
    "¡Listo! Antes de continuar, le confirmo sus datos registrados:\n"
    "· Nombre: Salvador Hernandez\n· Ciudad: Torreón\n· Unidad: sencillo\n"
    "¿Así es correcto?"
)


def _confirm_facts(message: str) -> dict:
    return _extract_context_confirmation_facts(
        normalize_text(message), _SUMMARY_BOT_MSG, _turn_signals=TurnIntentSignals(),
    )


class TestCompoundSummaryConfirmationDetection:
    def test_affirmation_plus_business_question_confirms(self):
        # El caso vivo: afirmación seguida de pregunta de negocio en el mismo
        # mensaje (el literal es solo ejemplo del patrón afirmación+pregunta).
        facts = _confirm_facts("Si todo bien señor, me falto preguntarle hacen dopin?")
        assert facts.get("funnel.summary_confirmed") == "true"

    def test_plain_affirmation_confirms(self):
        assert _confirm_facts("sí, correcto").get("funnel.summary_confirmed") == "true"

    def test_negation_plus_question_does_not_confirm(self):
        facts = _confirm_facts("no, la ciudad esta mal. ¿hacen antidoping?")
        assert "funnel.summary_confirmed" not in facts

    def test_correction_does_not_confirm(self):
        facts = _confirm_facts("la edad esta vencida, tengo otro dato")
        assert "funnel.summary_confirmed" not in facts


class TestWorkerPersistsConfirmationOutsideGuard:
    def test_compound_persist_block_wired_before_guard(self):
        # El fact debe persistirse aunque _guard_should_fire sea False (pregunta de
        # negocio presente). Estructural: el bloque existe, corre sobre la condición
        # negada del guard y usa el source auditable.
        from app import tasks_chatwoot
        src = inspect.getsource(tasks_chatwoot.process_chatwoot_debounced_message)
        assert "summary_confirm_compound" in src
        assert "[SUMMARY_CONFIRM_COMPOUND]" in src
        i_block = src.index("summary_confirm_compound")
        i_guard_branch = src.index("if _guard_should_fire:")
        assert i_block < i_guard_branch, (
            "la persistencia compuesta debe evaluarse antes de la rama del guard"
        )
        assert "not _guard_should_fire" in src

    def test_compound_persist_is_gated_on_confirmed_true(self):
        from app import tasks_chatwoot
        src = inspect.getsource(tasks_chatwoot.process_chatwoot_debounced_message)
        assert '_current_turn_facts.get("funnel.summary_confirmed") == "true"' in src


class TestReencauceScopeRegression:
    def test_handle_message_does_not_reference_foreign_active_facts(self):
        # NameError original: `active_facts` vive en _build_funnel_nudge, no en
        # handle_message. Si reaparece en handle_message, esta prueba truena antes
        # de que el except genérico lo esconda en producción.
        from app.orchestrators import knowledge_orchestrator as KO
        src = inspect.getsource(KO.handle_message)
        # El uso que producía el NameError (la palabra puede aparecer en comentarios).
        assert "facts=active_facts" not in src, (
            "handle_message no debe usar active_facts (scope de _build_funnel_nudge); "
            "usa el merge local _reencauce_facts"
        )
        assert "_reencauce_facts" in src

    def test_reencauce_branch_passes_local_facts(self):
        from app.orchestrators import knowledge_orchestrator as KO
        src = inspect.getsource(KO.handle_message)
        assert "facts=_reencauce_facts" in src


class TestTransitionVoiceInstruction:
    def test_prompt_pins_first_person_singular_usted(self):
        import os
        from unittest import mock
        from app.knowledge import current_turn as CT

        captured = {}

        def _spy(system, user, **kw):
            captured["user"] = user
            return "Va. ¿Me podría indicar su ciudad?"

        with mock.patch.dict(os.environ, {"FUNNEL_LLM_TRANSITIONS": "true"}), \
             mock.patch("app.gemini_client.dispatch_generation", side_effect=_spy):
            CT.generate_funnel_transition_reply(
                "tengo licencia E", {"license.category": "E"},
                "¿En qué ciudad se encuentra?", fallback="Bien. ¿Su ciudad?",
            )
        assert "PRIMERA PERSONA DEL SINGULAR" in captured["user"]
        assert "indicarnos" in captured["user"]  # el contraejemplo prohibido está citado
