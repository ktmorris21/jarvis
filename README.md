# Jarvis Core — Cognition POC

Core is Jarvis. Devices are interfaces/body services. Interpretation belongs in Core by default; interfaces handle hardware-local, latency-sensitive, and safety-critical work.

This iteration proves an additional architectural seam: **the executive decides when cognition is warranted; the LLM does not run the heartbeat or directly control interfaces.** Cognition returns one validated decision: `SPEAK` or `DO_NOTHING`.

## Railway-first deployment

Deploy this repository to the existing Railway service. Keep your existing interface token and add:

```text
OPENAI_API_KEY=<your OpenAI API key>
JARVIS_OPENAI_MODEL=gpt-5.6-luna
```

`gpt-5.6-luna` is the default for this inexpensive POC. You can change the model with the Railway variable without editing code.

If `OPENAI_API_KEY` is absent, Core deliberately falls back to the original deterministic greeting so the service remains testable rather than crashing.

Existing optional variables remain:

```text
JARVIS_HEARTBEAT_SECONDS=2
JARVIS_SOCIAL_TRIGGER_SECONDS=20
```

After Railway redeploys, open:

```text
https://YOUR-SERVICE.up.railway.app/state
```

The state now includes:

```json
"cognition": {
  "enabled": true,
  "last_action": null,
  "last_reason": null,
  "last_at": null
}
```

Connect the existing desktop interface:

```bash
python3 clients/desktop_interface.py \
  --url https://YOUR-SERVICE.up.railway.app \
  --token YOUR_TOKEN
```

Then test:

```text
idle
```

Wait long enough to represent an absence, then:

```text
active
```

The executive will decide that the return warrants cognition. The model may choose to say something or may choose `DO_NOTHING`. Refresh `/state` to inspect the last action and the model's short reason.

## Architecture in this POC

```text
Interface event
     ↓
Core state / drives
     ↓
Executive gate (deterministic)
     ↓
Is cognition warranted?
     ↓ yes
Cognition service / OpenAI
     ↓
validated SPEAK | DO_NOTHING
     ↓
Core capability dispatch
     ↓
Interface
```

The OpenAI call uses structured parsing into a Pydantic model. Arbitrary model-generated abilities are not accepted.

## Layout

```text
jarvis-poc/
├── jarvis_core/
│   ├── cognition.py   # bounded LLM cognition resource
│   ├── executive.py   # state/drive gatekeeper + action dispatch
│   ├── main.py        # FastAPI + WebSocket gateway
│   ├── state.py       # temporary in-memory state + introspection
│   ├── models.py      # interface protocol
│   └── config.py
├── clients/
│   └── desktop_interface.py
├── tests/
├── railway.json
├── requirements.txt
└── .env.example
```

## Deliberately still missing

- PostgreSQL/persistent memory
- rich event bus
- actual TTS/audio
- camera/vision perception
- unique per-interface credentials
- goals/task planning
- PiCar body service

Those should be added only after this cognition seam behaves sensibly.
