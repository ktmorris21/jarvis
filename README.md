# Jarvis Core + PiCar-X Body POC

Core is Jarvis. The PiCar-X, desktop, phone, speaker, and future devices are interfaces/body services.

This iteration proves targeted capability routing from the Railway-hosted Core to a physical PiCar-X body over the public Internet.

## What changed

- Commands can target a specific connected interface (`picar-main`).
- Core validates that the target actually advertises the requested ability.
- PiCar body service advertises `look`, `move`, and `stop`.
- SunFounder-specific calls are isolated in `body_services/picar/hardware.py`.
- The body clamps speed, steering, pan/tilt, and movement duration locally.
- Every `move` command must have a finite duration; max is 1000 ms in this POC.
- Network loss calls `stop()` locally before reconnecting.
- PiCar reports `COMMAND_RESULT` back to Core.
- `/debug/command` provides a temporary authenticated way to exercise a body capability without involving cognition.

## Deploy Core to Railway

Update the existing GitHub repo with these files and let Railway redeploy. Existing variables remain valid:

```text
JARVIS_INTERFACE_TOKEN=...
OPENAI_API_KEY=...
JARVIS_OPENAI_MODEL=gpt-5.6-luna
```

No additional Railway services or variables are needed.

Check:

```text
https://YOUR-SERVICE.up.railway.app/health
https://YOUR-SERVICE.up.railway.app/state
```

## Prepare the PiCar-X

This assumes the SunFounder PiCar-X software is already installed and this succeeds on the Pi:

```bash
python3 -c "from picarx import Picarx; print('PiCar-X library OK')"
```

Install only the network dependency if necessary:

```bash
python3 -m pip install websockets
```

Copy this repository onto the Pi, then from the repo root run:

```bash
python3 -m body_services.picar.main \
  --url https://YOUR-SERVICE.up.railway.app \
  --token YOUR_TOKEN
```

Expected output:

```text
Connected to Jarvis Core: {'type': 'hello_ack', 'interface_id': 'picar-main', 'core': 'jarvis'}
```

Open `/state`; `picar-main` should appear as a `mobile_body` with `look`, `move`, and `stop` capabilities.

## First physical test: camera head only

Use curl from any machine. Replace URL/token as needed:

```bash
curl -X POST 'https://YOUR-SERVICE.up.railway.app/debug/command' \
  -H 'Content-Type: application/json' \
  -H 'X-Jarvis-Token: YOUR_TOKEN' \
  -d '{"target":"picar-main","ability":"look","data":{"pan_deg":25,"tilt_deg":0}}'
```

Then center it:

```bash
curl -X POST 'https://YOUR-SERVICE.up.railway.app/debug/command' \
  -H 'Content-Type: application/json' \
  -H 'X-Jarvis-Token: YOUR_TOKEN' \
  -d '{"target":"picar-main","ability":"look","data":{"pan_deg":0,"tilt_deg":0}}'
```

## Second physical test: bounded motion

Put the PiCar on the floor with clear space. This command requests 20% forward power for only 400 ms:

```bash
curl -X POST 'https://YOUR-SERVICE.up.railway.app/debug/command' \
  -H 'Content-Type: application/json' \
  -H 'X-Jarvis-Token: YOUR_TOKEN' \
  -d '{"target":"picar-main","ability":"move","data":{"direction":"forward","speed":20,"duration_ms":400,"steering_deg":0}}'
```

The body will stop itself when the duration expires. In this POC it will also clamp any request to:

- speed <= 35
- duration <= 1000 ms
- steering between -30 and +30 degrees
- pan/tilt between -35 and +35 degrees

You can explicitly issue stop:

```bash
curl -X POST 'https://YOUR-SERVICE.up.railway.app/debug/command' \
  -H 'Content-Type: application/json' \
  -H 'X-Jarvis-Token: YOUR_TOKEN' \
  -d '{"target":"picar-main","ability":"stop","data":{}}'
```

## Mock mode

To prove the Pi networking path without touching motors/servos:

```bash
python3 -m body_services.picar.main \
  --url https://YOUR-SERVICE.up.railway.app \
  --token YOUR_TOKEN \
  --mock
```

## Architecture demonstrated

```text
Railway Jarvis Core
      |
      | authenticated WSS
      v
PiCar body service
      |
      | validated semantic ability
      v
SunFounder hardware wrapper
      |
      v
motors / camera servos
```

Core never calls `Picarx.forward()` or a servo API. It knows only that `picar-main` provides abilities such as `move` and `look`.
