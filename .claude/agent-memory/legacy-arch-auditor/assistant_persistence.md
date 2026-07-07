---
name: assistant-persistence
description: Ghost/double assistant messages and post-persistence reply mutation in Transmontes worker
metadata:
  type: project
---

Verified 2026-07. Per candidate turn the delivered text can diverge from persisted assistant memory:

- `knowledge_orchestrator.handle_message` persists the orchestrator reply to BOTH stores every turn: V2 `save_lead_message(role=assistant)` (`_store_lead_memory_updates`, line 1207) + legacy `save_message(..., "assistant", reply)` (line 2189).
- Worker `tasks_chatwoot.py` runs `run_hr_graph_message` FIRST (line 444), THEN may override the reply via the current-turn guard (`_guard_should_fire`, line 508) which persists ANOTHER assistant row to V2 (`_slm`, line 595) with `guarded_reply`.
  → When guard fires: V2 has 2 assistant rows (orchestrator ghost @1207 + guarded_reply @595); legacy has 1 assistant row (orchestrator ghost @2189); only guarded_reply is delivered.
- `_maybe_prepend_first_reply_intro` (line 647) mutates the reply AFTER all persistence → the intro-prefixed text actually delivered is NEVER stored anywhere.

This is the structural premise behind change `unified-turn-decision-v2-projection` D1/D2 (TurnDecision immutable + single assistant = delivered text). Premise CONFIRMED true.

Compound multi-intent (bug #3): live path DOES answer embedded questions — `_resolve_embedded_question` (knowledge_orchestrator.py:287) prepends the answer at line 1972-1976. Failure is in DETECTION, not composition: gated by `_looks_like_question` heuristic (needs "?" or BUSINESS_QUESTION_TERMS, line 282) AND a second `classify_message`/`enrich` pass requiring a `requires_rag` question (line 318-322); either miss → returns None → question silently dropped. Also the worker guard uses a DIFFERENT detector (`_pre_extraction.signals.has_embedded_question`, line 503) than the orchestrator — disagreement drops the question. The v2 change's D5 assumes reliable detection and does not address these gates.
