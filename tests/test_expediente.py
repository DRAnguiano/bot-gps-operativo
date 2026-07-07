"""Registro del expediente documental (document-expediente-vision-v2, Bloque 1).

Contrato: openspec/changes/document-expediente-vision-v2/specs/
candidate-expediente-registry. Deterministas: sin BD (mark_received mockea el upsert),
sin LLM.
"""
from __future__ import annotations

from unittest import mock

import app.lead_memory.expediente as EXP


# ── catálogo / validación determinista ────────────────────────────────────────

def test_canonical_doc_type_valid():
    assert EXP.canonical_doc_type("licencia_federal") == "licencia_federal"
    assert EXP.canonical_doc_type("INE") == "ine"
    assert EXP.canonical_doc_type("Apto Medico") == "apto_medico"  # normaliza espacios/case
    assert EXP.canonical_doc_type("apto_medico") == "apto_medico"


def test_canonical_doc_type_out_of_catalog_is_none():
    for raw in ("selfie", "meme", "", None, "documento_raro"):
        assert EXP.canonical_doc_type(raw) is None


def test_checklist_has_10_rows():
    assert len(EXP.NOTE_CHECKLIST) == 10


# ── declarar ≠ enviar ────────────────────────────────────────────────────────

def test_derive_declared_from_profile_facts():
    facts = {
        "license.category": "E",
        "medical.apto_expiration_text": "vence en 1 año",
        "documents.proof": "cartas",
    }
    declared = EXP.derive_declared(facts)
    assert {"licencia_federal", "apto_medico", "carta_laboral"} <= declared
    assert "ine" not in declared


def test_declared_does_not_mark_received():
    facts = {"license.category": "E"}
    rows = {r["key"]: r for r in EXP.expediente_snapshot(facts)}
    assert rows["licencia_federal"]["status"] == "declarado"  # NO recibido ✓


def test_received_beats_declared():
    facts = {
        "license.category": "E",
        "expediente.licencia_federal.status": "recibido",
    }
    rows = {r["key"]: r for r in EXP.expediente_snapshot(facts)}
    assert rows["licencia_federal"]["status"] == "recibido"


def test_ilegible_state_visible():
    facts = {"expediente.apto_medico.status": "ilegible"}
    rows = {r["key"]: r for r in EXP.expediente_snapshot(facts)}
    assert rows["apto_medico"]["status"] == "ilegible"


# ── comprobante laboral combinado (cartas O IMSS) ────────────────────────────

def test_comprobante_laboral_combines_best_state():
    facts = {"expediente.semanas_imss.status": "recibido"}
    rows = {r["key"]: r for r in EXP.expediente_snapshot(facts)}
    assert rows["comprobante_laboral"]["status"] == "recibido"


def test_comprobante_laboral_declared_via_proof():
    facts = {"documents.proof": "semanas_imss"}
    rows = {r["key"]: r for r in EXP.expediente_snapshot(facts)}
    assert rows["comprobante_laboral"]["status"] == "declarado"


# ── faltantes para el acuse ──────────────────────────────────────────────────

def test_missing_documents_excludes_received():
    facts = {
        "expediente.ine.status": "recibido",
        "license.category": "E",  # declarado, sigue faltando como envío
    }
    missing = EXP.missing_documents(facts)
    assert "INE" not in missing
    assert "Licencia federal" in missing  # declarado ≠ enviado


def test_received_documents_lists_types():
    facts = {
        "expediente.ine.status": "recibido",
        "expediente.licencia_federal.status": "analizado",
    }
    got = set(EXP.received_documents(facts))
    assert got == {"ine", "licencia_federal"}


# ── parser de clasificación de visión (determinista) ─────────────────────────

def test_parse_vision_classification_extracts_and_cleans():
    text = "tipo_documento: licencia_federal\nlegible: si\nnombre: Juan Pérez\nlicencia: E"
    clean, tipo, legible = EXP.parse_vision_classification(text)
    assert tipo == "licencia_federal"
    assert legible is True
    assert "tipo_documento" not in clean and "legible" not in clean
    assert "nombre: Juan Pérez" in clean  # el texto de perfilamiento se conserva


def test_parse_vision_classification_ilegible():
    clean, tipo, legible = EXP.parse_vision_classification(
        "tipo_documento: apto_medico\nlegible: no"
    )
    assert tipo == "apto_medico"
    assert legible is False
    assert clean == ""


def test_parse_vision_classification_desconocido_is_none():
    _, tipo, _ = EXP.parse_vision_classification("tipo_documento: desconocido\nlegible: si\nhola")
    assert tipo is None  # fuera de expediente → no registra


