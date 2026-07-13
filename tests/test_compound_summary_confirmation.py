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


class TestDetectionOverFullBotMessage:
    """conv 176: el resumen re-emitido al FINAL de una respuesta larga (>500 chars)
    quedaba fuera del truncado head-first y el detector no lo veía; y la variante
    plural ("son correctos") no matcheaba el marcador singular."""

    def _facts(self, message: str, bot_msg: str) -> dict:
        return _extract_context_confirmation_facts(
            normalize_text(message), bot_msg, _turn_signals=TurnIntentSignals(),
        )

    def test_summary_at_tail_of_long_reply_confirms(self):
        # Resumen del builder REAL (datos arbitrarios) al final de una respuesta
        # larga, como lo produce el nudge tras un turno RAG.
        from app.knowledge.current_turn import build_funnel_summary
        summary = build_funnel_summary({
            "candidate.name": "María Zúñiga", "candidate.city": "Torreón",
            "experience.vehicle_type": "sencillo", "license.category": "B",
        })
        long_reply = ("Para el proceso se necesita cumplir varios puntos. " * 15
                      + "\n\n" + summary)
        assert len(long_reply) > 500  # el head-truncate original lo dejaba fuera
        facts = self._facts("sí, así es, ¿cuándo empiezo?", long_reply)
        assert facts.get("funnel.summary_confirmed") == "true"

    def test_plural_confirmation_variant_confirms(self):
        # Variante que el propio sistema emitió en vivo (reformulación LLM).
        bot = "Muchas gracias por la información. ¿Me podría confirmar que los datos son correctos?"
        facts = self._facts("si, todo bien", bot)
        assert facts.get("funnel.summary_confirmed") == "true"

    def test_worker_captures_bot_message_tail_not_head(self):
        # Regresión: la captura de last_bot_message en el worker debe conservar la
        # COLA (donde vive la pregunta activa), no la cabeza.
        from app import tasks_chatwoot
        src = inspect.getsource(tasks_chatwoot.process_chatwoot_debounced_message)
        # Anclado a la línea de captura (otros [:500] del worker son legítimos).
        assert '_m.get("message") or "")[:500]' not in src, (
            "head-truncate reintroducido en la captura de last_bot_message"
        )
        assert '_m.get("message") or "")[-2000:]' in src


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


class TestSameTurnConfirmationConsumption:
    """conv 177: la confirmación se persistía pero el MISMO turno re-emitía el
    resumen recién confirmado — el nudge se componía con facts pre-turno. El merge
    en _build_funnel_nudge consume la confirmación detectada en el turno."""

    _COMPLETE_FACTS = {
        "candidate.name": "María Zúñiga", "candidate.city": "Torreón",
        "candidate.age": "38", "experience.vehicle_type": "sencillo",
        "experience.years": "8", "license.category": "E",
        "license.expiration_text": "dos años",
        "medical.apto_expiration_text": "dos años",
        "documents.proof": "cartas", "documents.labor_letters_status": "disponibles",
    }

    def _nudge(self, message: str, bot_message: str, facts: dict | None = None):
        from app.orchestrators.knowledge_orchestrator import _build_funnel_nudge
        base = facts if facts is not None else self._COMPLETE_FACTS
        lead_memory = {
            "lead": {"lead_key": "chatwoot:test"},
            "facts": [
                {"fact_group": k.split(".")[0], "fact_key": k.split(".")[1],
                 "fact_value": v}
                for k, v in base.items()
            ],
            "messages": [{"role": "assistant", "message": bot_message}],
        }
        contract = {"intent": "candidate_profile_signal", "route": "profile",
                    "business_signals": [], "requires_human": False}
        q, _keys = _build_funnel_nudge(
            message, contract, lead_memory,
            turn_signals=TurnIntentSignals(), pre_validated_facts=[],
        )
        return q

    def test_compound_affirmation_advances_past_summary_same_turn(self):
        from app.knowledge.current_turn import SUMMARY_HEADER, build_funnel_summary
        bot = ("Sí, contamos con esa prestación desde el primer día.\n\n"
               + build_funnel_summary(self._COMPLETE_FACTS))
        # Premisa: SIN confirmación, el nudge re-emitiría el resumen.
        assert SUMMARY_HEADER in (self._nudge("¿me pagan seguro?", bot) or "")
        # Con afirmación compuesta el mismo turno avanza al cierre.
        q = self._nudge("si, todo bien, ¿hacen antidoping?", bot)
        assert q is not None
        assert SUMMARY_HEADER not in q

    def test_negation_keeps_current_behavior(self):
        from app.knowledge.current_turn import SUMMARY_HEADER, build_funnel_summary
        bot = build_funnel_summary(self._COMPLETE_FACTS)
        q = self._nudge("no, la ciudad esta mal", bot)
        assert SUMMARY_HEADER in (q or "")

    def test_merge_is_scoped_to_summary_confirmed_only(self):
        # El detector de contexto puede inferir otras claves; SOLO
        # funnel.summary_confirmed debe entrar al nudge por esta vía. Escenario
        # sin handlers existentes (la pregunta de ciudad no tiene inferencia por
        # afirmación): si candidate.city se colara desde el mock, el paso se
        # daría por contestado y el nudge saltaría al resumen.
        from unittest import mock
        from app.knowledge.current_turn import SUMMARY_HEADER
        facts = dict(self._COMPLETE_FACTS)
        del facts["candidate.city"]  # paso pendiente
        with mock.patch(
            "app.knowledge.current_turn._extract_context_confirmation_facts",
            return_value={"candidate.city": "Torreón"},
        ):
            q = self._nudge("ok", "¿En qué ciudad se encuentra actualmente?", facts)
        assert q is not None
        assert "ciudad" in q.lower()
        assert SUMMARY_HEADER not in q


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
