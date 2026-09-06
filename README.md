# Jarvis Core — Proof of Concept

This is the smallest useful implementation of the project architecture:

> **Core is Jarvis. Devices are interfaces/body services.**
>
> Interpretation belongs in Core by default. Edge/interface code handles hardware-local, latency-sensitive, and safety-critical work.

The POC intentionally has no LLM, database, camera, microphone, or PiCar code yet. It proves four things first:

1. Jarvis Core is a persistent process independent of any interface.
2. Interfaces connect outbound to Core over an authenticated WebSocket.
3. Interfaces advertise capabilities instead of Core knowing device brands/models.
4. Core can independently originate an action (`speak`) based on state and an agency loop.

## Layout

```text
jarvis-poc/
├── jarvis_core/
│   ├── main.py        # FastAPI + WebSocket gateway
│   ├── executive.py   # tiny deterministic agency loop
│   ├── state.py       # temporary in-memory Jarvis state
│   ├── models.py      # protocol messages
│   └── config.py
├── clients/
│   └── desktop_interface.py
├── tests/
├── railway.json
├── requirements.txt
└── .env.example
```

## Local test

Requires Python 3.11+.

```bash
cd jarvis-poc
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn jarvis_core.main:app --reload
```

In a second terminal:

```bash
cd jarvis-poc
source .venv/bin/activate
python clients/desktop_interface.py
```

You should see a connection acknowledgement.

### Test agency

At the desktop client prompt:

```text
> idle
```

Wait several seconds, then:

```text
> active
```

Core sees a user return, raises the social drive, and—without a user request for speech—may send:

```text
JARVIS: There you are. I was beginning to wonder where you went.
```

This is deliberately deterministic. The next step is to put cognition behind the same executive seam rather than letting an LLM become the executive loop.

You can inspect Core state at:

```text
http://127.0.0.1:8000/state
```

Run tests:

```bash
pytest -q
```

## Railway deployment

Railway can deploy this directly from a GitHub repository. `railway.json` supplies the start command and `/health` health check.

Set this Railway variable to a long random secret:

```text
JARVIS_INTERFACE_TOKEN=<long-random-token>
```

Optionally:

```text
JARVIS_HEARTBEAT_SECONDS=2
JARVIS_SOCIAL_TRIGGER_SECONDS=20
```

Generate a Railway public domain. Then connect the desktop interface with:

```bash
python clients/desktop_interface.py \
  --url https://YOUR-SERVICE.up.railway.app \
  --token YOUR_LONG_RANDOM_TOKEN
```

The client converts `https://` to `wss://` automatically.

## What is intentionally temporary

- **Authentication:** one shared token. Later: unique credential per interface.
- **State:** in memory. Later: PostgreSQL-backed persistent state/memory.
- **Event bus:** direct function calls. Later: internal bus abstraction, then queue only if scaling requires it.
- **Agency:** deterministic drive threshold. Later: attention + goals + selective LLM cognition.
- **Speaker:** text printed by the desktop client. Later: TTS audio playback capability.
- **Presence:** manually generated. Later: desktop activity, microphone/VAD, camera/perception, etc.

## Protocol principle

Core sends semantic abilities:

```json
{
  "type": "command",
  "ability": "speak",
  "data": {"text": "There you are."}
}
```

Future PiCar Core commands should look like `go_to`, `look_at`, `follow`, etc.—not raw PWM or motor commands.
