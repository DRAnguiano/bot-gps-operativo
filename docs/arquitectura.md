# Arquitectura del Agente AI — mapa de módulos y reglas de negocio

Objetivo: entender **qué hace cada parte y dónde vive cada regla de negocio**, para
cambiar lógica sin perderse y sin generar deuda. Actualizado 2026-07-01.

> ⚠️ Varias reglas viven HOY en más de un lugar (deuda estructural). El cambio
> OpenSpec `unified-turn-decision-v2-projection` (PR #12) las centraliza. Mientras
> tanto, este doc marca **todos** los lugares a tocar.

## 1. Flujo de un turno del candidato

```
WhatsApp → Chatwoot → webhook (app/app.py /chatwoot/webhook)
  └─ INBOUND_DEBOUNCE_ENABLED=true (default): encola (tasks_chatwoot.enqueue) ──┐
  └─ =false (solo diagnóstico): procesa síncrono en el mismo webhook           │
                                                                               ▼
  Worker Celery (app/tasks_chatwoot.py) — debounce ~6s, combina mensajes
   ├─ extracción única del turno: turn_extractor.extract_turn (LLM) → facts
   ├─ guard current_turn (ack determinista si aplica)
   ├─ orquestador: graphs/hr_graph.run_hr_graph_message → orchestrators/knowledge_orchestrator
   │    ├─ clasifica (intent_classifier, business_route_classifier)
   │    ├─ arma reply (friendly / RAG / profile ack / funnel nudge)
   │    ├─ persiste facts (lead_memory) y decide stage
   │    └─ answer_primary_question (multi-intent para compuestos)
   └─ proyección a Chatwoot: reply + nota IA + labels
        (helpers viven en app/app.py, importados por tasks_chatwoot; nota en chatwoot_note_sync.py)

Aparte: beat (hr_beat) agenda seguimientos (tasks_seguimiento) que el worker ejecuta.
```

## 2. Mapa de módulos (qué hace / por qué)

| Módulo | Responsabilidad |
|---|---|
| `app/app.py` | **God file**: server FastAPI + endpoints (`/health`, `/ask`, `/orchestrate`, `/classify`, `/reindex`, `/admin/release-human-review`, `/chatwoot/webhook`) **y** hogar de helpers de proyección Chatwoot (envío, labels, nota, formatters `_human_*`). El worker importa esos helpers desde aquí. |
| `app/tasks_chatwoot.py` | Worker inbound: debounce, extracción pre, guard, llama orquestador, persiste, proyecta a Chatwoot. |
| `app/graphs/hr_graph.py` | Entry point `run_hr_graph_message` (usado por app.py y tasks_chatwoot). |
| `app/orchestrators/knowledge_orchestrator.py` | Orquestación: clasifica, arma reply (friendly/RAG/ack), funnel nudge, persiste facts, stage, multi-intent. |
| `app/knowledge/current_turn.py` | Guard de turno + funnel legacy (`_next_funnel_question_or_none`), acuse, vigencias, residencia. |
| `app/knowledge/funnel_state_planner.py` | Planner canónico del funnel (CORE_FIELDS, profile_ready). **Será la autoridad única** tras la consolidación. |
| `app/knowledge/turn_extractor.py` | Extractor unificado LLM del turno → facts (namespace + señales). |
| `app/knowledge/business_route_classifier.py` (+ `_policy`, `_schema`) | Clasificación de negocio (pago, rutas, B1, etc.) — hoy en **shadow**. |
| `app/knowledge/intent_classifier.py` | Clasificador multi-intent vivo (usado por `_resolve_embedded_question`). |
| `app/knowledge/context_builder.py` | Prompt de generación RAG (persona Mundo, políticas, contexto recuperado). |
| `app/knowledge/reply_cleaner.py` | Limpieza unificada de respuestas LLM (`<think>`, blockquotes, cierres genéricos). |
| `app/indexer.py` | RAG (índice Chroma bge-m3) + clientes LLM Groq (generación/JSON/visión/whisper) + persona system message. |
| `app/chatwoot_note_sync.py` | Construcción de la Nota IA + labels `falta_*` / estado. |
| `app/lead_memory/` | Persistencia de facts/memoria (V2 `rh_leads_v2`) y lectura canónica. |
| `app/followup/` + `app/tasks_seguimiento.py` | Seguimientos programados (agendados por `beat`, ejecutados por el worker). |
| `data/*.md` | Corpus RAG (fuente de pago, rutas, documentos, antidoping, jerga). |
| `app/knowledge/neo4j_seed_hr_rules.cypher` | Seed Neo4j: vocabulario/coloquialismos y contratos de políticas (NO política operativa). |
| `.env` | Config runtime: modelos LLM (split qwen/70b), flags (debounce, shadow), claves Groq. |

## 3. ¿Dónde cambio cada regla de negocio?

### Vacantes ofrecidas (full / sencillo) — tu ejemplo "hoy full, mañana solo sencillo"
Hoy vive en **varios lugares** (por eso la consolidación):
- **Texto de la pregunta de unidad**: `current_turn.py` (`_next_funnel_question_or_none`, rama sin licencia: "tenemos vacantes para operador de tracto full y de sencillo").
- **Campo del funnel**: `funnel_state_planner.py` `CORE_FIELDS` → `experience.vehicle_type`.
- **Condición licencia→unidad**: `current_turn.py` (B → solo sencillo; E → full+sencillo).
- **Normalización de jerga** (quinta rueda, torton): `domain_catalog.py` / `normalize_domain_values`.
- **Corpus RAG**: `data/04_bases_rutas.md`, `data/01_pago_prestaciones.md` mencionan full/sencillo.
- **Saludo/intro**: `orchestrators/knowledge_orchestrator._GREETING_INTRO` y seed Neo4j.
→ Para "solo sencillo": tocar los 3 primeros + intro + revisar RAG. (Tras la consolidación: un solo lugar.)

### Licencia válida (B/E; A no es apta)
- Esquema/valores: `business_route_schema.py`, `intent_classifier.py` (`license.type` B|E|A|C).
- Lógica funnel B→sencillo / E→ambas: `current_turn.py`.
- (Pendiente: quitar "A" de las preguntas — ver `fact-corrections` y propuesta de licencia.)

### Edad límite de descalificación
- **Un solo lugar**: `app/settings.py` → `AGE_DISQUALIFICATION_LIMIT` (default 57, por env). Usado en `current_turn.is_age_disqualified`.

### Documentos por residencia (ZM La Laguna vs foráneo)
- Regla: `current_turn.residency_document_question` + `residency_is_local`.
- Catálogo de localidades: `geo_utils.py` / `zm_laguna_localities.json`.
- Requisitos/copy: `data/02_documentos_requisitos.md`.

### Rutas de handoff (B1 / escuelita / cecati / reingreso)
- Clasificación: `business_route_classifier.py` (+ `_policy`, `_schema`).
- Pre-verificación mínima: `current_turn.next_prehandoff_question`.
- Acuse por motivo: `chatwoot_note_sync.py` / handoff replies.

### Pago, rutas, antidoping (respuestas informativas)
- **Corpus RAG** (`data/*.md`) — se editan los .md y se reindexa (`/reindex`). NO se hardcodean cifras en código.
- `01_pago_prestaciones.md` (km, tramos, semanal), `04_bases_rutas.md`, `03_seguridad_antidoping.md`.

### Modelos LLM y cuota
- `.env`: `GROQ_MODEL` (generación=qwen3-32b `/no_think`), `UNIFIED_EXTRACTOR_MODEL`/`GROQ_CLASSIFIER_MODEL` (=70b, vigencia), 3 claves Groq. Ver `memory/project_model_config_split`.

### Persona / voz de Mundo
- `app/persona_config.py` (reglas de voz), `indexer._llm_system_message` (system del generador), `.env: ASSISTANT_PUBLIC_INTRO` (intro de primer reply).

## 4. Deuda conocida (a resolver en la consolidación)
- Reply se compone/reemplaza en varias capas → `TurnDecision` inmutable.
- 4 definiciones de funnel → `funnel_state_planner` autoridad única.
- Claves incompatibles (`license.category`/`type`, `apto_status`/`apto_expiration_text`) → namespace canónico.
- Doble flujo de proyección (webhook-sync vs worker) → outbox único.
- Legacy DB vs V2 → V2 única verdad.
- `beat` puede quedar stale si el deploy no lo incluye (`up -d api worker` omite beat).

Ver `openspec/changes/unified-turn-decision-v2-projection/` para el plan completo.
