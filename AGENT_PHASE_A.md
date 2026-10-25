# Phase A — Agents SDK integration

This branch adds an **opt-in** Agents SDK conversation path without replacing Jarvis's Core, memory storage, ROS status bridge, or legacy cognition path.

## What changes

- `jarvis_core/agent_runtime.py` builds the Core-owned agent with a compact identity/state/goal baseline and **no injected duplicate conversation transcript**.
- SDK `SQLAlchemySession` persists the **single Jarvis conversation** under `jarvis-primary`, using the existing `DATABASE_URL` (PostgreSQL in Railway; SQLite supported locally).
- Agent has two read-only tools:
  - `search_memories(query)`: retrieves up to five existing persistent memories.
  - `get_robot_status()`: sends a request to the existing `picar-ros` ROS status bridge and awaits a matching command result (6-second default timeout).
- A per-process turn lock prevents overlapping session writes for a single Core worker.
- The legacy response pipeline remains a fallback.
- **Autonomous curiosity actions are disabled by default** while navigation safety work is paused.

## Deployment / evaluation

1. Install the updated requirements and run `python -m pytest -q`.
2. Confirm `DATABASE_URL` points to persistent PostgreSQL on Railway and `OPENAI_API_KEY` is configured.
3. Confirm `picar-ros` is connected to Core. Enable the SDK path with Railway env var `JARVIS_AGENT_ENABLED=true`. Leave `JARVIS_AUTONOMOUS_CURIOSITY_ENABLED=false`.
4. Connect the existing desktop client and ask, "Is your LiDAR working?" Compare response to live `/state` robot status.
5. Ask a follow-up and a question about an earlier memory, ensuring the SDK session retains context while long-term memory retrieval is tool-driven.
6. Set `JARVIS_AGENT_ENABLED=false` for immediate rollback to the original cognition path.

## Boundaries and follow-ups

- This is **Phase A only**: camera, speech-device integration, automatic memory formation from agent replies, and motor control are not added.
- Session storage handles conversation continuity; durable semantic/episodic memories remain Core-managed.
- SDK runner is bounded by `JARVIS_AGENT_MAX_TURNS` (default 4) and `JARVIS_AGENT_TIMEOUT_SECONDS` (default 50).
- Current usage logging is diagnostic, not a hard billing ceiling. Configure API project budgets/alerts and hard application request limits before uncontrolled automation.
- For multi-worker Railway deployment, move the per-process turn lock and in-flight status correlation to shared coordination; Phase A assumes a single worker.
- Agent exceptions fall back to old cognition; if a model call fails after partial SDK history persistence, review session continuity before assuming exactly-once conversation insertion.
- Do not enable curiosity movement until physical safety is separately validated.
