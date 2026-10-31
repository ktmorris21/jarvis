# Jarvis Agent SDK chained voice — staged cutover

## Design

Local Pi: `Hey Jarvis` wake word + VAD capture, Jabra microphone/speaker.
Railway Core: `/audio/utterance` -> OpenAI `gpt-transcribe` -> existing
`agent_runtime.agent_reply` (persistent SQLAlchemy session, Core tools,
identity, memory) -> ElevenLabs Flash TTS -> existing `speaker` WebSocket
command. The Pi plays the exact Agent SDK response.

This does **not** use OpenAI Realtime for conversation. The model and speech
providers have separate responsibilities. It retains the old voice listener,
so no duplicate listener should be started on the same microphone.

Why ElevenLabs? OpenAI's standalone `/v1/audio/speech` TTS models are
scheduled for removal in January 2027; there is no currently documented
long-term standalone drop-in replacement. ElevenLabs' TTS API is independent
of that deprecation. No provider can promise that individual model IDs will
never change. The TTS provider boundary lives in `jarvis_core/audio.py`.

## Required Railway environment settings

* `OPENAI_API_KEY`: existing OpenAI credential.
* `JARVIS_STT_MODEL=gpt-transcribe`
* `JARVIS_AGENT_MODEL`: keep the current working Agent SDK model.
* `JARVIS_ELEVENLABS_API_KEY` (or `ELEVENLABS_API_KEY`): private ElevenLabs key.
* `JARVIS_TTS_VOICE`: the ElevenLabs voice ID selected by the user.
* `JARVIS_TTS_MODEL=eleven_flash_v2_5` (default).

Do not commit credentials. `JARVIS_TTS_VOICE` is required and intentionally
has no default: do not silently change Jarvis's character by selecting a
random synthetic voice.

## Deployment sequence (only AFTER Railway credentials are configured)

1. Merge this branch and deploy Core on Railway. The old Realtime listener
   continues to work independently.
2. On the Pi, run:

```bash
cd /home/shadowfax/jarvis
git pull --ff-only
sudo install -m 0644 deploy/systemd/jarvis-agents-voice.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl disable --now jarvis-realtime.service
sudo systemctl disable --now jarvis-voice.service 2>/dev/null || true
sudo systemctl enable --now jarvis-agents-voice.service
journalctl -u jarvis-agents-voice.service -f
```

3. Say "Hey Jarvis, what's your LiDAR status?" and watch Core's STT/TTS
   timing logs. Confirm speaker output and tool execution. Test multiple turns.
4. Roll back voice immediately if needed:

```bash
sudo systemctl disable --now jarvis-agents-voice.service
sudo systemctl enable --now jarvis-realtime.service
```

## Known limitations

* This is the **initial functional cutover**, not a low-latency streaming
  implementation. TTS generation finishes before the existing `speaker`
  command starts playback. Latency will likely be longer than Realtime.
* Follow-up without another wake word, local cached acknowledgement clips,
  streamed TTS playback, and interruptions can be layered on afterward.
* Existing boot greeting belongs to the Realtime client and is not part of
  this staged listener. It can be added locally without using deprecated TTS.
* When synthesis fails, Core logs an explicit error rather than sending an
  unplayable speaker command.
* Test the chosen voice, pronunciation, audio levels and ElevenLabs account
  rate limits before treating this as production ready.
