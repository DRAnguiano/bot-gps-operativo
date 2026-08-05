"""Nombres/apellidos hispanos en el camino de audio (bug en vivo conv 174).

Whisper sin idioma fijado anglicaniza apellidos ("Elizondo"→"Ellison") y las
transcripciones dividen apellidos que inician con El- ("el lizondo", "el lisa").
Tres capas de defensa:
1. call_groq_transcribe fija language="es" y pasa prompt de sesgo (jerga + apellidos).
2. El prompt de Gemini audio nativo instruye no anglicanizar ni dividir.
3. El extractor unificado repara el artefacto de división vía few-shot (red final).

Todo mockeado, sin llamadas reales.
"""
from __future__ import annotations

from unittest import mock

from app import gemini_client as gc
from app import indexer
from app.knowledge.turn_extractor import _TURN_EXTRACTOR_SYSTEM


class TestWhisperSpanishBias:
    def test_transcribe_pins_spanish_and_bias_prompt(self):
        captured = {}

        class _FakeTranscriptions:
            def create(self, **kwargs):
                captured.update(kwargs)
                return "eliezer elizondo"

        class _FakeAudio:
            transcriptions = _FakeTranscriptions()

        fake_client = mock.Mock()
        fake_client.audio = _FakeAudio()

        with mock.patch.dict("os.environ", {"GROQ_API_KEY": "fake"}), \
             mock.patch("app.indexer.Groq", return_value=fake_client):
            out = indexer.call_groq_transcribe(b"OggS...", "audio.ogg")

        assert out == "eliezer elizondo"
        # Sin language="es" Whisper auto-detecta y anglicaniza (Elizondo→Ellison).
        assert captured["language"] == "es"
        # El prompt de Whisper es sesgo de vocabulario: jerga + apellidos hispanos.
        assert "Elizondo" in captured["prompt"]
        assert "fulero" in captured["prompt"]


class TestGeminiAudioPromptGuardsNames:
    def test_prompt_instructs_hispanic_names(self):
        assert "Elizondo" in gc._AUDIO_TRANSCRIBE_PROMPT
        assert "anglicanices" in gc._AUDIO_TRANSCRIBE_PROMPT
        # El artefacto de división documentado con ejemplo explícito.
        assert "el lizondo" in gc._AUDIO_TRANSCRIBE_PROMPT


class TestExtractorRepairsSplitSurnames:
    def test_extractor_prompt_teaches_el_split_repair(self):
        # La regla vive en el prompt REAL del extractor unificado (lección del bug
        # is_joke_request: agregarla en el clasificador secundario no hace nada).
        assert "Eliezer Elizondo" in _TURN_EXTRACTOR_SYSTEM
        assert "el lizondo" in _TURN_EXTRACTOR_SYSTEM

    def test_repair_is_scoped_to_name_only(self):
        # La regla debe declarar su alcance: solo candidate.name, nunca inventar.
        assert "SOLO a candidate.name" in _TURN_EXTRACTOR_SYSTEM
        assert "NUNCA inventes un apellido" in _TURN_EXTRACTOR_SYSTEM
