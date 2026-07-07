"""Catálogo de vocabulario de dominio — DATOS, no regex.

Fuente única de los términos de unidad/experiencia del candidato y su resolución.
Las decisiones de negocio viven AQUÍ como datos (no if/else dispersos ni regex por término).

TEMPORAL en código (Fase 1A). Migra a Neo4j (nodos VehicleType/Term con aliases y
target_experience) en Fase 3 — la interfaz de `normalize_domain_values` no cambia.

Reglas de dominio (esquema_perfilamiento_v1 + decisiones Fase 0/1):
- `full` / `sencillo`            → tipo de unidad OBJETIVO, confirmable como vehicle_type.
- `quinta rueda`/`tráiler`/`traila`/`tractocamión` → experiencia compatible (tractocamión)
  pero NO determinan full vs sencillo → needs_clarification, NO se fija vehicle_type.
- `camión`                       → genérico AMBIGUO → needs_clarification.
- `torton`/`rabón`/`reparto`/`carga local`/`camioneta` → experiencia NO objetivo.
"""
from __future__ import annotations

from typing import NamedTuple

# Estados de resolución de un término de unidad.
CONFIRMED = "confirmed"
NEEDS_CLARIFICATION = "needs_clarification"
NON_TARGET = "non_target"


class VehicleResolution(NamedTuple):
    value: str | None          # vehicle_type canónico ('full'|'sencillo') o None si no se fija
    status: str                # CONFIRMED | NEEDS_CLARIFICATION | NON_TARGET
    target_experience: bool    # experiencia compatible con tractocamión/quinta rueda
    ambiguous: bool            # término genérico (p. ej. "camión")
    domain: str | None         # etiqueta de dominio para trazabilidad


# Catálogo. Claves NORMALIZADAS (minúsculas, sin acentos — como las deja text_normalizer).
# La resolución evalúa primero las claves más largas para que "camioneta" gane sobre
# "camion" y "quinta rueda" gane sobre cualquier palabra suelta. value=None => no se fija
# vehicle_type; el status indica qué debe hacer el planner.
VEHICLE_TERMS: dict[str, VehicleResolution] = {
    # Objetivo confirmado
    "full":         VehicleResolution("full", CONFIRMED, True, False, "full"),
    "fulero":       VehicleResolution("full", CONFIRMED, True, False, "full"),
    # Regla de negocio 2026-07-07 (conv 163): "doble articulado"/"doble" = full.
    "doble articulado": VehicleResolution("full", CONFIRMED, True, False, "doble_articulado"),
    "doble":        VehicleResolution("full", CONFIRMED, True, False, "doble_articulado"),
    "sencillo":     VehicleResolution("sencillo", CONFIRMED, True, False, "sencillo"),
    "sensillo":     VehicleResolution("sencillo", CONFIRMED, True, False, "sencillo"),
    "censillo":     VehicleResolution("sencillo", CONFIRMED, True, False, "sencillo"),
    # "caja seca" suele referir a sencillo (regla de negocio 2026-07-07); el resumen de
    # confirmación del funnel lo valida con el candidato (red de seguridad).
    "caja seca":    VehicleResolution("sencillo", CONFIRMED, True, False, "caja_seca"),
    # Compatible pero requiere aclaración full/sencillo (NO es vehicle_type final)
    "quinta rueda": VehicleResolution(None, NEEDS_CLARIFICATION, True, False, "quinta_rueda"),
    "5ta rueda":    VehicleResolution(None, NEEDS_CLARIFICATION, True, False, "quinta_rueda"),
    "tractocamion": VehicleResolution(None, NEEDS_CLARIFICATION, True, False, "tractocamion"),
    "trailer":      VehicleResolution(None, NEEDS_CLARIFICATION, True, False, "trailer"),
    "traila":       VehicleResolution(None, NEEDS_CLARIFICATION, True, False, "trailer"),
    # Genérico ambiguo
    "camion":       VehicleResolution(None, NEEDS_CLARIFICATION, False, True, "camion_generico"),
    # No objetivo para la vacante principal
    "camioneta":    VehicleResolution(None, NON_TARGET, False, False, "camioneta"),
    "torton":       VehicleResolution(None, NON_TARGET, False, False, "torton"),
    "rabon":        VehicleResolution(None, NON_TARGET, False, False, "rabon"),
    "reparto":      VehicleResolution(None, NON_TARGET, False, False, "reparto"),
    "carga local":  VehicleResolution(None, NON_TARGET, False, False, "local"),
}
