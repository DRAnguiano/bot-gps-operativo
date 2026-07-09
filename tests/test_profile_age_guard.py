"""B3 — age extraction guard.

`candidate.age` solo se captura con señal explícita de edad. Frases de experiencia
("20 años de fullero", "10 años manejando full", "20 años de experiencia", etc.) NO
deben producir `candidate.age`.

extract_profile_facts_as_dict llama al LLM real (sin mock) — marcado external_llm
(gemini-full-provider-migration: Gemini free tier es 20 RPD, no soporta estos tests
en el gate rápido por defecto como sí lo hacía el free tier generoso de Groq).
"""
from __future__ import annotations

import pytest

from app.lead_memory.profile_extractor import extract_profile_facts_as_dict as f

pytestmark = pytest.mark.external_llm


# --- Frases de experiencia → NO edad ---

def test_fullero_experience_no_age():
    d = f("llevo 20 años de fullero")
    assert d.get("experience.years") == "20 años"
    assert d.get("experience.vehicle_type") == "full"
    assert "candidate.age" not in d


def test_manejando_full_no_age():
    d = f("tengo 10 años manejando full")
    assert d.get("experience.years") == "10 años"
    assert d.get("experience.vehicle_type") == "full"
    assert "candidate.age" not in d


def test_experiencia_no_age():
    d = f("tengo 20 años de experiencia")
    assert d.get("experience.years") == "20 años"
    assert "candidate.age" not in d


def test_fullero_desde_hace_no_age():
    d = f("soy fullero desde hace 20 años")
    assert d.get("experience.years") == "20 años"
    assert d.get("experience.vehicle_type") == "full"
    assert "candidate.age" not in d


def test_operador_experience_no_age():
    d = f("tengo 15 años de operador")
    assert d.get("experience.years") == "15 años"
    assert "candidate.age" not in d


# --- Señal explícita de edad → candidate.age ---

def test_tengo_45_anos_age():
    assert f("tengo 45 años").get("candidate.age") == "45"


def test_mi_edad_es_45():
    assert f("mi edad es 45").get("candidate.age") == "45"


def test_45_anos_de_edad():
    assert f("45 años de edad").get("candidate.age") == "45"


def test_tengo_45_anos_de_edad():
    assert f("tengo 45 años de edad").get("candidate.age") == "45"


def test_cuento_con_45_anos():
    assert f("cuento con 45 años").get("candidate.age") == "45"
