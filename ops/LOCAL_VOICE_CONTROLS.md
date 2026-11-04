# Jarvis Pi-local voice commands (Agents voice)

Pi voice service: `jarvis-agents-voice.service`, running `clients/voice/voice_interface.py`.
After local "Hey Jarvis" wake-word capture, `local_commands.py` transcribes the WAV
with **offline Vosk** and accepts only full-utterance exact commands. Unmatched audio
goes unchanged to Railway/Core when connected. Local listener stays live if Core
WebSocket is disconnected. No model/Agent can issue these local actions.

## Commands

| Initial spoken utterance | Response | Required next utterance |
| --- | --- | --- |
| "Hey Jarvis, arm motors" | "Say confirm arm motors" | "Hey Jarvis, confirm arm motors" |
| "Hey Jarvis, disarm motors" | disarms immediately | none |
| "Hey Jarvis, reboot" | "Say confirm reboot" | "Hey Jarvis, confirm reboot" |
| "Hey Jarvis, power down" | "Say confirm power down" | "Hey Jarvis, confirm power down" |

Confirmation expires after **20 seconds**; each separate utterance requires the
wake word. Reboot and power down run after the local Piper spoken acknowledgement.
Voice is **not an authentication factor**; any speaker close enough could issue
or replay matching phrases. Keep independent physical motor cutoff accessible.

## Pi installation

Do not overwrite uncommitted Pi-local modifications; check git status first.

```bash
cd ~/jarvis
git status --short
git pull --ff-only
python3 -m py_compile clients/voice/local_commands.py clients/voice/voice_interface.py body_services/picar/ros_drive_controller.py
.venv-voice/bin/python -m pip install vosk
mkdir -p models
cd models
curl -fL -o vosk-model-small-en-us-0.15.zip https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
unzip -q vosk-model-small-en-us-0.15.zip
rm vosk-model-small-en-us-0.15.zip
cd ~/jarvis
```

The 40MB model is documented at https://alphacephei.com/vosk/models .
Its runtime memory usage is significantly larger than its download size.
Override location with `JARVIS_VOSK_MODEL` in `/etc/jarvis/voice.env` if needed.
If missing, the voice service logs that local recognition is unavailable and
continues sending ordinary utterances to Core; local commands won't work.

### Restricted Pi power permissions

The existing Pi control bridge has its own permission for reboot. The **voice**
service runs as `shadowfax` and needs explicit noninteractive permissions for
both operations. Create using Vim:

```bash
sudo EDITOR=vim visudo -f /etc/sudoers.d/jarvis-local-power
```

Insert exactly, assuming `command -v systemctl` is `/usr/bin/systemctl`:

```text
shadowfax ALL=(root) NOPASSWD: /usr/bin/systemctl reboot, /usr/bin/systemctl poweroff
```

Check rules without executing either operation:

```bash
sudo -n -l -U shadowfax
```

**Do not** grant unrestricted root shell, arbitrary systemctl commands, or
passwordless general sudo.

### Restart to install changes

```bash
sudo systemctl restart jarvis-drive@shadowfax.service
sudo systemctl restart jarvis-agents-voice.service
journalctl -u jarvis-drive@shadowfax.service -n 15 --no-pager
journalctl -u jarvis-agents-voice.service -n 30 --no-pager
```

Look for `HARDWARE AVAILABLE, DISARMED` on the drive service and
`[LOCAL] Offline Vosk command recognition enabled` on the voice service.

## Drive arming semantics

Drive service starts disarmed on every boot/restart. Explicit local voice
arming uses the existing ROS `/jarvis_drive/set_armed` SetBool service;
ordinary zero /cmd_vel messages and the 0.5-second command watchdog **stop
the motors but no longer disarm**. Invalid commands, hardware faults, manual
disarm and drive process restart still disarm. Hardware mode still requires
the existing operator-enabled systemd configuration.

Validate first with wheels elevated. Check ordinary zero commands no longer
disarm, then test "disarm motors." Finally test stationary/no-command watchdog
behavior and ensure the physical stop works independently. Do not initially
test reboot or shutdown while motion is possible.

## Limitations

- Voice command recognition is strict and intentionally not conversational.
  The local model may mishear speech; if an initial command is not recognized,
  the audio is forwarded to Core when connected.
- This is *not* an emergency-stop mechanism; local speech and speech synthesis
  introduce latency and are not reliable if the voice process is unresponsive.
- Pending confirmations are in memory and vanish when the voice service restarts.
- A drive-controller restart clears arming independently of the voice process.
- The PiCar-X hardware library's existing motor PWM mapping is unchanged.
- The current mapping/Nav2 stack does not yet implement dual-LiDAR collision
  prevention or an independent physical E-stop.

## Cached local speech responses

Local Pi-control replies now use pre-rendered WAV audio files to avoid launching
Piper and reloading the speech model after every voice command. The ordinary
Agent responses still use the existing pipeline. The cache is stored at
`~/jarvis/cache/local_voice/` by default and is ignored by Git because its
files are WAV audio. Do not commit generated audio files.

After pulling the new code onto the Pi, generate the responses **once** using
the same voice environment used by the running service:

```bash
cd ~/jarvis
.venv-voice/bin/python clients/voice/local_audio.py generate
```

The generator reads `JARVIS_PIPER_VOICE` and `JARVIS_PIPER_BIN` if set; by
default it uses the existing Alan medium voice and `.venv-voice/bin/piper`.
If you have customized either variable in `/etc/jarvis/voice.env`, provide
those same values when running the generator. If you later change Piper voices,
regenerate the cache.

Then validate and restart **voice only** (drive does not need a restart):

```bash
python3 -m py_compile clients/voice/local_audio.py clients/voice/voice_interface.py
sudo systemctl restart jarvis-agents-voice.service
journalctl -u jarvis-agents-voice.service -f
```

As a safe test, say "Hey Jarvis, arm motors" but **do not confirm**.
Expect a quick "Say confirm arm motors." and a log line similar to:

```text
[LOCAL AUDIO] Cache hit: 'Say confirm arm motors.'
```

The prompt will expire after 20 seconds and motors remain disarmed.
If the cached file is absent, corrupt, or cannot be played, the client logs a
cache miss/playback failure and falls back to the normal Piper response. For
power commands, the existing rule remains: the actual reboot/shutdown is not
issued unless acknowledgement audio playback succeeds.

Piper generation is deliberately an explicit setup operation instead of a
boot-time activity, so service startup stays predictable and there is no
per-utterance synthesis cost on cache hits.
