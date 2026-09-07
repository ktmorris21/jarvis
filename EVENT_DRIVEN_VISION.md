# Jarvis Eyes — Event-Driven Vision

This phase removes the manual `see` requirement for ordinary visual changes.

## Architecture

```text
Pi camera
   ↓
tiny 160×120 YUV420 monitor stream (~2 fps)
   ↓
local luminance frame comparison
   ↓
no material change ───────────────→ discard locally
   ↓
scene changed
   ↓
stop tiny monitor stream
   ↓
capture normal 640×480 JPEG
   ↓
send JPEG to Jarvis Core
   ↓
vision interpretation
   ↓
VISUAL_OBSERVATION
   ↓
attention / state / event history
   ↓
cooldown
   ↓
resume tiny monitor stream
```

The Pi still performs no semantic visual interpretation.

## Why YUV420?

Raspberry Pi's `rpicam-vid`/`libcamera-vid` can emit uncompressed YUV420.
The scene monitor reads only the Y (luminance) plane, so no image decoding
library or OpenCV is required.

## Run

Use your existing audio arguments and add `--auto-vision`:

```bash
python3 -m body_services.picar.main \
  --url https://jarvis-production-110e.up.railway.app \
  --token YOUR_TOKEN \
  --audio-input plughw:5,0 \
  --audio-output plughw:5,0 \
  --vad \
  --auto-vision
```

Expected startup:

```text
Automatic vision enabled: 160x120 @ 2.0 fps, threshold=12.0, cooldown=8.0s
```

When something changes materially:

```text
Scene change detected: score=...
Sending changed scene (...) to Jarvis Core...
Jarvis sees: ...
```

## Tuning

Too sensitive:

```text
--scene-threshold 18
```

Not sensitive enough:

```text
--scene-threshold 8
```

Longer cooldown after a visual interpretation:

```text
--scene-cooldown-seconds 15
```

Sampling rate:

```text
--scene-fps 1
```

The defaults are intentionally conservative starting points, not calibrated truths.

## Important behavioral boundary

A scene change is only a trigger. It does not mean "person detected."

```text
local Pi:
SOMETHING VISUALLY CHANGED

Core vision:
A person is now visible near the desk.

Core attention:
Does that semantic observation matter right now?
```

This preserves the project rule that interpretation defaults to Core.

## Still supported

The manual:

```text
see
```

command remains available for direct testing.

## Not included yet

- face/person identity recognition
- continuous multimodal inference
- visual tracking
- object persistence
- local neural object detection
- autonomous camera pan/tilt behavior
- visual semantic-memory consolidation
