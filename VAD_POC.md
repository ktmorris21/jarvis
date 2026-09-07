# Jarvis VAD POC

This phase removes the manual `listen` command.

The Pi performs only cheap local audio-energy detection:

```text
USB mic
  ↓
arecord raw PCM
  ↓
local energy VAD
  ↓
speech starts
  ↓
capture utterance
  ↓
~750 ms silence
  ↓
WAV → existing Core audio endpoint
```

No speech recognition, wake word, LLM, or semantic interpretation runs on the Pi.

## Run

Use the same ALSA input/output device that worked in the manual audio test:

```bash
python3 -m body_services.picar.main \
  --url https://jarvis-production-110e.up.railway.app \
  --token YOUR_TOKEN \
  --audio-input plughw:2,0 \
  --audio-output plughw:2,0 \
  --vad
```

Startup performs ~1.5 seconds of ambient calibration. Be quiet during calibration.

Expected:

```text
Connected: ...
VAD calibrated: baseline RMS=..., threshold=...
Listening automatically. Speak near Jarvis...
```

When speech is detected:

```text
Speech detected: 2.31s (silence); sending to Core...
Heard: What time is it?
```

Jarvis should then answer through the USB speaker using the already-proven Core STT → attention → cognition → TTS path.

## Tuning

If background noise triggers it too easily, increase:

```text
--vad-threshold-multiplier 4.0
```

If normal speech does not trigger it, lower:

```text
--vad-threshold-multiplier 2.0
```

The absolute floor is:

```text
--vad-min-threshold 350
```

End-of-utterance silence defaults to 750 ms:

```text
--vad-end-silence-ms 750
```

Maximum utterance length defaults to 12 seconds.

## Important limitation

This is intentionally **voice activity**, not speaker intent. TV, another person, or Jarvis's own speaker may trigger capture. Conversation attention / wake behavior comes next and will decide whether detected speech deserves interpretation/action.

The ReSpeaker may later supply better hardware/DSP cues, but this interface remains useful as the fallback.
