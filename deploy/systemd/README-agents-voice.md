# Jarvis chained voice with local Piper — staged migration

## Architecture
Pi: local Hey Jarvis wake-word, microphone capture, Piper TTS, Jabra speaker.
Railway: OpenAI gpt-transcribe -> existing Agents SDK conversation with identity,
memory, tools and SQLAlchemy session -> text command to Pi. Piper speaks the
Agent SDK's exact text. No ElevenLabs account or cloud TTS required.

## Install on Shadowfax (64-bit Ubuntu 24.04)

Prepare a local Piper installation in the existing voice virtual environment:

```bash
cd ~/jarvis
.venv-voice/bin/python -m pip install 'piper-tts>=1.8,<2'
mkdir -p voices
.venv-voice/bin/python -m piper.download_voices --data-dir voices en_GB-alan-medium
printf 'LiDAR is online.\n' | .venv-voice/bin/piper \
  --model "$HOME/jarvis/voices/en_GB-alan-medium.onnx" \
  --output_file /tmp/jarvis-piper-test.wav
aplay -D plughw:CARD=J710,DEV=0 /tmp/jarvis-piper-test.wav
```

The first suggested voice is the British English Alan medium voice. Compare
alternatives later. Check the model's licensing documentation before distribution.
The Piper model requires both the .onnx file and its .onnx.json companion.

Configure any nonstandard binary/model using JARVIS_PIPER_BIN and
JARVIS_PIPER_VOICE in /etc/jarvis/voice.env.

## Core prerequisites
Deploy the branch to Railway with OPENAI_API_KEY and
JARVIS_STT_MODEL=gpt-transcribe. Keep existing JARVIS_AGENT_MODEL and database
settings unchanged. There is no TTS provider configuration on Railway.

## Cut over only after confirming local Piper playback and deployed Core

```bash
cd ~/jarvis
git pull --ff-only
sudo install -m 0644 deploy/systemd/jarvis-agents-voice.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl disable --now jarvis-realtime.service
sudo systemctl disable --now jarvis-voice.service 2>/dev/null || true
sudo systemctl enable --now jarvis-agents-voice.service
journalctl -u jarvis-agents-voice.service -f
```

Rollback:
```bash
sudo systemctl disable --now jarvis-agents-voice.service
sudo systemctl enable --now jarvis-realtime.service
```

## Current behavior and next optimization

The staged listener synthesizes the complete Agent SDK answer in Piper before
playback. That is functional but not yet first-sentence streaming. We should
implement and test streamed text transport from Runner.run_streamed() to the Pi,
a sentence playback queue, and a final-turn marker before using streaming
in production. Do not mistake token deltas from a tool-call intermediate turn
for a final user-facing answer. Preserve the session lock and reliable completion.

Known follow-ups: immediate locally cached wake acknowledgement; wake-free
follow-ups; interruption, TTS preloading, first-sentence latency instrumentation;
Realtime and chained listener must never
own the microphone simultaneously.

## Once-per-boot voice readiness announcement

The Agents voice client restores the previous Realtime greeting **"Jarvis online
and ready."**. After its local wake-word model and head controller are
initialized, and before the first microphone capture, it plays this greeting
locally via the cached WAV, without any Core or Agent request. This indicates
**voice readiness**, not a health check of mapping, LiDAR or navigation.

The existing `clients/voice/boot_notice.py` compares the Linux kernel boot ID
to a marker in `/tmp`, shared with the old Realtime service. A voice service
restart during the same boot does not repeat the announcement; a physical
reboot does. The marker is written only after successful playback. A playback
failure is logged and does not prevent the wake listener from starting.

Deployment on the Pi:

```bash
cd ~/jarvis
git pull --ff-only
.venv-voice/bin/python clients/voice/local_audio.py generate
python3 -m py_compile clients/voice/voice_interface.py clients/voice/local_audio.py
sudo systemctl restart jarvis-agents-voice.service
journalctl -u jarvis-agents-voice.service -n 30 --no-pager
```

The restart will play the greeting if it has not previously been announced
this physical boot, otherwise logs `[BOOT] Readiness announcement already played
this boot`. On a subsequent Pi reboot the greeting should play automatically.
No need to restart the drive/mapping services solely for this update.
