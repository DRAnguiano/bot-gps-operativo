"""Config pytest a nivel de suite (tests/ SÍ se monta en el contenedor api-test;
el pytest.ini del repo root NO se monta, así que la exclusión vive aquí para ser
portable local+contenedor).

Excluye `external_llm` del gate por defecto: esos tests llaman a un LLM real y no
deben correr (ni consumir cuota) salvo que se pidan explícitamente con
`pytest -m external_llm`.
"""
import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "external_llm: llama a un LLM real (Groq); excluido del gate por defecto",
    )
    config.addinivalue_line(
        "markers", "integration: prueba de integración (servicios reales)"
    )


def pytest_collection_modifyitems(config, items):
    # Si el usuario pidió explícitamente external_llm, no filtrar.
    markexpr = (config.getoption("-m", default="") or "")
    if "external_llm" in markexpr:
        return
    skip = pytest.mark.skip(
        reason="external_llm excluido del gate por defecto (usa: pytest -m external_llm)"
    )
    for item in items:
        if "external_llm" in item.keywords:
            item.add_marker(skip)
