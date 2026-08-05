"""TurnDecision inmutable (unified-turn-decision-v2-projection, Fase 1 / D1).
Deterministas: sin BD/LLM.
"""
from __future__ import annotations

import dataclasses

import pytest

from app.knowledge.turn_decision import TurnDecision


def test_reply_is_immutable():
    d = TurnDecision(reply="Hola, soy Mundo.")
    with pytest.raises(dataclasses.FrozenInstanceError):
        d.reply = "otro texto"  # type: ignore[misc]


def test_all_fields_frozen():
    d = TurnDecision(reply="x", requires_human=False)
    for f in ("delivery_policy", "requires_human", "handoff_reason", "next_question", "should_continue_profile"):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(d, f, "mut")


def test_collections_normalized_to_tuples():
    d = TurnDecision(reply="x", facts_to_write=[1, 2], asked_field_keys=["candidate.city"])
    assert isinstance(d.facts_to_write, tuple)
    assert isinstance(d.asked_field_keys, tuple)
    assert d.asked_field_keys == ("candidate.city",)


def test_defaults():
    d = TurnDecision(reply="x")
    assert d.delivery_policy == "send"
    assert d.should_continue_profile is True
    assert d.requires_human is False
    assert d.facts_to_write == () and d.asked_field_keys == ()


def test_is_deliverable():
    assert TurnDecision(reply="Hola").is_deliverable is True
    assert TurnDecision(reply="  ").is_deliverable is False
    assert TurnDecision(reply="Hola", delivery_policy="suppress").is_deliverable is False
    # ack_then_handoff con texto sí entrega el ack
    assert TurnDecision(reply="Lo canalizo", delivery_policy="ack_then_handoff").is_deliverable is True
