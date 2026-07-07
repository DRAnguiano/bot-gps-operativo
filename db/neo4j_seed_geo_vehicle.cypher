// =============================================================================
// Neo4j seed: GeoArea and VehicleType nodes for profile fact extraction
//
// Apply via Neo4j Browser or cypher-shell:
//   cypher-shell -u neo4j -p $NEO4J_PASSWORD < db/neo4j_seed_geo_vehicle.cypher
//
// Re-running is safe — MERGE + SET is idempotent.
// =============================================================================

CREATE CONSTRAINT geo_area_id IF NOT EXISTS FOR (n:GeoArea) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT vehicle_type_id IF NOT EXISTS FOR (n:VehicleType) REQUIRE n.id IS UNIQUE;

// ─── GeoArea — cities ─────────────────────────────────────────────────────────
// Note on single-word aliases: "leon" is intentionally excluded from geo_leon
// because it appears as a token inside "nuevo leon" (state), causing false
// positives. Use explicit "leon gto" or "leon guanajuato" instead.

MERGE (n:GeoArea {id: 'geo_torreon'})
SET n.canonical = 'Torreón',
    n.type = 'city',
    n.state = 'Coahuila',
    n.aliases = ['torreon', 'torreón', 'torreon coahuila', 'la laguna'],
    n.profile_fact_group = 'candidate',
    n.profile_fact_key = 'city',
    n.profile_fact_value = 'Torreón',
    n.confidence = 0.92;

MERGE (n:GeoArea {id: 'geo_gomez_palacio'})
SET n.canonical = 'Gómez Palacio',
    n.type = 'city',
    n.state = 'Durango',
    n.aliases = ['gomez palacio', 'gómez palacio'],
    n.profile_fact_group = 'candidate',
    n.profile_fact_key = 'city',
    n.profile_fact_value = 'Gómez Palacio',
    n.confidence = 0.92;

MERGE (n:GeoArea {id: 'geo_lerdo'})
SET n.canonical = 'Lerdo',
    n.type = 'city',
    n.state = 'Durango',
    n.aliases = ['lerdo', 'ciudad lerdo'],
    n.profile_fact_group = 'candidate',
    n.profile_fact_key = 'city',
    n.profile_fact_value = 'Lerdo',
    n.confidence = 0.92;

MERGE (n:GeoArea {id: 'geo_monterrey'})
SET n.canonical = 'Monterrey',
    n.type = 'city',
    n.state = 'Nuevo León',
    n.aliases = ['monterrey', 'monterey', 'mty', 'meritito monterrey', 'el monterrey'],
    n.profile_fact_group = 'candidate',
    n.profile_fact_key = 'city',
    n.profile_fact_value = 'Monterrey',
    n.confidence = 0.92;

MERGE (n:GeoArea {id: 'geo_saltillo'})
SET n.canonical = 'Saltillo',
    n.type = 'city',
    n.state = 'Coahuila',
    n.aliases = ['saltillo'],
    n.profile_fact_group = 'candidate',
    n.profile_fact_key = 'city',
    n.profile_fact_value = 'Saltillo',
    n.confidence = 0.92;

MERGE (n:GeoArea {id: 'geo_nuevo_laredo'})
SET n.canonical = 'Nuevo Laredo',
    n.type = 'city',
    n.state = 'Tamaulipas',
    n.aliases = ['nuevo laredo', 'nvo laredo', 'n. laredo'],
    n.profile_fact_group = 'candidate',
    n.profile_fact_key = 'city',
    n.profile_fact_value = 'Nuevo Laredo',
    n.confidence = 0.92;

MERGE (n:GeoArea {id: 'geo_ciudad_juarez'})
SET n.canonical = 'Ciudad Juárez',
    n.type = 'city',
    n.state = 'Chihuahua',
    n.aliases = ['ciudad juarez', 'ciudad juárez', 'cd juarez', 'cd. juarez', 'juarez', 'juárez'],
    n.profile_fact_group = 'candidate',
    n.profile_fact_key = 'city',
    n.profile_fact_value = 'Ciudad Juárez',
    n.confidence = 0.92;

MERGE (n:GeoArea {id: 'geo_chihuahua'})
SET n.canonical = 'Chihuahua',
    n.type = 'city',
    n.state = 'Chihuahua',
    n.aliases = ['chihuahua', 'chih'],
    n.profile_fact_group = 'candidate',
    n.profile_fact_key = 'city',
    n.profile_fact_value = 'Chihuahua',
    n.confidence = 0.92;

MERGE (n:GeoArea {id: 'geo_durango'})
SET n.canonical = 'Durango',
    n.type = 'city',
    n.state = 'Durango',
    n.aliases = ['durango', 'dgo', 'victoria de durango'],
    n.profile_fact_group = 'candidate',
    n.profile_fact_key = 'city',
    n.profile_fact_value = 'Durango',
    n.confidence = 0.90;

