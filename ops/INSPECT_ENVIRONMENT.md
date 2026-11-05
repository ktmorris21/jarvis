# Agent SDK: two-view visual environment inspection

**Flow:** Spoken request -> Core Agent SDK `inspect_environment(question)`
-> authenticated Core command bus -> `picar-voice` WebSocket
`capture_environment` -> camera pan -45/+45 degrees -> two JPEGs
-> transient command response -> Core Responses API vision model
-> textual findings returned to the Agent -> spoken answer.

The camera-only subprocess `clients/voice/head_expressions.py` owns the
servo. Captures use the pre-existing
`clients/voice/environment_camera.py` helper, including the installed
isolated libcamera 0.3 capture path, rpicam/libcamera CLI fallback, and
V4L2 fallback. Do not instantiate `Picarx` to control the head.

### Behavior

- Two views: left (-45°) and right (+45°), ~0.65s settling each.
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

With Jarvis stationary and the camera mechanically free to sweep ±45°:
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
