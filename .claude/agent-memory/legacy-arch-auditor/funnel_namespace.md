---
name: funnel-namespace
description: 4 divergent funnels and incompatible fact key namespaces (license/apto) in Transmontes bot
metadata:
  type: project
---

FOUR funnel definitions (verified 2026-07):
1. `current_turn._next_funnel_question_or_none` (current_turn.py:535) — LIVE. Order: name, city, age, vehicle_type, **license.category**, license.expiration_text, **medical.apto_expiration_text**, years, labor doc.
2. `knowledge_orchestrator._FUNNEL_STEPS` (line 1463, used 1702) — LIVE. Same keys (license.category, medical.apto_expiration_text); order name, city, age, vehicle, license.category, license.exp, apto_exp, years.
3. `intent_orchestrator.FUNNEL_STEPS` (line 79) — SHADOW.
4. `funnel_state_planner.CORE_FIELDS` (line 29) — NOT wired live. Uses **license.type**, **medical.apto_status**, documents.proof, candidate.city, experience.vehicle_type, experience.years. **OMITS candidate.name and candidate.age** that the live funnels ask.

Namespace incompatibility:
- Live extractors WRITE `license.category` (turn_extractor.py:49/330, profile_extractor.py:314-327) and `medical.apto_status` + `medical.apto_expiration_text` (profile_extractor.py:337-376). turn_extractor writes only apto_expiration_text.
- Live funnel gates READ `license.category` and `medical.apto_expiration_text` (consistent with writers).
- `license.type` is written by NOBODY live; READ only by SHADOW `memory_guard.py:39` and `turn_planner.py:42`.
- v2-projection change picks `license.type` as canonical (inverts fix-license-key direction) → migration = rename across live code + rewire shadow.
- apto split: note reads `medical.apto_status` (chatwoot_note_sync.py:551) but funnel gate reads `medical.apto_expiration_text` → status known ≠ funnel satisfied.
- Namespace sprawl for apto: `medical.apto_status`, `document.apto_status` (singular! profile_extractor.py:373), `documents.general_status` — all read as fallbacks in chatwoot_note_sync.py:551. The v2 change's compat matrix (D4) does NOT mention `document.apto_status`/`documents.general_status` nor the name/age omission.

Timezone: two canonical zones coexist — `America/Monterrey` (celery_app.py:25, followup/ventana.py:7) vs `America/Mexico_City` (business_hours.py:15, "decisión #15").