MERGE (n:GeoArea {id: 'geo_san_luis_potosi'})
SET n.canonical = 'San Luis Potosí',
    n.type = 'city',
    n.state = 'San Luis Potosí',
    n.aliases = ['san luis potosi', 'san luis potosí', 'slp', 'san luisito', 'san luis'],
    n.profile_fact_group = 'candidate',
    n.profile_fact_key = 'city',
    n.profile_fact_value = 'San Luis Potosí',
    n.confidence = 0.90;

MERGE (n:GeoArea {id: 'geo_matehuala'})
SET n.canonical = 'Matehuala',
    n.type = 'city',
    n.state = 'San Luis Potosí',
    n.aliases = ['matehuala'],
    n.profile_fact_group = 'candidate',
    n.profile_fact_key = 'city',
    n.profile_fact_value = 'Matehuala',
    n.confidence = 0.92;

MERGE (n:GeoArea {id: 'geo_culiacan'})
SET n.canonical = 'Culiacán',
    n.type = 'city',
    n.state = 'Sinaloa',
    n.aliases = ['culiacan', 'culiacán'],
    n.profile_fact_group = 'candidate',
    n.profile_fact_key = 'city',
    n.profile_fact_value = 'Culiacán',
    n.confidence = 0.92;

MERGE (n:GeoArea {id: 'geo_manzanillo'})
SET n.canonical = 'Manzanillo',
    n.type = 'city',
    n.state = 'Colima',
    n.aliases = ['manzanillo'],
    n.profile_fact_group = 'candidate',
    n.profile_fact_key = 'city',
    n.profile_fact_value = 'Manzanillo',
    n.confidence = 0.92;

MERGE (n:GeoArea {id: 'geo_queretaro'})
SET n.canonical = 'Querétaro',
    n.type = 'city',
    n.state = 'Querétaro',
    n.aliases = ['queretaro', 'querétaro', 'qro'],
    n.profile_fact_group = 'candidate',
    n.profile_fact_key = 'city',
    n.profile_fact_value = 'Querétaro',
    n.confidence = 0.92;

MERGE (n:GeoArea {id: 'geo_leon'})
SET n.canonical = 'León',
    n.type = 'city',
    n.state = 'Guanajuato',
    n.aliases = ['leon gto', 'leon guanajuato', 'la perla del bajio'],
    n.profile_fact_group = 'candidate',
    n.profile_fact_key = 'city',
    n.profile_fact_value = 'León',
    n.confidence = 0.88;

MERGE (n:GeoArea {id: 'geo_rio_bravo'})
SET n.canonical = 'Río Bravo',
    n.type = 'city',
    n.state = 'Tamaulipas',
    n.aliases = ['rio bravo', 'río bravo'],
    n.profile_fact_group = 'candidate',
    n.profile_fact_key = 'city',
    n.profile_fact_value = 'Río Bravo',
    n.confidence = 0.92;

MERGE (n:GeoArea {id: 'geo_matamoros'})
SET n.canonical = 'Matamoros',
    n.type = 'city',
    n.state = 'Tamaulipas',
    n.aliases = ['matamoros'],
    n.profile_fact_group = 'candidate',
    n.profile_fact_key = 'city',
    n.profile_fact_value = 'Matamoros',
    n.confidence = 0.90;

MERGE (n:GeoArea {id: 'geo_reynosa'})
SET n.canonical = 'Reynosa',
    n.type = 'city',
    n.state = 'Tamaulipas',
    n.aliases = ['reynosa'],
    n.profile_fact_group = 'candidate',
    n.profile_fact_key = 'city',
    n.profile_fact_value = 'Reynosa',
    n.confidence = 0.92;

MERGE (n:GeoArea {id: 'geo_guadalajara'})
SET n.canonical = 'Guadalajara',
    n.type = 'city',
    n.state = 'Jalisco',
    n.aliases = ['guadalajara', 'gdl', 'tapatia', 'tapatío'],
    n.profile_fact_group = 'candidate',
    n.profile_fact_key = 'city',
    n.profile_fact_value = 'Guadalajara',
    n.confidence = 0.90;

MERGE (n:GeoArea {id: 'geo_cdmx'})
SET n.canonical = 'Ciudad de México',
    n.type = 'city',
    n.state = 'CDMX',
    n.aliases = ['cdmx', 'ciudad de mexico', 'ciudad de méxico', 'df', 'distrito federal'],
    n.profile_fact_group = 'candidate',
    n.profile_fact_key = 'city',
    n.profile_fact_value = 'Ciudad de México',
    n.confidence = 0.90;

MERGE (n:GeoArea {id: 'geo_zacatecas'})
SET n.canonical = 'Zacatecas',
    n.type = 'city',
    n.state = 'Zacatecas',
    n.aliases = ['zacatecas', 'zac'],
    n.profile_fact_group = 'candidate',
    n.profile_fact_key = 'city',
    n.profile_fact_value = 'Zacatecas',
    n.confidence = 0.90;

