# Jarvis: Agents SDK only

The Agents SDK is the sole conversational engine. The old cognition, context selection, side-effect proposal, and manually injected working-memory modules were removed. Core still owns identity, episodic/semantic memory, attention, world state, goals and ROS communications.

- `OPENAI_API_KEY` must be configured in Railway.
- `JARVIS_AGENT_ENABLED` is no longer used and can be removed.
- `JARVIS_AGENT_MODEL` selects the agent model (default `gpt-5.6-luna`).
- `JARVIS_AUTONOMOUS_CURIOSITY_ENABLED=false` remains the safety default.
- The desktop client requires its standard Core URL and interface token.

A failed model/session/tool call now produces a visible "OpenAI agent is unavailable" message, with a traceback under `Agent conversation failed` in Railway logs. **No alternate LLM or legacy conversation logic runs.** This is a handled operational error, not successful cognition.

Tests: `python -m pytest -q`. In Railway check the current deployment and attempt:

```
say Hey Jarvis, how are you doing?
say Can you check your LiDAR status right now?
say What do you remember about our previous LiDAR issues?
```

For LiDAR tool requests, ensure the `picar-ros` bridge is connected. Check for `agent turn: requests=` in Railway logs. Agent-only behavior does not imply live telemetry when the bridge is offline.
