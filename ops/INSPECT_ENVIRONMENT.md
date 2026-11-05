# Agent SDK: two-view visual environment inspection

**Flow:** Spoken request -> Core Agent SDK `inspect_environment(question)`
-> authenticated Core command bus -> `picar-voice` WebSocket
`capture_environment` -> camera pan -25/+25 degrees -> two JPEGs
-> transient command response -> Core Responses API vision model
-> textual findings returned to the Agent -> spoken answer.

The camera-only subprocess `clients/voice/head_expressions.py` owns the
servo. Captures use the pre-existing
`clients/voice/environment_camera.py` helper, including the installed
isolated libcamera 0.3 capture path, rpicam/libcamera CLI fallback, and
V4L2 fallback. Do not instantiate `Picarx` to control the head.

### Behavior

- Two views: left (-25°) and right (+25°), ~0.65s settling each.
- Returns head to neutral even after a capture error.
- Does not turn, navigate, or arm/disarm the chassis.
- Image binaries are not retained by Core's event/memory storage.
- The tool returns only textual vision findings to the Agent conversation.
- No automatic sampling. One full capture per explicit inspection request.
- The model should not infer objects outside the camera coverage.
- The two photos require a separate Core vision-model request (API usage/cost).
- The inspection blocks the requesting Agent turn while capturing/interpreting;
  other robot navigation remains controlled by ROS.

### Deploy on Raspberry Pi

Ensure the new Railway Core commit has deployed, then:

```bash
cd ~/jarvis
git pull --ff-only
python3 -m py_compile clients/voice/environment_camera.py \
  clients/voice/head_expressions.py clients/voice/voice_interface.py
sudo systemctl restart jarvis-agents-voice.service
```

Verify that `jarvis-agents-voice.service` is the installed service name
(`systemctl list-units 'jarvis*voice*'`). The existing head controller
subprocess restarts with the voice service.

### Test

With Jarvis stationary and the camera mechanically free to sweep ±25°:
"Hey Jarvis, inspect your environment and tell me what you see."

Check logs:

```bash
journalctl -u jarvis-agents-voice.service -n 80 --no-pager \
  | grep -Ei 'VISION|capture|head|error'
```

The expected Pi log is `[VISION] Captured two camera views`; Railway
should log `[VOICE PROFILE] tool=inspect_environment` once the model
invokes it.

If a model request times out, check camera capture duration and the
configured Agent turn timeout. Vision analysis includes two photographs
sent as one model request and may take longer than standard voice replies.

### Timing instrumentation (two photos)

Each inspection generates a Core `command_id` printed as `trace=<id>`
in both the Pi and Railway logs. Each duration uses a local monotonic
clock; do not subtract raw Pi and Railway timestamps to measure transfer
latency because their wall clocks may differ.

On the Pi, look for `[VISION PROFILE]` entries for:
`setup` (camera backend), `pan_settle` for each view,
`camera_capture` for each view, `base64` for each view,
`head_reset`, `ws_json_encode`, and `ws_send`.

On Railway, `[VISION PROFILE]` includes:
`core_capture_start`, `core_command_dispatch`,
`capture_roundtrip` (Pi capture + transmission + Core receipt),
`images_received`, `validate_images`, `vision_api_start`,
`vision_api_response`, `vision_complete`,
`vision_processing`, and `capture_request_end`.
Preexisting `[VOICE PROFILE]` log entries cover LLM round trips,
`tool=inspect_environment`, full Agent duration, TTS, and speaker dispatch.

These measurements identify the main bottleneck without writing images
or user-visible image interpretations to the logs. Image sizes and output
text length are logged, but not contents.

Pi:

```bash
journalctl -u jarvis-agents-voice.service -f -o cat \
  | grep --line-buffered -E 'VISION PROFILE|VISION|VOICE PROFILE'
```

Railway logs: filter for `VISION PROFILE` and `VOICE PROFILE`.
Correlate the Pi/Core camera trace by `trace`, then compare LLM/TTS
stages from the same voice turn. Avoid changing camera backend or reducing
settle time until we have a baseline.
