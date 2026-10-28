# Jarvis interface-unification refactor

## Invariant

Jarvis Core owns identity, world-state context, memory retrieval, tool schemas,
tool dispatch, and canonical dialogue records. User interfaces select model
and media but do not implement independent robot abilities.

## Implemented

- `jarvis_core/abilities.py` is the sole Core tool registry and dispatcher.
  `/realtime/context` advertises the same four schemas that
  `agent_runtime.py` adapts into Agents SDK `FunctionTool` instances.
- `/realtime/tool` dispatches through the same allowlisted implementation
  as the desktop agent, preserving input checks and current robot-status
  and memory-service behavior.
- Both model paths use `baseline_context()` for Jarvis identity, drives,
  goals and live-state caveats. Voice additionally gets voice-delivery guidance.
- The canonical `CONVERSATION_TURN` event includes role, session ID,
  transcript, input mode and source for **both** voice and desktop.
- Realtime's bounded recent-history endpoint now reads both interfaces.
  Desktop's persistent Agents SDK session remains in place; its baseline
  also receives recent voice turns (not duplicated desktop turns).
- Memory formation is intentionally unchanged. Transcript capture alone
  does not create semantic memories.

## Current limitations / follow-on

- `inspect_environment` has one schema/implementation, but the fresh
  three-view camera capture still lives in the Pi Realtime client.
  Desktop receives an explicit unavailable result until a safe, authenticated,
  Core-mediated remote camera capture facility is implemented. The registry
  does not misrepresent an old sensor observation as a fresh capture.
- `finish_conversation` remains intentionally Pi-local (wake-word session
  control, not a Core cognitive capability).
- The canonical record currently has no replay deduplication or retention
  policy, and conversation consolidation remains separate work.
- Runtime tests on Railway and the Pi are still required before merging.

## Suggested smoke tests

1. Desktop: ask for LiDAR status and search a historical memory.
2. Voice: ask for LiDAR status and search the same memory.
3. Desktop: ask something distinctive, then wake Pi and make an elliptical
   follow-up; verify it restores the desktop transcript.
4. Pi: discuss a topic, close the session, and follow up on desktop.
5. Voice: inspect a live scene; confirm it still captures and analyzes
   the three views.
6. Desktop: request camera inspection; expect an explicit unavailable result
   rather than an invented image or claim.
