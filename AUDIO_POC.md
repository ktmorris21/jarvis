# Jarvis Audio POC — USB conference speaker/mic

This phase proves one spoken round trip without always-listening, VAD, wake words, or streaming audio.

## Core path

Pi records 5 seconds with ALSA -> POST raw WAV to Core -> OpenAI transcription -> `USER_SPOKE` -> attention -> cognition -> OpenAI TTS -> targeted `speaker` command -> Pi plays WAV with ALSA.

The Pi performs no speech recognition, TTS, or LLM reasoning.

## Railway

Deploy this version over the current attention build. Existing PostgreSQL is unchanged.

Keep `OPENAI_API_KEY` and add/accept defaults:

```text
JARVIS_STT_MODEL=gpt-4o-mini-transcribe
JARVIS_TTS_MODEL=gpt-4o-mini-tts
JARVIS_TTS_VOICE=alloy
```

`GET /health` should report `v1-audio-poc`.

## Pi

Use the ALSA device identifiers that already worked in your manual test.

Example:

```bash
python3 -m body_services.picar.main   --url https://jarvis-production-110e.up.railway.app   --token YOUR_TOKEN   --audio-input plughw:2,0   --audio-output plughw:2,0   --record-seconds 5
```

At the prompt:

```text
> listen
```

Speak during the five-second recording. The Pi should print the transcription, then Jarvis should answer through the USB conference speaker.

If your card/device was not `2,0`, substitute the exact working values from your `arecord`/`aplay` test.

## Deliberately not included yet

- continuous capture
- VAD
- wake word
- echo cancellation
- interruption/barge-in
- streaming speech
- ReSpeaker-specific features

Those come only after this round trip is reliable.