MERGE (n:GeoArea {id: 'geo_hermosillo'})
SET n.canonical = 'Hermosillo',
    n.type = 'city',
    n.state = 'Sonora',
    n.aliases = ['hermosillo', 'hmo'],
    n.profile_fact_group = 'candidate',
    n.profile_fact_key = 'city',
    n.profile_fact_value = 'Hermosillo',
    n.confidence = 0.90;

MERGE (n:GeoArea {id: 'geo_mazatlan'})
SET n.canonical = 'Mazatlán',
    n.type = 'city',
    n.state = 'Sinaloa',
    n.aliases = ['mazatlan', 'mazatlán'],
    n.profile_fact_group = 'candidate',
    n.profile_fact_key = 'city',
    n.profile_fact_value = 'Mazatlán',
    n.confidence = 0.90;

// ─── GeoArea — states ─────────────────────────────────────────────────────────
// These save candidate.state (not city). The funnel nudge already asks
// "¿en qué ciudad?" when city is missing but state is known.

MERGE (n:GeoArea {id: 'geo_state_nuevo_leon'})
SET n.canonical = 'Nuevo León',
    n.type = 'state',
    n.aliases = ['nuevo leon', 'nuevo león', 'nuevoleon'],
    n.profile_fact_group = 'candidate',
    n.profile_fact_key = 'state',
    n.profile_fact_value = 'Nuevo León',
    n.confidence = 0.90;

MERGE (n:GeoArea {id: 'geo_state_tamaulipas'})
SET n.canonical = 'Tamaulipas',
    n.type = 'state',
    n.aliases = ['tamaulipas', 'tamps'],
    n.profile_fact_group = 'candidate',
    n.profile_fact_key = 'state',
    n.profile_fact_value = 'Tamaulipas',
    n.confidence = 0.88;

MERGE (n:GeoArea {id: 'geo_state_coahuila'})
SET n.canonical = 'Coahuila',
    n.type = 'state',
    n.aliases = ['coahuila', 'coah'],
    n.profile_fact_group = 'candidate',
    n.profile_fact_key = 'state',
    n.profile_fact_value = 'Coahuila',
    n.confidence = 0.88;

MERGE (n:GeoArea {id: 'geo_state_jalisco'})
SET n.canonical = 'Jalisco',
    n.type = 'state',
    n.aliases = ['jalisco', 'jal'],
    n.profile_fact_group = 'candidate',
    n.profile_fact_key = 'state',
    n.profile_fact_value = 'Jalisco',
    n.confidence = 0.88;

MERGE (n:GeoArea {id: 'geo_state_sinaloa'})
SET n.canonical = 'Sinaloa',
    n.type = 'state',
    n.aliases = ['sinaloa', 'sin'],
    n.profile_fact_group = 'candidate',
    n.profile_fact_key = 'state',
    n.profile_fact_value = 'Sinaloa',
    n.confidence = 0.88;

MERGE (n:GeoArea {id: 'geo_state_sonora'})
SET n.canonical = 'Sonora',
    n.type = 'state',
    n.aliases = ['sonora', 'son'],
    n.profile_fact_group = 'candidate',
    n.profile_fact_key = 'state',
    n.profile_fact_value = 'Sonora',
    n.confidence = 0.88;

// ─── VehicleType nodes ────────────────────────────────────────────────────────
// "full" alone is excluded: too ambiguous ("tengo full documentación").
// "quinta" alone is excluded: "quinta de mayo", "quinta avenida" etc.
// "tracto" alone is excluded: could be either trailer type.
// Only unambiguous terms or explicit multi-word phrases are included.
//
// REGLA (contrato domain_catalog / 10b.13): "quinta rueda" y variantes NO son
// un tipo de unidad — son jerga del oficio (experiencia compatible). El nodo
// legacy vehicle_quinta_rueda escribía experience.vehicle_type=quinta_rueda
// brincándose normalize_vehicle (bug observado en vivo, conv. 80/81). Se
// elimina y la limpieza es autocurativa al re-correr este seed:

MATCH (n:VehicleType {id: 'vehicle_quinta_rueda'})
DETACH DELETE n;

MERGE (n:VehicleType {id: 'vehicle_full'})
SET n.canonical = 'full',
    n.category = 'double_trailer',
    // 'doble' agregado 2026-07-07 (regla de negocio conv 163: "doble" = full)
    n.aliases = ['fulero', 'fulera', 'fuleros', 'doble articulado', 'doble', 'remolque doble'],
    n.profile_fact_group = 'experience',
    n.profile_fact_key = 'vehicle_type',
    n.profile_fact_value = 'full',
    n.confidence = 0.88;

// 'caja seca' suele referir a sencillo (regla de negocio 2026-07-07); el resumen de
// confirmación del funnel lo valida con el candidato. Solo vocabulario (lenguaje→concepto).
MERGE (n:VehicleType {id: 'vehicle_sencillo'})
SET n.canonical = 'sencillo',
    n.category = 'single_trailer',
    n.aliases = ['sensillo', 'censillo', 'caja seca'],
    n.profile_fact_group = 'experience',
    n.profile_fact_key = 'vehicle_type',
    n.profile_fact_value = 'sencillo',
    n.confidence = 0.75;