def test_parse_vision_classification_missing_lines_safe():
    clean, tipo, legible = EXP.parse_vision_classification("nombre: Ana López")
    assert tipo is None
    assert legible is True
    assert clean == "nombre: Ana López"


def test_parse_vision_classification_never_invents():
    # Un tipo fuera del catálogo emitido por el LLM NO pasa la validación determinista.
    _, tipo, _ = EXP.parse_vision_classification("tipo_documento: pasaporte\nlegible: si")
    assert tipo is None


# ── sección 📄 Documentos en la Nota IA ──────────────────────────────────────

def _nota(facts):
    from app.chatwoot_note_sync import render_candidate_note
    ctx = {"lead": {}, "facts": facts, "last_message": {"message": "hola"}, "conversation": {}}
    return render_candidate_note(ctx, ["bot_activo"])


def test_note_shows_documentos_section_with_states():
    facts = {
        "expediente.ine.status": "recibido",
        "expediente.licencia_federal.status": "analizado",
        "expediente.licencia_federal.dato": "tipo E, vence 03/2027",
        "license.category": "E",
    }
    note = _nota(facts)
    assert "📄 Documentos (expediente)" in note
    assert "INE: recibido ✓" in note
    assert "Licencia federal: analizado ✓ · tipo E, vence 03/2027" in note


def test_note_compacts_pendientes_one_line():
    note = _nota({})
    seccion = note.split("📄 Documentos (expediente)")[-1].split("👥")[0]
    assert seccion.count("Pendientes:") == 1
    # 10 renglones pendientes NO ocupan 10 líneas
    assert len([l for l in seccion.strip().splitlines() if l.strip()]) <= 2


def test_note_shows_discrepancia():
    facts = {
        "expediente.licencia_federal.status": "analizado",
        "expediente.licencia_federal.discrepancia": "declaró vigente, documento muestra vencida 03/2026",
    }
    note = _nota(facts)
    assert "⚠️ Licencia federal: declaró vigente" in note


def test_note_ilegible_asks_retoma():
    note = _nota({"expediente.apto_medico.status": "ilegible"})
    assert "ilegible, pedir re-toma" in note


# ── acuse determinista (fallback sin LLM) ─────────────────────────────────────

def test_build_acuse_fallback_names_received_and_missing():
    with mock.patch("app.indexer.call_groq_with_system", side_effect=RuntimeError("sin LLM")):
        facts = {"expediente.ine.status": "recibido"}
        acuse = EXP.build_acuse(facts, ["ine"], [])
    assert "INE" in acuse and "✓" in acuse
    assert "faltaría" in acuse or "falta" in acuse.lower()


def test_build_acuse_ilegible_pide_retoma():
    with mock.patch("app.indexer.call_groq_with_system", side_effect=RuntimeError("sin LLM")):
        acuse = EXP.build_acuse({"expediente.apto_medico.status": "ilegible"}, [], ["apto_medico"])
    assert "no se alcanza a leer" in acuse
    assert "foto" in acuse.lower()


# ── mark_received (upsert mockeado; sin imagen persistida) ───────────────────

def test_mark_received_upserts_status_and_timestamp():
    calls = []
    with mock.patch(
        "app.lead_memory.repository.upsert_lead_fact",
        side_effect=lambda **kw: calls.append(kw),
    ):
        ok = EXP.mark_received("test:x", "ine", legible=True)
    assert ok is True
    keys = {(c["fact_group"], c["fact_key"]) for c in calls}
    assert ("expediente", "ine.status") in keys
    assert ("expediente", "ine.received_at") in keys
    status = next(c for c in calls if c["fact_key"] == "ine.status")
    assert status["fact_value"] == "recibido"
    # Minimización: nunca se pasa una imagen/bytes al registro.
    assert not any("image" in str(c).lower() or "bytes" in str(c).lower() for c in calls)


def test_mark_received_ilegible():
    calls = []
    with mock.patch(
        "app.lead_memory.repository.upsert_lead_fact",
        side_effect=lambda **kw: calls.append(kw),
    ):
        EXP.mark_received("test:x", "apto_medico", legible=False)
    status = next(c for c in calls if c["fact_key"] == "apto_medico.status")
    assert status["fact_value"] == "ilegible"


def test_mark_received_invalid_type_noop():
    with mock.patch("app.lead_memory.repository.upsert_lead_fact") as up:
        assert EXP.mark_received("test:x", "selfie") is False
    up.assert_not_called()


def test_mark_received_db_error_safe():
    with mock.patch(
        "app.lead_memory.repository.upsert_lead_fact",
        side_effect=RuntimeError("db down"),
    ):
        assert EXP.mark_received("test:x", "ine") is False  # degradación segura
