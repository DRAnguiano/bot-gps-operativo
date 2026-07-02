"""Detector único de pregunta de negocio (Fase 2 / D5 — raíz del bug #3).
Deterministas: sin BD/LLM. Verifican el superset de los 3 mecanismos y que
SIN turn_signals NO se dispara ningún LLM (gate barato).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.knowledge.current_turn import has_business_question


@dataclass
class _FakeSignals:
    has_embedded_question: bool = False


def test_signo_pregunta():
    assert has_business_question("¿cuánto pagan?") is True
    assert has_business_question("cuando inicio?") is True


def test_sustantivo_tema_sin_signo():
    # "pago", "licencia", "ruta" — términos de negocio sin "?"
    assert has_business_question("me interesa el pago semanal") is True
    assert has_business_question("tengo licencia federal") is True


def test_apertura_cantidad_embebida():
    # _EMBEDDED_Q_SIGNAL: "cuántas necesita" sin "?"
    assert has_business_question("y cuantas unidades manejan") is True


def test_sin_marcador_requiere_senal_llm():
    # Compuesto sin "?" ni término conocido: SOLO la señal LLM lo cataloga.
    msg = "ando viendo que onda con lo del arranque"
    assert has_business_question(msg) is False  # determinista, sin señal
    assert has_business_question(msg, _FakeSignals(has_embedded_question=True)) is True
    assert has_business_question(msg, _FakeSignals(has_embedded_question=False)) is False


def test_perfil_puro_no_es_pregunta():
    # Dato de perfil sin pregunta → False (no debe bloquear el guard)
    assert has_business_question("manejo full") is False
    assert has_business_question("soy de Monterrey") is False


def test_vacio():
    assert has_business_question("") is False
    assert has_business_question(None) is False


def test_determinista_sin_signals_no_invoca_llm(monkeypatch):
    # Si intentara clasificar por LLM, classify_turn_intent explotaría aquí.
    import app.knowledge.turn_intent_classifier as tic

    def _boom(*a, **k):
        raise AssertionError("has_business_question NO debe invocar el LLM sin turn_signals")

    monkeypatch.setattr(tic, "classify_turn_intent", _boom)
    assert has_business_question("manejo full") is False
