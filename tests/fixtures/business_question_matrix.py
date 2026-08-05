"""Matriz adversarial de detección de pregunta de negocio.

Fuente única de casos para la suite determinista (`tests/unit`) y la eval con LLM
real (`tests/evals`). `expected_semantic` ∈ {True, False, "uncertain"}.

BQ-L11 y BQ-L18 están REFORMULADOS (preflight regla 2): no contienen `?` ni término
de `BUSINESS_QUESTION_TERMS` tras el normalizador real, preservando el significado.
"""
from __future__ import annotations

# Cada caso: id, group, message, expected_semantic, intent_family, facts_expected, facts_forbidden
CASES: list[dict] = [
    # ── A. llm_only_required (deben requerir la señal LLM) ────────────────────
    {"id": "BQ-L01", "group": "llm_only", "message": "d a komo da el km jaja k bonito ta el klima", "expected_semantic": True, "intent_family": "pay", "facts_forbidden": ["candidate.city"]},
    {"id": "BQ-L02", "group": "llm_only", "message": "x kilometro kuanto kae masomenos", "expected_semantic": True, "intent_family": "pay", "facts_forbidden": ["candidate.city"]},
    {"id": "BQ-L03", "group": "llm_only", "message": "una vuelta d esas k tanto deja pa uno", "expected_semantic": True, "intent_family": "pay"},
    {"id": "BQ-L04", "group": "llm_only", "message": "pa k lado se rueda mas seguido", "expected_semantic": True, "intent_family": "routes", "facts_forbidden": ["candidate.city"]},
    {"id": "BQ-L05", "group": "llm_only", "message": "ai jalones pa arriba o puro cerka", "expected_semantic": True, "intent_family": "routes", "facts_forbidden": ["candidate.city"]},
    {"id": "BQ-L06", "group": "llm_only", "message": "uno anda mucho fuera o regresa rapido", "expected_semantic": True, "intent_family": "travel_conditions"},
    {"id": "BQ-L07", "group": "llm_only", "message": "q ocupa uno pa entrar yo ya kiero jalar", "expected_semantic": True, "intent_family": "requirements"},
    {"id": "BQ-L08", "group": "llm_only", "message": "pa apuntarme k es lo primero k tengo k soltar", "expected_semantic": True, "intent_family": "onboarding_process"},
    {"id": "BQ-L09", "group": "llm_only", "message": "la oja medika esa komo ba o kien la da", "expected_semantic": True, "intent_family": "medical_document"},
    {"id": "BQ-L10", "group": "llm_only", "message": "lo d la pipi antes d entrar komo sta", "expected_semantic": True, "intent_family": "drug_test"},
    {"id": "BQ-L11", "group": "llm_only", "message": "el examen ese d la pipi se ase ai o asta despues", "expected_semantic": True, "intent_family": "drug_test", "reformulated": True},
    {"id": "BQ-L12", "group": "llm_only", "message": "a q ora se reporta uno aka", "expected_semantic": True, "intent_family": "schedule_or_callback"},
    {"id": "BQ-L13", "group": "llm_only", "message": "ya no ay chans pa meterse o todabia", "expected_semantic": True, "intent_family": "vacancy_availability"},
    {"id": "BQ-L14", "group": "llm_only", "message": "andan agarrando gente aun o ya se lleno", "expected_semantic": True, "intent_family": "vacancy_availability"},
    {"id": "BQ-L15", "group": "llm_only", "message": "ya andube con ustedes antes ai modo d bolber", "expected_semantic": True, "intent_family": "reingreso"},
    {"id": "BQ-L16", "group": "llm_only", "message": "nunk e jalado trailer aun asi se puede", "expected_semantic": True, "intent_family": "training_or_no_experience"},
    {"id": "BQ-L17", "group": "llm_only", "message": "es caja normal o d las dobles lo k mueven", "expected_semantic": True, "intent_family": "vehicle_operation"},
    {"id": "BQ-L18", "group": "llm_only", "message": "no ubico la oficina pa firmar aonde kae uno", "expected_semantic": True, "intent_family": "onboarding_process", "reformulated": True},

    # ── B. mixed_signal_robustness ────────────────────────────────────────────
    {"id": "BQ-M01", "group": "mixed", "message": "tngo B1 pero kiero saber si si se arma o nel", "expected_semantic": True, "intent_family": "license_eligibility", "facts_expected": {"license.type": "B1"}},
    {"id": "BQ-M02", "group": "mixed", "message": "traigo b y e juntas sirve pa entrar o ke", "expected_semantic": True, "intent_family": "license_eligibility"},
    {"id": "BQ-M03", "group": "mixed", "message": "si no tngo el aptt aun se puede ir avanzando", "expected_semantic": True, "intent_family": "medical_document"},
    {"id": "BQ-M04", "group": "mixed", "message": "me urge saber si pagan viatiko o eso va aparte", "expected_semantic": True, "intent_family": "pay"},
    {"id": "BQ-M05", "group": "mixed", "message": "k tan seguido sale uno de viaje", "expected_semantic": True, "intent_family": "routes"},
    {"id": "BQ-M06", "group": "mixed", "message": "si tengo 57 aun se puede o ya no", "expected_semantic": True, "intent_family": "age_eligibility"},
    {"id": "BQ-M07", "group": "mixed", "message": "me markan ustedes o yo tengo k ir", "expected_semantic": True, "intent_family": "schedule_or_callback"},
    {"id": "BQ-M08", "group": "mixed", "message": "tengo B pero ahi entrenan para full", "expected_semantic": True, "intent_family": "training_or_no_experience", "facts_expected": {"license.type": "B"}},
    {"id": "BQ-M09", "group": "mixed", "message": "k onda con el descanso en los viajes", "expected_semantic": True, "intent_family": "travel_conditions"},
    {"id": "BQ-M10", "group": "mixed", "message": "me interesa pero no se si es sencillo o full", "expected_semantic": True, "intent_family": "vehicle_operation"},

    # ── C. compound_messages (perfil + pregunta lateral + ruido) ──────────────
    {"id": "BQ-C01", "group": "compound", "message": "soy d torrion tngo 10 años full y d a komo da el km jaja", "expected_semantic": True, "intent_family": "pay", "facts_expected": {"candidate.city": "Torreón", "experience.years": "10", "experience.vehicle_type": "full"}},
    {"id": "BQ-C02", "group": "compound", "message": "vivo en gomez palasio y pa k lado se rueda mas seguido", "expected_semantic": True, "intent_family": "routes", "facts_expected": {"candidate.city": "Gómez Palacio"}, "facts_forbidden": ["candidate.city=Monterrey", "candidate.city=Nuevo Laredo"]},
    {"id": "BQ-C03", "group": "compound", "message": "tngo b1 y ya jale 2 años en rabon pero ai modo d entrar", "expected_semantic": True, "intent_family": "license_eligibility", "facts_expected": {"license.type": "B1", "experience.years": "2"}},
    {"id": "BQ-C04", "group": "compound", "message": "mi lisensia vence en agsto y la oja medika no la e renovado q ago primero", "expected_semantic": True, "intent_family": "medical_document", "facts_forbidden": ["medical.apto_status=vigente"]},
    {"id": "BQ-C05", "group": "compound", "message": "tngo 30 soy de lerdo y nunk e jalado trailer aun asi se puede", "expected_semantic": True, "intent_family": "training_or_no_experience", "facts_expected": {"candidate.age": "30", "candidate.city": "Lerdo"}},
    {"id": "BQ-C06", "group": "compound", "message": "mande foto d mis papeles pero el d la pipi como esta", "expected_semantic": True, "intent_family": "drug_test", "facts_forbidden": ["documents.proof=verified_from_image"]},
    {"id": "BQ-C07", "group": "compound", "message": "soy d saltillo pero me gustaria saber si ai salida pa monterrey", "expected_semantic": True, "intent_family": "routes", "facts_expected": {"candidate.city": "Saltillo"}, "facts_forbidden": ["candidate.city=Monterrey"]},
    {"id": "BQ-C08", "group": "compound", "message": "trabaje con ustedes ace años y ora kiero volver que se ocupa", "expected_semantic": True, "intent_family": "reingreso", "facts_expected": {"candidate.reingreso": "true"}},
    {"id": "BQ-C09", "group": "compound", "message": "tngo full y b e pero k tan seguido se sale", "expected_semantic": True, "intent_family": "routes", "facts_expected": {"experience.vehicle_type": "full"}},
    {"id": "BQ-C10", "group": "compound", "message": "tngo apto vigente pero no se si se ocupa antidopin", "expected_semantic": True, "intent_family": "drug_test"},
    {"id": "BQ-C11", "group": "compound", "message": "me interesa la vacante yo vivo en torreon pero no se cuanto deja x viaje", "expected_semantic": True, "intent_family": "pay", "facts_expected": {"candidate.city": "Torreón"}},
    {"id": "BQ-C12", "group": "compound", "message": "tngo 5 años pero mi ruta era local ai viajes de ida y vuelta", "expected_semantic": True, "intent_family": "routes", "facts_expected": {"experience.years": "5"}},
    {"id": "BQ-C13", "group": "compound", "message": "soy de gomez palacio primero mando papeles o voy a oficina", "expected_semantic": True, "intent_family": "onboarding_process", "facts_expected": {"candidate.city": "Gómez Palacio"}},
    {"id": "BQ-C14", "group": "compound", "message": "tngo licencia E y apto vence el mes k entra aun asi puedo aplicar", "expected_semantic": True, "intent_family": "license_eligibility", "facts_expected": {"license.type": "E"}},
    {"id": "BQ-C15", "group": "compound", "message": "yo puedo desde la otra semana ay turno de noche o como", "expected_semantic": True, "intent_family": "schedule_or_callback"},
    {"id": "BQ-C16", "group": "compound", "message": "tngo sencillo desde hace 4 años y quiero saber si luego suben a full", "expected_semantic": True, "intent_family": "training_or_no_experience", "facts_expected": {"experience.years": "4", "experience.vehicle_type": "sencillo"}},

    # ── D. negative_cases (mención de dominio que NO es pregunta) ──────────────
    {"id": "BQ-N01", "group": "negative", "message": "tngo 10 años en rutta nacional", "expected_semantic": False, "facts_expected": {"experience.years": "10"}},
    {"id": "BQ-N02", "group": "negative", "message": "mi lisensia b vence en agsto", "expected_semantic": False},
    {"id": "BQ-N03", "group": "negative", "message": "soi d torrion jaja k bonito ta el klima", "expected_semantic": False, "facts_expected": {"candidate.city": "Torreón"}},
    {"id": "BQ-N04", "group": "negative", "message": "ayer fui a monterrey y regrese hoy", "expected_semantic": False, "facts_forbidden": ["candidate.city=Monterrey"]},
    {"id": "BQ-N05", "group": "negative", "message": "el pago donde estaba era semanal", "expected_semantic": False},
    {"id": "BQ-N06", "group": "negative", "message": "mis papeles los mande ayer", "expected_semantic": False},
    {"id": "BQ-N07", "group": "negative", "message": "ando en casa asta las 7", "expected_semantic": False},
    {"id": "BQ-N08", "group": "negative", "message": "ya jale con ustedes ace años", "expected_semantic": False, "facts_expected": {"candidate.reingreso": "true"}},
    {"id": "BQ-N09", "group": "negative", "message": "tngo b1", "expected_semantic": False, "facts_expected": {"license.type": "B1"}},
    {"id": "BQ-N10", "group": "negative", "message": "el aptt lo renuevo el lunes", "expected_semantic": False},
    {"id": "BQ-N11", "group": "negative", "message": "no e jalado trailer", "expected_semantic": False},
    {"id": "BQ-N12", "group": "negative", "message": "me gustan los viajes largos", "expected_semantic": False},
    {"id": "BQ-N13", "group": "negative", "message": "llegue a la oficina", "expected_semantic": False},
    {"id": "BQ-N14", "group": "negative", "message": "mande la foto de mi licencia", "expected_semantic": False, "facts_forbidden": ["license.type=verified_from_image"]},
    {"id": "BQ-N15", "group": "negative", "message": "me llamaron pero iba dormido", "expected_semantic": False},
    {"id": "BQ-N16", "group": "negative", "message": "tengo caja sencilla desde 2020", "expected_semantic": False, "facts_expected": {"experience.vehicle_type": "sencillo"}},
    {"id": "BQ-N17", "group": "negative", "message": "mi ruta era laredo cada semana", "expected_semantic": False, "facts_forbidden": ["candidate.city=Nuevo Laredo"]},
    {"id": "BQ-N18", "group": "negative", "message": "toy disponible desde mañana", "expected_semantic": False},
    {"id": "BQ-N19", "group": "negative", "message": "mi primo trae licencia b1 pero yo no", "expected_semantic": False, "facts_forbidden": ["license.type=B1"]},
    {"id": "BQ-N20", "group": "negative", "message": "la camioneta de mi tio es full", "expected_semantic": False, "facts_forbidden": ["experience.vehicle_type=full"]},

    # ── E. ambiguous_cases (no inventar intención) ────────────────────────────
    {"id": "BQ-A01", "group": "ambiguous", "message": "kuanto", "expected_semantic": "uncertain"},
    {"id": "BQ-A02", "group": "ambiguous", "message": "y eso como", "expected_semantic": "uncertain"},
    {"id": "BQ-A03", "group": "ambiguous", "message": "b1", "expected_semantic": "uncertain"},
    {"id": "BQ-A04", "group": "ambiguous", "message": "q onda con eso", "expected_semantic": "uncertain"},
    {"id": "BQ-A05", "group": "ambiguous", "message": "ai o no ai", "expected_semantic": "uncertain"},
    {"id": "BQ-A06", "group": "ambiguous", "message": "pa donde", "expected_semantic": "uncertain"},
    {"id": "BQ-A07", "group": "ambiguous", "message": "komo va", "expected_semantic": "uncertain"},
    {"id": "BQ-A08", "group": "ambiguous", "message": "me interesa pero pues no se", "expected_semantic": "uncertain"},
]
