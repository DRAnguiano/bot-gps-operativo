"""Captura pasiva de `asked_field_keys` (campo que el funnel preguntó).

Cubre tres piezas, todas aditivas y conservadoras (todo-o-nada canónico):
  1. `_canonical_asked_keys` — mapeo legacy→canónico, sin mezclar ni inventar.
  2. `_build_funnel_nudge` — devuelve (texto, keys canónicas); step mixto → [].
  3. `_store_lead_memory_updates` — escribe metadata sólo si hay keys.
  4. `read_last_asked_field_keys` — lectura read-only de la metadata.

No toca BD real: las funciones de persistencia/extracción se mockean.
"""
from __future__ import annotations

import contextlib

import pytest

import app.orchestrators.knowledge_orchestrator as KO
import app.lead_memory.last_asked_field as LAF


# ---------------------------------------------------------------------------
# 1) _canonical_asked_keys — mapeo estricto, todo-o-nada
# ---------------------------------------------------------------------------

def test_canonical_city_identity():
    assert KO._canonical_asked_keys({"candidate.city"}) == ["candidate.city"]


def test_canonical_license_category_to_type():
    assert KO._canonical_asked_keys({"license.category"}) == ["license.type"]


def test_canonical_age_identity():
    assert KO._canonical_asked_keys({"candidate.age"}) == ["candidate.age"]


def test_canonical_expiration_text_identity():
    assert KO._canonical_asked_keys({"license.expiration_text"}) == ["license.expiration_text"]


def test_canonical_documents_to_proof():
    assert KO._canonical_asked_keys({"documents.labor_letters_status"}) == ["documents.proof"]


def test_canonical_mixed_vigencia_step_returns_empty():
    # license.status no es mapeable → todo-o-nada descarta el step completo,
    # evitando asociar falsamente una respuesta corta sólo a medical.apto_status.
    assert KO._canonical_asked_keys({"license.status", "medical.apto_status"}) == []


def test_canonical_license_status_alone_returns_empty():
    assert KO._canonical_asked_keys({"license.status"}) == []


def test_canonical_empty_returns_empty():
    assert KO._canonical_asked_keys(set()) == []


# ---------------------------------------------------------------------------
# 2) _build_funnel_nudge — (texto, keys canónicas)
# ---------------------------------------------------------------------------

@pytest.fixture
def no_extraction(monkeypatch):
    """Neutraliza la extracción Neo4j/regex para controlar active_facts vía lead_memory."""
    monkeypatch.setattr(
        "app.knowledge.neo4j_client.extract_profile_facts_from_neo4j", lambda message: []
    )
    monkeypatch.setattr(
        "app.lead_memory.profile_extractor.extract_profile_facts",
        lambda message, intent=None, turn_signals=None: [],
    )
    # `_build_funnel_nudge` elige el texto con `random.choice(step["variants"])`. Fijarlo a
    # la primera variante hace deterministas estos tests: una variante de edad dice "edad"
    # (no "años") y rompía `"años" in text` al azar (~1/3). El campo/keys ya es determinista;
    # solo variaba el wording.
    monkeypatch.setattr(
        "app.orchestrators.knowledge_orchestrator.random.choice", lambda seq: seq[0]
    )


def _facts(*pairs):
    return {"facts": [
        {"fact_group": g, "fact_key": k, "fact_value": v} for g, k, v in pairs
    ]}


def test_nudge_first_step_returns_name_key(no_extraction):
    text, keys = KO._build_funnel_nudge("hola", {"intent": "info", "route": "rag"}, _facts())
    assert text is not None
    assert keys == ["candidate.name"]


def test_nudge_city_step_returns_city_key(no_extraction):
    mem = _facts(("candidate", "name", "Juan Pérez"))
    text, keys = KO._build_funnel_nudge("ok", {"intent": "info", "route": "rag"}, mem)
    assert text is not None
    assert keys == ["candidate.city"]


def test_nudge_age_step_returns_age_key(no_extraction):
    mem = _facts(
        ("candidate", "name", "Juan Pérez"),
        ("candidate", "city", "Torreon"),
    )
    text, keys = KO._build_funnel_nudge("ok", {"intent": "info", "route": "rag"}, mem)
    assert text is not None
    assert "años" in text
    assert keys == ["candidate.age"]


def test_nudge_license_step_records_type(no_extraction):
    # license.category y license.expiration_text son pasos SEPARADOS en _FUNNEL_STEPS
    # (no un step combinado); sin license.category aún, el nudge pregunta primero
    # el tipo de licencia (license.type), no la vigencia.
    mem = _facts(
        ("candidate", "name", "Juan Pérez"),
        ("candidate", "city", "Torreon"),
        ("candidate", "age", "45"),
        ("experience", "vehicle_type", "full"),
    )
    text, keys = KO._build_funnel_nudge("ok", {"intent": "info", "route": "rag"}, mem)
    assert text is not None
    assert "licencia" in text.lower()
    assert keys == ["license.type"]


def test_nudge_all_facts_no_nudge(no_extraction):
    mem = _facts(
        ("candidate", "name", "Juan Pérez"),
        ("candidate", "city", "Torreon"),
        ("candidate", "age", "45"),
        ("license", "category", "E"),
        ("license", "expiration_text", "vence en 1 año"),
        ("medical", "apto_status", "vigente"),
        ("medical", "apto_expiration_text", "vence en 1 año"),
        ("experience", "years", "5"),
        ("experience", "vehicle_type", "full"),
        # documents.proof (no labor_letters_status) es el fact canónico que satisface
        # el paso de documento laboral (Bloque 2, D3: cartas O semanas IMSS).
        ("documents", "proof", "cartas"),
    )
    text, keys = KO._build_funnel_nudge("ok", {"intent": "info", "route": "rag"}, mem)
    assert text is None
    assert keys == []


