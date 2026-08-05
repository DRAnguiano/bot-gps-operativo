"""asked_field_keys_for_guard: espejo del funnel visible de current_turn."""
from __future__ import annotations

import pytest

from app.knowledge.current_turn import next_question_from_missing_facts
from app.knowledge.guard_asked_field import asked_field_keys_for_guard


_NAME = {"candidate.name": "Juan Pérez"}
_CITY = {"candidate.city": "Torreon"}
_AGE = {"candidate.age": "45"}
_VT = {"experience.vehicle_type": "full"}
_LIC = {"license.category": "E", "license.status": "vigente"}
_LIC_EXP = {"license.expiration_text": "vence en 1 año"}
_APTO = {"medical.apto_status": "vigente", "medical.apto_expiration_text": "vence en 1 año"}
_YEARS = {"experience.years": "5 años"}
_DOCS = {"documents.labor_letters": "si"}


def test_name_missing():
    assert asked_field_keys_for_guard({}) == ["candidate.name"]


def test_city_missing():
    assert asked_field_keys_for_guard({**_NAME}) == ["candidate.city"]


def test_age_missing():
    assert asked_field_keys_for_guard({**_NAME, **_CITY}) == ["candidate.age"]


def test_age_disqualified_returns_empty():
    # AGE_DISQUALIFICATION_LIMIT = 57; 57 >= 57 → descartado
    assert asked_field_keys_for_guard({**_NAME, **_CITY, "candidate.age": "57"}) == []


def test_vehicle_type_missing():
    assert asked_field_keys_for_guard({**_NAME, **_CITY, **_AGE}) == ["experience.vehicle_type"]


def test_license_mixed_returns_empty():
    assert asked_field_keys_for_guard({**_NAME, **_CITY, **_AGE, **_VT}) == []


def test_license_expiration_missing_returns_empty():
    assert asked_field_keys_for_guard({**_NAME, **_CITY, **_AGE, **_VT, **_LIC}) == []


def test_apto_expiration_missing_returns_empty():
    assert asked_field_keys_for_guard({**_NAME, **_CITY, **_AGE, **_VT, **_LIC, **_LIC_EXP}) == []


def test_years_missing():
    assert asked_field_keys_for_guard(
        {**_NAME, **_CITY, **_AGE, **_VT, **_LIC, **_LIC_EXP, **_APTO}
    ) == ["experience.years"]


def test_documents_missing():
    assert asked_field_keys_for_guard(
        {**_NAME, **_CITY, **_AGE, **_VT, **_LIC, **_LIC_EXP, **_APTO, **_YEARS}
    ) == ["documents.proof"]


def test_profile_complete_returns_empty():
    full = {**_NAME, **_CITY, **_AGE, **_VT, **_LIC, **_LIC_EXP, **_APTO, **_YEARS, **_DOCS}
    assert asked_field_keys_for_guard(full) == []


@pytest.mark.parametrize(
    "facts,expected_keys,question_marker",
    [
        ({}, ["candidate.name"], "nombre"),
        ({**_NAME}, ["candidate.city"], "ciudad"),
        ({**_NAME, **_CITY}, ["candidate.age"], "años"),
        ({**_NAME, **_CITY, **_AGE}, ["experience.vehicle_type"], "sencillo"),
        ({**_NAME, **_CITY, **_AGE, **_VT}, [], "licencia federal"),
        ({**_NAME, **_CITY, **_AGE, **_VT, **_LIC}, [], "vence"),
        ({**_NAME, **_CITY, **_AGE, **_VT, **_LIC, **_LIC_EXP}, [], "apto"),
        ({**_NAME, **_CITY, **_AGE, **_VT, **_LIC, **_LIC_EXP, **_APTO}, ["experience.years"], "años de experiencia"),
        ({**_NAME, **_CITY, **_AGE, **_VT, **_LIC, **_LIC_EXP, **_APTO, **_YEARS}, ["documents.proof"], "cartas"),
    ],
)
def test_helper_aligned_with_visible_question(facts, expected_keys, question_marker):
    assert asked_field_keys_for_guard(facts) == expected_keys
    assert question_marker in next_question_from_missing_facts(facts)


def test_helper_does_not_mutate_input():
    facts = {**_NAME, **_CITY, **_AGE}
    snapshot = dict(facts)
    asked_field_keys_for_guard(facts)
    assert facts == snapshot


def _build_guard_meta(facts):
    guard_keys = asked_field_keys_for_guard(facts)
    return (
        {
            "asked_field_keys": guard_keys,
            "asked_field_source": "current_turn_guard",
            "asked_field_key_space": "canonical",
        }
        if guard_keys
        else None
    )


def test_save_metadata_clean_field():
    meta = _build_guard_meta({**_NAME, **_CITY, **_AGE, **_VT, **_LIC, **_LIC_EXP, **_APTO})
    assert meta == {
        "asked_field_keys": ["experience.years"],
        "asked_field_source": "current_turn_guard",
        "asked_field_key_space": "canonical",
    }


def test_save_metadata_mixed_or_advisory_is_none():
    assert _build_guard_meta({**_NAME, **_CITY, **_AGE, **_VT}) is None
    assert _build_guard_meta({**_NAME, **_CITY, **_AGE, **_VT, **_LIC}) is None
