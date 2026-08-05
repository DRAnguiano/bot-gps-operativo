"""B6.1 — dedup de prefijo/ack en la respuesta visible del current_turn guard.

Cubre el helper puro `_join_ack_and_question` (sin extracción ni BD) y una
verificación de integración por `build_current_turn_ack` para confirmar que el
reply visible no duplica "Perfecto".
"""
from __future__ import annotations

import app.knowledge.current_turn as CT
from app.knowledge.current_turn import (
    _join_ack_and_question,
    _strip_leading_perfecto,
    build_current_turn_ack,
)


# ---------------------------------------------------------------------------
# Helper puro
# ---------------------------------------------------------------------------

def test_join_dedups_double_perfecto():
    out = _join_ack_and_question(
        "Perfecto, registro ciudad Torreón, licencia tipo E.",
        "Perfecto. ¿Cuántos años de experiencia tienes como operador?",
    )
    assert out == ("Perfecto, registro ciudad Torreón, licencia tipo E. "
                   "¿Cuántos años de experiencia tienes como operador?")
    assert out.count("Perfecto") == 1
    assert "¿Cuántos años de experiencia" in out  # se preserva la apertura ¿


def test_join_empty_prefix_keeps_question():
    q = "Perfecto. ¿Cuántos años de experiencia tienes como operador?"
    assert _join_ack_and_question("", q) == q


def test_join_question_none_returns_prefix():
    assert _join_ack_and_question("Perfecto, lo dejo registrado.", None) == "Perfecto, lo dejo registrado."


def test_join_question_empty_returns_prefix():
    assert _join_ack_and_question("Perfecto, lo dejo registrado.", "   ") == "Perfecto, lo dejo registrado."


def test_join_question_without_perfecto_unchanged():
    out = _join_ack_and_question("Perfecto, registro ciudad Torreón.", "¿Cuentas con cartas laborales?")
    assert out == "Perfecto, registro ciudad Torreón. ¿Cuentas con cartas laborales?"
    assert out.count("Perfecto") == 1


def test_strip_leading_perfecto_preserves_inverted_question_mark():
    assert _strip_leading_perfecto("Perfecto. ¿Cuántos años?") == "¿Cuántos años?"


def test_strip_leading_perfecto_recapitalizes_next_word():
    assert _strip_leading_perfecto("Perfecto, ya casi terminamos. ¿X?") == "Ya casi terminamos. ¿X?"


# ---------------------------------------------------------------------------
# Acuse del funnel sin eco de datos (feedback usuario 2026-07-03): un conector
# breve y VARIADO + la siguiente pregunta del funnel — SIN repetir el valor del
# dato recién aportado. Domain-level asserts (no copy literal): ver
# openspec/specs/message-orchestration "Acuse del funnel sin eco de datos".
# ---------------------------------------------------------------------------

def test_ack_uses_connector_and_next_question_no_echo():
    reply = build_current_turn_ack("soy de Torreón y tengo licencia tipo E")
    # conector breve del pool + pregunta; ningún dato del turno se repite en texto
    assert reply.split(".")[0].strip() + "." in CT._FUNNEL_CONNECTORS
    assert "Torreón" not in reply
    assert "tipo E" not in reply
    assert "?" in reply


def test_ack_single_question_no_data_echoed():
    reply = build_current_turn_ack("soy de Torreón, licencia tipo E vigente y mi apto está vigente")
    assert reply.count("?") == 1  # una sola pregunta visible
    assert "Torreón" not in reply
    assert "vigente" not in reply.lower()


def test_ack_experience_years_not_echoed():
    reply = build_current_turn_ack("tengo 20 años manejando full")
    # ni el valor de años ni "full" se repiten en el acuse (sin eco de datos)
    assert "20 años" not in reply
    assert "tracto full" not in reply
    assert "?" in reply


def test_ack_connector_varies_across_turns():
    # El pool de conectores tiene más de una opción — no es una frase enlatada fija.
    assert len(CT._FUNNEL_CONNECTORS) > 1


# ---------------------------------------------------------------------------
# Cierre de perfil: ligero, indica el siguiente paso una sola vez, sin prometer
# agenda ni repetir el recordatorio de proceso condicionado al interés.
# ---------------------------------------------------------------------------

def test_profile_complete_closing_in_hours_indicates_next_step(monkeypatch):
    monkeypatch.setattr(CT, "is_business_hours", lambda: True)
    reply = CT._profile_complete_closing()
    assert "documentos" in reply.lower()
    assert "ya quedó agendada" not in reply.lower()
    assert "siempre que sigas interesado" not in reply.lower()


def test_profile_complete_closing_out_of_hours_keeps_office_hours(monkeypatch):
    monkeypatch.setattr(CT, "is_business_hours", lambda: False)
    reply = CT._profile_complete_closing()
    assert "lunes a viernes de 08:00 a 17:30 hrs" in reply
    assert "siempre que sigas interesado" not in reply.lower()