def test_nudge_skip_intent_no_keys(no_extraction):
    text, keys = KO._build_funnel_nudge("adios", {"intent": "farewell", "route": "rag"}, _facts())
    assert text is None
    assert keys == []


# ---------------------------------------------------------------------------
# 3) _store_lead_memory_updates — escribe metadata sólo si hay keys
# ---------------------------------------------------------------------------

@pytest.fixture
def store_spies(monkeypatch):
    """Mockea persistencia/extracción y captura las llamadas a save_lead_message."""
    saved: list[dict] = []
    upserts: list[dict] = []

    def fake_save(**kwargs):
        saved.append(kwargs)
        return {"id": 1}

    monkeypatch.setattr(KO, "save_lead_message", fake_save)
    monkeypatch.setattr(KO, "upsert_lead_fact", lambda **kw: upserts.append(kw))
    monkeypatch.setattr(KO, "log_lead_event", lambda **kw: None)
    monkeypatch.setattr(KO, "update_lead_summary", lambda **kw: None)
    monkeypatch.setattr(KO, "get_lead_memory", lambda **kw: {"facts": []})
    monkeypatch.setattr(
        "app.knowledge.neo4j_client.extract_profile_facts_from_neo4j", lambda message: []
    )
    monkeypatch.setattr(
        "app.lead_memory.profile_extractor.extract_profile_facts",
        lambda message, intent=None, turn_signals=None: [],
    )
    return saved, upserts


def _store(asked_field_keys, *, message="hola", saved=None):
    return KO._store_lead_memory_updates(
        lead_key="L1",
        conversation_key="C1",
        message=message,
        contract={"intent": "unknown", "route": "fallback"},
        stage_from=None,
        stage_to="new",
        reply="respuesta",
        asked_field_keys=asked_field_keys,
    )


def _assistant_meta(saved):
    assistant = [c for c in saved if c.get("role") == "assistant"]
    assert len(assistant) == 1
    return assistant[0].get("external_metadata")


def test_store_writes_canonical_metadata(store_spies):
    saved, _ = store_spies
    _store(["license.type"])
    assert _assistant_meta(saved) == {
        "asked_field_keys": ["license.type"],
        "asked_field_source": "funnel_nudge",
        "asked_field_key_space": "canonical",
    }


def test_store_no_keys_writes_no_metadata(store_spies):
    saved, _ = store_spies
    _store([])
    assert _assistant_meta(saved) is None


def test_store_none_keys_writes_no_metadata(store_spies):
    saved, _ = store_spies
    _store(None)
    assert _assistant_meta(saved) is None


def test_store_multiple_keys_preserved_as_list(store_spies):
    saved, _ = store_spies
    _store(["candidate.city", "experience.years"])
    assert _assistant_meta(saved)["asked_field_keys"] == ["candidate.city", "experience.years"]


def test_store_capture_does_not_change_extraction(store_spies):
    # La captura pasiva no altera la extracción de facts: con "quinta rueda"
    # se upserta role_fit.operator_type tenga o no asked_field_keys.
    saved, upserts = store_spies
    _store(["license.type"], message="manejo quinta rueda")
    keys_with = {(u["fact_group"], u["fact_key"]) for u in upserts}
    assert ("role_fit", "operator_type") in keys_with

    upserts.clear()
    _store(None, message="manejo quinta rueda")
    keys_without = {(u["fact_group"], u["fact_key"]) for u in upserts}
    assert keys_without == keys_with


# ---------------------------------------------------------------------------
# 4) read_last_asked_field_keys — lectura read-only
# ---------------------------------------------------------------------------

class _FakeCursor:
    def __init__(self, row):
        self._row = row

    def execute(self, *args, **kwargs):
        pass

    def fetchone(self):
        return self._row

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeConn:
    def __init__(self, row):
        self._row = row

    def cursor(self):
        return _FakeCursor(self._row)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _patch_conn(monkeypatch, row):
    @contextlib.contextmanager
    def _get_conn():
        yield _FakeConn(row)

    monkeypatch.setattr(LAF, "get_conn", _get_conn)


def test_helper_reads_last_keys(monkeypatch):
    _patch_conn(monkeypatch, {"external_metadata": {
        "asked_field_keys": ["license.type"],
        "asked_field_source": "funnel_nudge",
        "asked_field_key_space": "canonical",
    }})
    assert LAF.read_last_asked_field_keys("L1") == ["license.type"]


def test_helper_no_row_returns_none(monkeypatch):
    _patch_conn(monkeypatch, None)
    assert LAF.read_last_asked_field_keys("L1") is None


def test_helper_metadata_without_keys_returns_none(monkeypatch):
    _patch_conn(monkeypatch, {"external_metadata": {"other": "x"}})
    assert LAF.read_last_asked_field_keys("L1") is None


def test_helper_empty_lead_key_returns_none(monkeypatch):
    # No debe ni tocar la BD.
    def _boom():
        raise AssertionError("no debe abrir conexión con lead_key vacío")

    monkeypatch.setattr(LAF, "get_conn", _boom)
    assert LAF.read_last_asked_field_keys("") is None


def test_helper_db_error_returns_none(monkeypatch):
    @contextlib.contextmanager
    def _get_conn():
        raise RuntimeError("db down")
        yield  # pragma: no cover

    monkeypatch.setattr(LAF, "get_conn", _get_conn)
    assert LAF.read_last_asked_field_keys("L1") is None
