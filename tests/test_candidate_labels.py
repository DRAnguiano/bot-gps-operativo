"""B11 — labels oficiales / no labels fantasma.

`calculate_candidate_labels` solo emite labels del catálogo oficial.
Labels fantasma (`falta_cartas`, `apto_por_vencer*`, `licencia_por_vencer*`) eliminadas.
"""
from __future__ import annotations

import pytest

from app.chatwoot_note_sync import (
    OFFICIAL_LABELS,
    _filter_official_labels,
    calculate_candidate_labels,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _ctx(facts=None, requires_human=False, risk_level=None):
    return {
        "lead": {"requires_human": requires_human, "risk_level": risk_level or ""},
        "facts": facts or {},
    }


# Perfil COMPLETO según el funnel (gate de perfil_listo = funnel agotado): incluye
# nombre, edad y vencimientos VÁLIDOS de licencia y apto, además de unidad, años y
# documento. (Antes estos fixtures omitían name/age/vencimientos y dependían del
# gate laxo —el bug que corrige funnel-objection-handling-and-ready-gating.)
FULL_FACTS = {
    "candidate.name": "Juan Pérez",
    "candidate.age": "35",
    "license.category": "E",
    "license.expiration_text": "vence en 2 años",
    "medical.apto_status": "vigente",
    "medical.apto_expiration_text": "vence en 2 años",
    "experience.vehicle_type": "full",
    "experience.years": "10 años",
    "documents.labor_letters_status": "available",
    "candidate.city": "Torreón",
    "candidate.vacancy_accepted": "sí",
}

SENCILLO_FACTS = {
    "candidate.name": "Juan Pérez",
    "candidate.age": "35",
    "license.category": "E",
    "license.expiration_text": "vence en 2 años",
    "medical.apto_status": "vigente",
    "medical.apto_expiration_text": "vence en 2 años",
    "experience.vehicle_type": "sencillo",
    "experience.years": "8 años",
    "documents.labor_letters_status": "available",
    "candidate.city": "Torreón",
    "candidate.vacancy_accepted": "sí",
}


# ── catálogo oficial ──────────────────────────────────────────────────────────

def test_official_labels_count():
    assert len(OFFICIAL_LABELS) == 27


def test_official_labels_contains_expected():
    expected = {
        "aclaracion_pendiente", "bot_activo", "cecati_sugerido",
        "considerar_escuelita_transmontes", "considerar_operador_b1",
        "descartado_edad", "documentos", "falta_apto", "falta_ciudad",
        "falta_experiencia", "falta_licencia", "falta_unidad", "foraneo",
        "insistencia", "jerga_ambigua", "llamada_pendiente", "local_laguna",
        "objetivo_full", "objetivo_sencillo",
        "perfil_listo", "reingreso_verificar", "requiere_agente",
        "requiere_revision_ch", "riesgo_alto", "seguimiento",
        "urgente", "validar_traslado",
    }
    assert OFFICIAL_LABELS == expected


def test_official_labels_no_cecati():
    assert "cecati" not in OFFICIAL_LABELS


def test_official_labels_no_escuelita():
    assert "escuelita" not in OFFICIAL_LABELS


def test_official_labels_no_disponible_acudir():
    assert "disponible_acudir" not in OFFICIAL_LABELS


def test_official_labels_tiene_cecati_sugerido():
    assert "cecati_sugerido" in OFFICIAL_LABELS


def test_official_labels_tiene_considerar_escuelita():
    assert "considerar_escuelita_transmontes" in OFFICIAL_LABELS


def test_official_labels_tiene_llamada_pendiente():
    assert "llamada_pendiente" in OFFICIAL_LABELS


def test_official_labels_tiene_considerar_operador_b1():
    assert "considerar_operador_b1" in OFFICIAL_LABELS


# ── _filter_official_labels ───────────────────────────────────────────────────

def test_filter_removes_fantasy_label():
    result = _filter_official_labels(["bot_activo", "label_fantasma", "falta_cartas"])
    assert "bot_activo" in result
    assert "label_fantasma" not in result
    assert "falta_cartas" not in result


def test_filter_keeps_all_official():
    result = set(_filter_official_labels(list(OFFICIAL_LABELS)))
    assert result == OFFICIAL_LABELS


def test_filter_returns_sorted():
    result = _filter_official_labels(["seguimiento", "bot_activo"])
    assert result == sorted(result)


# ── allowlist: nunca sale nada fuera del catálogo ─────────────────────────────

@pytest.mark.parametrize("facts,requires_human,risk_level", [
    ({}, False, None),
    (FULL_FACTS, False, None),
    (FULL_FACTS, True, "high"),
    ({"license.category": "E", "medical.apto_expiration_text": "vence en 3 días"}, False, None),
    ({"license.category": "E", "license.expiration_text": "vence en 2 semanas"}, False, None),
    ({"medical.apto_expiration_text": "vence en 1 mes"}, False, None),
    ({"candidate.city": "Monterrey", "experience.years": "5 años"}, False, None),
])
def test_allowlist_subsets_official(facts, requires_human, risk_level):
    result = calculate_candidate_labels(_ctx(facts, requires_human, risk_level))
    assert set(result) <= OFFICIAL_LABELS, f"Labels fuera de catálogo: {set(result) - OFFICIAL_LABELS}"


# ── falta_cartas → documentos ─────────────────────────────────────────────────

def test_no_letters_with_license_emits_documentos():
    facts = {"license.category": "E"}
    result = calculate_candidate_labels(_ctx(facts))
    assert "documentos" in result
    assert "falta_cartas" not in result


def test_no_letters_with_experience_emits_documentos():
    facts = {"experience.years": "5 años"}
    result = calculate_candidate_labels(_ctx(facts))
    assert "documentos" in result
    assert "falta_cartas" not in result


def test_has_letters_no_documentos():
    facts = {"license.category": "E", "documents.labor_letters_status": "available"}
    result = calculate_candidate_labels(_ctx(facts))
    assert "documentos" not in result
    assert "falta_cartas" not in result


def test_no_license_no_experience_no_documentos():
    result = calculate_candidate_labels(_ctx({}))
    assert "documentos" not in result


# ── labels fantasma de vencimiento eliminadas ─────────────────────────────────

@pytest.mark.parametrize("exp_text", [
    "vence en 3 días",
    "vence en 2 semanas",
    "vence en 1 mes",
    "vence en 5 meses",
])
def test_no_apto_por_vencer_variants(exp_text):
    facts = {"medical.apto_expiration_text": exp_text}
    result = calculate_candidate_labels(_ctx(facts))
    assert "apto_por_vencer" not in result
    assert "apto_por_vencer_urgente" not in result


@pytest.mark.parametrize("exp_text", [
    "vence en 3 días",
    "vence en 2 semanas",
    "vence en 1 mes",
    "vence en 5 meses",
])
def test_no_licencia_por_vencer_variants(exp_text):
    facts = {"license.expiration_text": exp_text}
    result = calculate_candidate_labels(_ctx(facts))
    assert "licencia_por_vencer" not in result
    assert "licencia_por_vencer_urgente" not in result


# ── regresiones: labels oficiales conservadas ─────────────────────────────────

def test_regression_falta_licencia():
    result = calculate_candidate_labels(_ctx({}))
    assert "falta_licencia" in result


def test_regression_falta_apto_sin_medico():
    result = calculate_candidate_labels(_ctx({}))
    assert "falta_apto" in result


def test_regression_apto_vigente_clears_falta_apto():
    facts = {"medical.apto_status": "vigente"}
    result = calculate_candidate_labels(_ctx(facts))
    assert "falta_apto" not in result


def test_regression_foraneo_y_validar_traslado():
    facts = {"candidate.city": "Monterrey"}
    result = calculate_candidate_labels(_ctx(facts))
    assert "foraneo" in result
    assert "validar_traslado" in result


def test_regression_local_no_foraneo():
    facts = {"candidate.city": "Torreón"}
    result = calculate_candidate_labels(_ctx(facts))
    assert "foraneo" not in result
    assert "validar_traslado" not in result


# ── 10a.5 — local/foráneo como señal core (catálogo de ciudades) ──────────────
# El agente requiere local/foráneo junto a perfil_listo para continuar la
# contratación; `local_laguna` debe emitirse, no quedar diferido.

def test_ciudad_local_emite_local_laguna():
    result = calculate_candidate_labels(_ctx({"candidate.city": "Torreón"}))
    assert "local_laguna" in result


def test_ciudad_foranea_no_emite_local_laguna():
    result = calculate_candidate_labels(_ctx({"candidate.city": "Monterrey"}))
    assert "local_laguna" not in result


def test_local_y_foraneo_son_mutuamente_excluyentes():
    for city in ("Torreón", "Gómez Palacio", "Lerdo", "Monterrey", "CDMX", "Saltillo"):
        result = calculate_candidate_labels(_ctx({"candidate.city": city}))
        assert not ({"local_laguna", "foraneo"} <= set(result)), city


def test_local_laguna_con_sufijo_de_estado():
    # Alias del catálogo ZML con sufijo de estado siguen siendo locales (resueltos vía
    # normalize_zm_laguna_city antes del check canónico; bug de producción corregido en
    # auditoría 2026-07-06: antes se comparaba el texto crudo, sin resolver alias).
    for city in ("torreon coahuila", "Torreón Coahuila", "cd lerdo", "Cd Lerdo"):
        result = calculate_candidate_labels(_ctx({"candidate.city": city}))
        assert "local_laguna" in result, city
        assert "foraneo" not in result, city


def test_sin_ciudad_no_emite_ubicacion():
    result = calculate_candidate_labels(_ctx({}))
    assert "local_laguna" not in result
    assert "foraneo" not in result


def test_regression_perfil_listo():
    result = calculate_candidate_labels(_ctx(FULL_FACTS))
    assert "perfil_listo" in result
    assert "falta_licencia" not in result
    assert "falta_apto" not in result
    assert "documentos" not in result


def test_regression_bot_activo_siempre_presente():
    result = calculate_candidate_labels(_ctx({}))
    assert "bot_activo" in result


def test_regression_requiere_agente_y_revision():
    result = calculate_candidate_labels(_ctx({}, requires_human=True))
    assert "requiere_agente" in result
    assert "requiere_revision_ch" in result


def test_regression_riesgo_alto():
    result = calculate_candidate_labels(_ctx({}, risk_level="high"))
    assert "riesgo_alto" in result


def test_regression_seguimiento_por_submission():
    facts = {"documents.submission_status": "pending_candidate_will_send"}
    result = calculate_candidate_labels(_ctx(facts))
    assert "seguimiento" in result


# ── sencillo como unidad objetivo válida (igual que full) ────────────────────

def test_sencillo_perfil_listo_igual_que_full():
    result = calculate_candidate_labels(_ctx(SENCILLO_FACTS))
    assert "perfil_listo" in result
    assert "falta_licencia" not in result
    assert "falta_apto" not in result
    assert "documentos" not in result


def test_sencillo_has_experience_sin_fifth_wheel():
    """vehicle_type=sencillo cuenta como has_experience sin necesitar fifth_wheel."""
    facts = {"experience.vehicle_type": "sencillo"}
    result = calculate_candidate_labels(_ctx(facts))
    assert "bot_activo" in result  # flujo normal activo
    # has_experience = True → no genera documentos sin licencia/experiencia vacía


def test_sencillo_allowlist_subsets_official():
    result = calculate_candidate_labels(_ctx(SENCILLO_FACTS))
    assert set(result) <= OFFICIAL_LABELS


def test_sencillo_no_requiere_fifth_wheel():
    """SENCILLO_FACTS no tiene fifth_wheel y perfil_listo debe funcionar igual."""
    assert "experience.fifth_wheel" not in SENCILLO_FACTS
    result = calculate_candidate_labels(_ctx(SENCILLO_FACTS))
    assert "perfil_listo" in result


# ── labels deprecadas nunca en output ────────────────────────────────────────

@pytest.mark.parametrize("facts,requires_human,risk_level", [
    ({}, False, None),
    (FULL_FACTS, False, None),
    (SENCILLO_FACTS, False, None),
    (FULL_FACTS, True, "high"),
])
def test_deprecated_labels_never_emitted(facts, requires_human, risk_level):
    """cecati, escuelita y disponible_acudir nunca deben aparecer en el output."""
    result = calculate_candidate_labels(_ctx(facts, requires_human, risk_level))
    assert "cecati" not in result
    assert "escuelita" not in result
    assert "disponible_acudir" not in result


# ── nota IA: display de labels nuevas ────────────────────────────────────────

from app.chatwoot_note_sync import render_candidate_note, _LABEL_DISPLAY  # noqa: E402


def _nota_con_labels(labels: list[str]) -> str:
    ctx = {"lead": {}, "facts": {}, "last_message": {}, "conversation": {}}
    return render_candidate_note(ctx, labels)


def test_nota_sin_labels_en_cuerpo_con_cecati_sugerido():
    # Contrato chatwoot-ai-note: las labels NO se renderizan en el cuerpo de la nota
    # (antes este test exigía el display "CECATI sugerido"; el contrato lo supersedió).
    note = _nota_con_labels(["bot_activo", "cecati_sugerido"])
    assert "🏷️ Labels" not in note
    assert "cecati_sugerido" not in note


def test_nota_sin_labels_en_cuerpo_con_considerar_escuelita():
    note = _nota_con_labels(["bot_activo", "considerar_escuelita_transmontes"])
    assert "🏷️ Labels" not in note
    assert "considerar_escuelita_transmontes" not in note


def test_nota_no_muestra_cecati_raw():
    """La nota nunca debe mostrar el string raw 'cecati' (label deprecada)."""
    note = _nota_con_labels(["bot_activo"])
    assert "cecati\n" not in note.lower()
    assert note.count("cecati") == 0 or "CECATI sugerido" in note


def test_nota_no_muestra_escuelita_raw():
    """La nota nunca debe mostrar el string raw 'escuelita' (label deprecada)."""
    note = _nota_con_labels(["bot_activo"])
    # escuelita no debe aparecer como label en la sección Labels
    lines = note.split("\n")
    label_section = next((l for l in lines if "bot_activo" in l.lower() or "Bot activo" in l), "")
    assert "escuelita" not in label_section


def test_label_display_no_contiene_deprecated():
    """_LABEL_DISPLAY no debe tener keys para labels deprecadas."""
    assert "cecati" not in _LABEL_DISPLAY
    assert "escuelita" not in _LABEL_DISPLAY
    assert "disponible_acudir" not in _LABEL_DISPLAY


def test_nota_sin_labels_en_cuerpo_con_considerar_operador_b1():
    note = _nota_con_labels(["bot_activo", "considerar_operador_b1"])
    assert "🏷️ Labels" not in note
    assert "considerar_operador_b1" not in note


# ══════════════════════════════════════════════════════════════════════════════
# candidate-label-safety — tests ROJOS hasta implementar L2
# (openspec/changes/candidate-label-safety). No modificar las aserciones al
# implementar: el código debe ponerse verde, no los tests.
# ══════════════════════════════════════════════════════════════════════════════


def _fallback_labels(result: dict) -> list[str]:
    # Import perezoso: app.app solo se carga en el entorno de test completo.
    from app.app import _fallback_chatwoot_labels
    return _fallback_chatwoot_labels(result)


# ── 1. Fallback solo emite labels oficiales ───────────────────────────────────

class TestFallbackLabelsOficiales:
    def test_fallback_no_emite_requiere_humano(self):
        labels = _fallback_labels({"requires_human": True})
        assert "requiere_humano" not in labels

    def test_fallback_emite_requiere_agente_cuando_requiere_humano(self):
        labels = _fallback_labels({"requires_human": True})
        assert "requiere_agente" in labels

    def test_fallback_riesgo_alto_no_emite_requiere_humano(self):
        labels = _fallback_labels({"risk_level": "high"})
        assert "riesgo_alto" in labels
        assert "requiere_humano" not in labels

    @pytest.mark.parametrize("result", [
        {},
        {"requires_human": True},
        {"risk_level": "high"},
        {"current_stage": "PROFILE_READY"},
        {"requires_human": True, "risk_level": "high", "current_stage": "PROFILE_READY"},
    ])
    def test_fallback_solo_labels_oficiales(self, result):
        labels = _fallback_labels(result)
        assert set(labels) <= OFFICIAL_LABELS, (
            f"Fallback emitió labels fuera de catálogo: {set(labels) - OFFICIAL_LABELS}"
        )


# ── 2. perfil_listo requiere unidad confirmada ────────────────────────────────

class TestPerfilListoRequiereUnidad:
    def test_years_sin_vehicle_type_no_perfil_listo(self):
        facts = {**FULL_FACTS, "experience.years": "5 años"}
        facts.pop("experience.vehicle_type")
        result = calculate_candidate_labels(_ctx(facts))
        assert "perfil_listo" not in result
        assert "falta_unidad" in result

    @pytest.mark.parametrize("ambiguous", ["quinta rueda", "tráiler", "trailero", "tractocamión"])
    def test_vehicle_type_ambiguo_no_perfil_listo(self, ambiguous):
        facts = {**FULL_FACTS, "experience.years": "5 años",
                 "experience.vehicle_type": ambiguous}
        result = calculate_candidate_labels(_ctx(facts))
        assert "perfil_listo" not in result
        assert "falta_unidad" in result

    def test_full_completo_perfil_listo(self):
        facts = {**FULL_FACTS, "experience.years": "5 años"}
        result = calculate_candidate_labels(_ctx(facts))
        assert "perfil_listo" in result
        assert "falta_unidad" not in result

    def test_sencillo_completo_perfil_listo(self):
        facts = {**SENCILLO_FACTS, "experience.years": "5 años"}
        result = calculate_candidate_labels(_ctx(facts))
        assert "perfil_listo" in result
        assert "falta_unidad" not in result

    def test_falta_unidad_y_perfil_listo_nunca_coexisten(self):
        # Invariante del contrato sobre ambos perfiles completos y el incompleto.
        for facts in (FULL_FACTS, SENCILLO_FACTS,
                      {k: v for k, v in FULL_FACTS.items() if k != "experience.vehicle_type"}):
            result = calculate_candidate_labels(_ctx(dict(facts)))
            assert not ({"falta_unidad", "perfil_listo"} <= set(result)), (
                f"falta_unidad y perfil_listo coexisten para facts={facts}"
            )


# ── 3. Labels terminales remueven bot_activo ─────────────────────────────────
# Conjunto terminal según openspec/specs/chatwoot-label-taxonomy/spec.md:94-101:
# perfil_listo, requiere_agente, requiere_revision_ch, riesgo_alto,
# reingreso_verificar. (reingreso_verificar y considerar_operador_b1 aún no
# tienen path de emisión en calculate_candidate_labels — deuda N7, fuera de
# este change; su escenario vive en el spec delta.)

class TestBotActivoTerminales:
    def test_perfil_listo_remueve_bot_activo(self):
        result = calculate_candidate_labels(_ctx(FULL_FACTS))
        assert "perfil_listo" in result
        assert "bot_activo" not in result

    def test_requiere_agente_remueve_bot_activo(self):
        result = calculate_candidate_labels(_ctx({}, requires_human=True))
        assert "requiere_agente" in result
        assert "bot_activo" not in result

    def test_requiere_revision_ch_remueve_bot_activo(self):
        result = calculate_candidate_labels(_ctx({}, requires_human=True))
        assert "requiere_revision_ch" in result
        assert "bot_activo" not in result

    def test_riesgo_alto_remueve_bot_activo(self):
        result = calculate_candidate_labels(_ctx({}, risk_level="high"))
        assert "riesgo_alto" in result
        assert "bot_activo" not in result

    def test_fallback_perfil_listo_remueve_bot_activo(self):
        labels = _fallback_labels({"current_stage": "PROFILE_READY"})
        assert "perfil_listo" in labels
        assert "bot_activo" not in labels

    def test_bot_activo_permanece_sin_terminales(self):
        result = calculate_candidate_labels(_ctx({}))
        assert "bot_activo" in result


# ══════════════════════════════════════════════════════════════════════════════
# B11.1/B11.2 — mapeo de aliases fantasma → oficial en el chokepoint único.
# La vista SQL `v_rh_work_queue.suggested_chatwoot_labels` emite nombres que NO
# están en el catálogo (requiere_humano, ubicacion_extranjero, validar_ch,
# posible_abandono); deben mapearse al label oficial equivalente, no llegar crudos
# a Chatwoot. `falta_cartas` → `documentos` (spec chatwoot-label-taxonomy).
# ══════════════════════════════════════════════════════════════════════════════

ALIAS_CASES = [
    ("requiere_humano", "requiere_agente"),     # spec.md:51-52
    ("falta_cartas", "documentos"),             # spec live-reply :35
    ("ubicacion_extranjero", "foraneo"),
    ("validar_ch", "requiere_revision_ch"),
    ("posible_abandono", "seguimiento"),
]


@pytest.mark.parametrize("ghost,official", ALIAS_CASES)
def test_filter_maps_ghost_alias_to_official(ghost, official):
    result = _filter_official_labels(["bot_activo", ghost])
    assert ghost not in result
    assert official in result


def _normalize_sql_labels(labels):
    # path primario: vista SQL → _normalize_chatwoot_labels → Chatwoot (import perezoso).
    from app.app import _normalize_chatwoot_labels
    return _normalize_chatwoot_labels(labels)


@pytest.mark.parametrize("ghost,official", ALIAS_CASES)
def test_sql_primary_path_maps_ghost_alias(ghost, official):
    result = _normalize_sql_labels(["bot_activo", ghost])
    assert ghost not in result
    assert official in result


def test_sql_primary_path_drops_unknown_label():
    result = _normalize_sql_labels(["bot_activo", "label_totalmente_inventada"])
    assert "label_totalmente_inventada" not in result
    assert set(result) <= OFFICIAL_LABELS


def test_sql_primary_path_parses_pg_array_with_ghost():
    # PostgreSQL devuelve "{a,b}"; un fantasma adentro debe normalizarse igual.
    result = _normalize_sql_labels("{bot_activo,requiere_humano}")
    assert "requiere_humano" not in result
    assert "requiere_agente" in result
    assert set(result) <= OFFICIAL_LABELS


# ═══════════════════════════════════════════════════════════════════════════════
# live-label-completion — labels derivadas de facts deterministas
# ═══════════════════════════════════════════════════════════════════════════════

TRICHOTOMY = {
    "objetivo_full",
    "objetivo_sencillo",
    "considerar_escuelita_transmontes",
    "cecati_sugerido",
}


def test_objetivo_sencillo_desde_vehicle_type_confirmado():
    result = calculate_candidate_labels(_ctx({"experience.vehicle_type": "sencillo"}))
    assert "objetivo_sencillo" in result
    assert not (TRICHOTOMY - {"objetivo_sencillo"} & set(result))


def test_objetivo_full_desde_vehicle_type_confirmado():
    result = calculate_candidate_labels(_ctx({"experience.vehicle_type": "full"}))
    assert "objetivo_full" in result
    assert not (TRICHOTOMY - {"objetivo_full"} & set(result))


def test_non_target_vehicle_emite_escuelita_y_canaliza():
    result = calculate_candidate_labels(_ctx({"experience.non_target_vehicle_type": "torton"}))
    assert "considerar_escuelita_transmontes" in result
    assert "requiere_agente" in result
    assert "bot_activo" not in result
    assert not (TRICHOTOMY - {"considerar_escuelita_transmontes"} & set(result))


def test_road_experience_none_emite_cecati_y_canaliza():
    result = calculate_candidate_labels(_ctx({"experience.road_experience": "none"}))
    assert "cecati_sugerido" in result
    assert "requiere_agente" in result
    assert "bot_activo" not in result
    assert not (TRICHOTOMY - {"cecati_sugerido"} & set(result))


def test_vehicle_type_confirmado_gana_sobre_senales_previas():
    result = calculate_candidate_labels(_ctx({
        "experience.vehicle_type": "full",
        "experience.non_target_vehicle_type": "torton",
        "experience.road_experience": "none",
        "experience.vehicle_type_pending": "trailer",
    }))
    assert "objetivo_full" in result
    assert "objetivo_sencillo" not in result
    assert "considerar_escuelita_transmontes" not in result
    assert "cecati_sugerido" not in result
    assert "aclaracion_pendiente" not in result


def test_vehicle_type_pending_emite_aclaracion_sin_objetivo():
    result = calculate_candidate_labels(_ctx({"experience.vehicle_type_pending": "trailer"}))
    assert "aclaracion_pendiente" in result
    assert "objetivo_full_sencillo" not in result


def test_b1_intent_emite_label_y_requiere_agente():
    result = calculate_candidate_labels(_ctx({"experience.b1_us_intent": "sí"}))
    assert "considerar_operador_b1" in result
    assert "requiere_agente" in result
    assert "bot_activo" not in result


def test_reingreso_emite_terminal_y_requiere_agente():
    result = calculate_candidate_labels(_ctx({"candidate.reingreso": "sí"}))
    assert "reingreso_verificar" in result
    assert "requiere_agente" in result
    assert "bot_activo" not in result


def test_faltantes_ciudad_y_experiencia_base():
    result = calculate_candidate_labels(_ctx({}))
    assert "falta_ciudad" in result
    assert "falta_experiencia" in result


def test_non_target_no_permite_perfil_listo():
    facts = {**FULL_FACTS, "experience.non_target_vehicle_type": "torton"}
    facts.pop("experience.vehicle_type")
    result = calculate_candidate_labels(_ctx(facts))
    assert "perfil_listo" not in result
    assert "considerar_escuelita_transmontes" in result


def test_perfil_listo_no_depende_de_disponible_acudir():
    """disponible_acudir no debe completar perfil_listo."""
    facts_sin_disponible = {
        "candidate.name": "Juan Pérez",
        "candidate.age": "35",
        "license.category": "E",
        "license.expiration_text": "vence en 2 años",
        "medical.apto_status": "vigente",
        "medical.apto_expiration_text": "vence en 2 años",
        "experience.vehicle_type": "full",
        "experience.years": "10 años",
        "documents.labor_letters_status": "available",
        "candidate.city": "Torreón",
        "candidate.vacancy_accepted": "sí",
    }
    facts_con_disponible = {**facts_sin_disponible, "candidate.availability_to_attend": "sí"}
    result_sin = calculate_candidate_labels(_ctx(facts_sin_disponible))
    result_con = calculate_candidate_labels(_ctx(facts_con_disponible))
    # disponible_acudir no altera perfil_listo
    assert "perfil_listo" in result_sin
    assert "perfil_listo" in result_con
    assert "disponible_acudir" not in result_sin
    assert "disponible_acudir" not in result_con
