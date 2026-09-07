# Jarvis Eyes — Vision POC

This phase gives Jarvis a first visual sense without continuous video or Pi-side vision inference.

## Architecture

```text
Pi Camera
   ↓
rpicam-still / libcamera-still
   ↓
JPEG
   ↓ HTTP
Jarvis Core
   ↓
vision model
   ↓
VISUAL_OBSERVATION
   ↓
attention / state / event history
```

The Pi does not identify people or objects. It only captures a frame.

## Railway

Deploy this version over the existing Core. Existing Postgres schema is unchanged.

Optional variable:

```text
JARVIS_VISION_MODEL=gpt-5.6-luna
```

`GET /health` should report:

```text
v1-vision-poc
```

## Pi camera smoke test

Before Jarvis, verify the camera stack:

```bash
rpicam-still -n --width 640 --height 480 -o test.jpg
```

If `rpicam-still` isn't available, try:

```bash
libcamera-still -n --width 640 --height 480 -o test.jpg
```

The body service automatically chooses whichever exists.

## Run Jarvis

Use the same audio/VAD arguments as before:

```bash
python3 -m body_services.picar.main   --url https://jarvis-production-110e.up.railway.app   --token YOUR_TOKEN   --audio-input plughw:5,0   --audio-output plughw:5,0   --vad
```

At the console prompt:

```text
see
```

Expected flow:

```text
Capturing camera frame...
Sending ... bytes to Jarvis Core...
Jarvis sees: ...
Notable: ...
```

Inspect:

```text
GET /state
GET /events
```

`/state` includes `last_visual_observation`.

## Scope

This intentionally does NOT yet do:

- continuous video
- local object/person detection
- face recognition
- identity recognition
- scene-change detection
- autonomous camera polling
- visual memory consolidation

Once this one-frame path is solid, the next phase is to make vision event-driven rather than manually triggered.
