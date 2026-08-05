---
name: flow-map
description: Live turn flow of the Transmontes recruiting bot; which modules are LEGACY/CANONICAL/SHADOW
metadata:
  type: project
---

Live turn flow (verified 2026-07):

webhook `app/app.py:1056 chatwoot_webhook`
→ if `INBOUND_DEBOUNCE_ENABLED!=false` (default) → `enqueue_chatwoot_message` (worker). The synchronous branch `app/app.py:1441-1600+` only runs when the flag is false (diagnostic), but is a live-capable DUPLICATE of the worker projection sequence.
→ worker `app/tasks_chatwoot.py process_chatwoot_batch` (~line 357+): pre-extraction (`turn_extractor.extract_turn`) → `run_hr_graph_message` (ALWAYS) → optional first_contact_greeting override → optional current-turn guard override (`_guard_should_fire` line 508) → `_maybe_prepend_first_reply_intro` (line 647) → send + note/labels.
→ `app/graphs/hr_graph.py run_hr_graph_message` → `app/orchestrators/knowledge_orchestrator.py handle_message` (line 1763) = LIVE brain.

Persistence: TWO stores.
- V2 lead memory `rh_leads_v2` via `save_lead_message` (`repository.py`) — CANONICAL going forward.
- Legacy `rh_conversations`/messages via `db.save_message` — LEGACY, still written every turn (`knowledge_orchestrator.py:2189`).

Module status:
- `knowledge_orchestrator` = LIVE/CANONICAL brain.
- `current_turn` (`_next_funnel_question_or_none`) = LIVE (funnel gate used by orchestrator lines 72/93/106 + worker guard).
- `intent_orchestrator` / `memory_guard` / `turn_planner` / `intent_shadow` = SHADOW multi-intent subsystem (only `/classify` test endpoint app.py:363 + `run_shadow` gated by `MULTI_INTENT_SHADOW` + each other).
- `funnel_state_planner.plan()` = NOT wired live at all; only `CanonicalFact` dataclass imported by `canonical_profile_reader` (shadow). The v2-projection change proposes making it the single authority — greenfield wiring.
- `profile_extractor` = LIVE (called by orchestrator 1075/1246/1385/1636 and current_turn 372).
- `beat` (hr_beat, docker-compose.yml:123) = LIVE cron; schedules `seguimiento.programar_tareas` (*/15) + `enviar_pendientes` (*/5) in `celery_app.py:32`.

Chatwoot projection helpers live in `app/app.py` (god file, 1636 lines): `_send_chatwoot_message` 619, `_set_chatwoot_labels` 769, `_send_chatwoot_private_note` 810, `_build_chatwoot_internal_note` 986, `_normalize/_fallback_chatwoot_labels` 658/685, `_get_rh_work_queue_metadata` 714, `_human_*` 849+. Worker imports them from `app.app` (`tasks_chatwoot.py:359`).
