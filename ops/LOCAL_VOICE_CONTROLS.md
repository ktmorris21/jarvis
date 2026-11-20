# Jarvis Pi-local voice commands (Agents voice)

Pi voice service: `jarvis-agents-voice.service`, running `clients/voice/voice_interface.py`.
After local "Hey Jarvis" wake-word capture, `local_commands.py` transcribes the WAV
with **offline Vosk** and accepts only full-utterance exact commands. Unmatched audio
goes unchanged to Railway/Core when connected. Local listener stays live if Core
WebSocket is disconnected. No model/Agent can issue these local actions.

## Commands

| Initial spoken utterance | Response | Required next utterance |
| --- | --- | --- |
| "Hey Jarvis, stop" | Cancels Nav2 movement goals locally, without disarming | none |
| "Hey Jarvis, arm motors" | "Say confirm arm motors" | "Hey Jarvis, confirm arm motors" |
| "Hey Jarvis, disarm motors" | disarms immediately | none |
| "Hey Jarvis, reboot" | "Say confirm reboot" | "Hey Jarvis, confirm reboot" |
| "Hey Jarvis, power down" | "Say confirm power down" | "Hey Jarvis, confirm power down" |
| "Hey Jarvis, upload diagnostics" | Uploads a bounded snapshot to Railway logs | none |
| "Hey Jarvis, update Jarvis" | "Say confirm update Jarvis" | "Hey Jarvis, confirm update Jarvis" |

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

## Vosk repeated-stop recognition fix

Moving-goal diagnostics confirmed Vosk produced `stop hey jarvis` and
`stop stop`, neither of which matched the original strict one-phrase table.
The local stop matching now accepts those limited forms (and a repeated
`stop` or trailing `jarvis` after `stop moving`/`stop movement`). It
continues to reject unrelated instructions or negated stop requests;
arming, disarming, and power commands retain exact matching.

The persistent ROS client and Nav2 cancellation code are unchanged. Deploy
the recognition update with the voice service only, **motors disarmed**:

```bash
cd ~/jarvis
git status --short
git pull --ff-only
python3 -m unittest discover -s tests -p 'test_voice_management.py'
python3 -m unittest discover -s tests -p 'test_ros_stop_client.py'
sudo systemctl restart jarvis-agents-voice.service
```

On the next stop test, the voice journal should record both a grammar
transcript and `[LOCAL STOP] dispatching ROS stop`. Try the stationary
disarmed test before attempting supervised moving navigation.

## Persistent stop client rollout (November 2026)

When voice `stop` was tested during active navigation, Vosk recognized
`stop` but the former one-shot `ros2 service call` timed out after eight
seconds without reaching the Nav2 service. Stationary tests had succeeded.
The per-command CLI startup/discovery has now been replaced by two small
Pi-side modules: `clients/voice/ros_stop_client.py` (async voice IPC owner)
and `clients/voice/ros_stop_worker.py` (persistent rclpy Trigger client).
The robot's cancel-all-goals and motor-inhibit services are unchanged.

With Jarvis parked and **disarmed**:

```bash
cd ~/jarvis
git status --short
git pull --ff-only
python3 -m unittest discover -s tests -p 'test_ros_stop_client.py'
python3 -m unittest discover -s tests -p 'test_voice_management.py'
python3 -m unittest discover -s tests -p 'test_diagnostics.py'
python3 -m py_compile clients/voice/ros_stop_client.py clients/voice/ros_stop_worker.py clients/voice/local_commands.py clients/voice/voice_interface.py
sudo systemctl restart jarvis-agents-voice.service
journalctl -u jarvis-agents-voice.service -n 40 --no-pager
```

Look for `[LOCAL STOP] persistent ROS client ready`. If unavailable,
verify ROS startup and `/jarvis/motion/stop` service availability. No
Nav2/drive service restart is required. Test "Hey Jarvis", wait for
"I'm here", then "Stop" **while disarmed**, followed by diagnostics upload.
An active-goal test may follow only under normal supervision with the physical
motor cutoff accessible. The new timing measures service dispatch/response
after recognition, not the wake-word and speech-capture interval.

## Pi-local stop of active ROS goals

Say "Hey Jarvis", wait for the local "I'm here" reply, then say "Stop".
The exact utterances "stop moving" and "stop movement" are also recognized
locally by Vosk. No Core connectivity or LLM call is required.

The voice process uses a **persistent, prewarmed ROS Trigger client** to call
`/jarvis/motion/stop`, provided by the Nav2 frontier detector. The voice
virtualenv launches a single `/usr/bin/python3` ROS helper on startup after
sourcing Jazzy and the workspace. Subsequent stop commands reuse the same
client; they do not launch `ros2 service call` or wait for fresh ROS discovery.
The helper does not accept arbitrary commands, and never arms motors.
If the helper becomes unavailable, the voice command fails locally (and does
not silently go to Core); a subsequent stop can try restarting it.
The service reply is bounded to about 3 seconds once the client is warm.

The diagnostics upload records `[LOCAL STOP] persistent ROS client ready`,
`[LOCAL STOP] dispatching ROS stop`, and acknowledgement timing in
milliseconds. An unsuccessful request logs the error and retains the physical
cutoff fallback. It halts frontier exploration, requests cancellation
of all goals on /navigate_to_pose, /follow_path, and /compute_path_to_pose,
and requests the drive controller's /jarvis_drive/stop_goal service.
These affect active Nav2 goals, regardless of whether their client was Core,
an RViz goal, or the exploration manager. The motor armed state remains unchanged.

The drive controller stops motor output at once on receipt of its local stop
request, and inhibits subsequent nonzero /cmd_vel messages until at least one second has passed without nonzero velocity commands.
If Nav2 keeps sending nonzero commands, the inhibit remains active. The stop reply "Stop requested."
means the ROS stop request was dispatched, NOT that all cancellation results
have arrived. Journals include VOICE_STOP_REQUESTED, VOICE_STOP_DRIVE_ACK,
and VOICE_STOP_CANCEL_RESULT.

This is not an emergency-stop mechanism. The wake word, "I'm here"
acknowledgment, Vosk processing, ROS service calls, or an ongoing spoken reply
can delay recognition. Keep the physical motor cutoff accessible.

### Installation

Park and disarm first. Check git status before pulling.

```bash
cd ~/jarvis
git status --short
git pull --ff-only
python3 -m py_compile clients/voice/local_commands.py ops/nav2/frontier_detector.py body_services/picar/ros_drive_controller.py
python3 -m unittest discover -s tests -p 'test_voice_management.py'
sudo systemctl restart jarvis-drive@shadowfax.service
sudo systemctl restart jarvis-nav2.service
sudo systemctl restart jarvis-agents-voice.service
```

Core also needs the updated local-audio phrase allowlist deployed to Railway.
Once live, synchronize the new two audio clips with the existing service:

```bash
sudo systemctl start jarvis-local-audio-sync.service
sudo journalctl -u jarvis-local-audio-sync.service -n 40 --no-pager
```

A missing WAV clip prevents the audible confirmation, but not execution of
the ROS stop command. First test with motors disarmed:

```bash
ros2 service call /jarvis/motion/stop std_srvs/srv/Trigger '{}'
journalctl -u jarvis-nav2.service -n 70 --no-pager | grep VOICE_STOP
journalctl -u jarvis-drive@shadowfax.service -n 40 --no-pager
```

Then try the spoken command while stationary. Only after validating service
health and cancellation logs should you test stopping a supervised short motion.
The drive service restart disarms the motors as usual; the stop command itself
does not.

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

## Operator-triggered diagnostic upload (new)

"Hey Jarvis, upload diagnostics" runs **locally** using the existing offline
Vosk path, with no Agents SDK tool invocation. The voice WebSocket sends one
`PI_DIAGNOSTIC_UPLOAD` event to Core. Railway logs receive `[PI DIAG] START`,
section lines, and `[PI DIAG] END`, all sharing a 12-character report ID.
The report contains a short Git revision, uptime, memory and disk use, and
the recent journal/status of Nav2, mapping, drive and ROS bridge. The voice
client deliberately excludes voice logs, environment variables and arbitrary
files. Diagnostics are not saved into Jarvis memory or its conversational
context. The spoken reply confirms that the client sent the report; it
does **not** prove Railway has persisted the lines. Check Railway logs by
`[PI DIAG]` and report ID.

**Important:** Journal content can contain sensitive information even with
best-effort redaction; restrict Railway log access. The upload requires an
active Core WebSocket; without it Jarvis says the upload failed. This is
intended for supervised, occasional troubleshooting, not continuous telemetry.

### Diagnosing an ineffective voice stop

After using "Hey Jarvis" / "I'm here" / "Stop", request **Upload diagnostics**.
The report now includes `journal:voice_stop` (wake acknowledgment,
local stop recognition, stop request failures) and `journal:ros_stop`
(the Nav2 stop service and drive inhibit outcomes). It does **not** upload
ordinary speech transcripts or microphone audio.

A stationary test is preferable first: leave the motors **disarmed**, say
"Hey Jarvis", wait for "I'm here", say "Stop", then request "Upload
diagnostics". If the local ROS stop command is functioning, the Nav2
journal should log `VOICE_STOP_REQUESTED`, and the drive journal should
record the stop inhibit. Only repeat an armed moving-goal test under
supervision after that stationary confirmation. A voice command is not an
emergency-stop substitute.

```bash
cd ~/jarvis
git status --short
git pull --ff-only
python3 -m unittest discover -s tests -p 'test_diagnostics.py'
sudo systemctl restart jarvis-agents-voice.service
```

### Navigation-failure context (new)

Diagnostics now find up to **two recent failed navigation goals** in the last
30 minutes, including `nav_goal_aborted` and `RELATIVE_MOTION_ABORT` events.
Each failure gets its own `nav_failure_context:1` / `:2` section, containing
the goal event and selected Nav2 planner, controller, action, and
behavior-tree log messages from **six seconds before to three seconds after**
the failure. This is a timestamp-based correlation, not proof that every
nearby planner warning belongs to the same goal. Repeated frontier previews
may run in the same interval, so interpret their warnings carefully.

The capture runs **only when "upload diagnostics" is requested**; it adds no
persistent recorder, extra ROS process, or autonomous retry. Each section is
bounded to 2,200 characters, and the overall report is bounded as before.
If the goal event has aged out of the 30-minute window or its journal has
rotated, the surrounding context cannot be recovered.

**Pi-only deployment** (no Railway, Nav2, or drive changes):

```bash
cd ~/jarvis
git status --short
git pull --ff-only
python3 -m unittest discover -s tests -p 'test_diagnostics.py'
python3 -m py_compile clients/voice/diagnostics.py
sudo systemctl restart jarvis-agents-voice.service
```

For a diagnostic test, with the robot disarmed, attempt a regular **plan-only**
or supervised coordinate goal as appropriate. After an observed abort, say
"Hey Jarvis", wait for "I'm here", then "Upload diagnostics". The Railway
report should contain `nav_failure_context:1` along with the usual
`journal:nav_goal_failures` section. No need to induce an actual physical
collision for diagnosis.

### Warning-focused diagnostic history

The diagnostics upload now searches the preceding **30 minutes** of each
service's journal, matching ROS `[WARN]`/`[ERROR]` text, warnings, failures,
exceptions, and navigation/controller issues rather than copying just the
last 18 messages. This is important because ROS log messages often have an
informational journald priority even when their text indicates an error.

A separate `journal:nav_goal_failures` section searches bridge events
including `nav_goal_aborted`, `nav_goal_canceled`, relative-motion aborts,
and unsuccessful stop cancellation. It prevents frequent LiDAR/TF warnings
from evicting the goal failures being investigated. The existing total report
and individual section bounds, redaction, and Railway-only (no memory)
handling are unchanged. Matches are bounded to the most recent entries;
very large warning bursts can still cause older events to be omitted.

**Pi-only deployment** (Core does not need changes):

```bash
cd ~/jarvis
git status --short
git pull --ff-only
python3 -m unittest discover -s tests -p 'test_diagnostics.py'
python3 -m py_compile clients/voice/diagnostics.py
sudo systemctl restart jarvis-agents-voice.service
```

After restart, say "Hey Jarvis", wait for "I'm here", then "Upload
diagnostics". Search Railway logs for the report ID and
`journal:nav_goal_failures`. The voice-service restart does not change
motor arming or restart Nav2.

## Operator-confirmed update (new)

"Hey Jarvis, update Jarvis" prompts "Say confirm update Jarvis." A second
utterance within 20 seconds launches a fixed, separate systemd oneshot unit.
It refuses to update if the repository is dirty, not on `main`, or
diverged from `origin/main`. It runs `git fetch origin main` and a
fast-forward-only merge, then restarts ONLY
`jarvis-bridge@shadowfax.service` and `jarvis-agents-voice.service`.
This intentionally does **not** restart Nav2, mapping, or drive; those
changes still require supervised manual rollout. The spoken "Starting update"
is an acknowledgement of the requested job, **not** proof of success.
Review `journalctl -u jarvis-voice-update.service` or
`~/jarvis-update.log` if using an earlier helper.

Voice commands are not authentication and may be replayed by nearby speakers.
Keep the robot parked, motors disarmed, and physical cutoff available before
using the update command. Do not enable these commands in a shared or
untrusted acoustic environment.

### One-time Pi setup

After Railway has deployed the new Core receiver, on the Pi (while parked):

```bash
cd ~/jarvis
git status --short
git pull --ff-only
sudo install -m 0644 ops/systemd/jarvis-voice-update.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo EDITOR=vim visudo -f /etc/sudoers.d/jarvis-voice-update
```

Insert precisely these rules (adapt paths/user only after checking them):

```text
shadowfax ALL=(root) NOPASSWD: /usr/bin/systemctl --no-block start jarvis-voice-update.service
shadowfax ALL=(root) NOPASSWD: /usr/bin/systemctl restart jarvis-bridge@shadowfax.service
shadowfax ALL=(root) NOPASSWD: /usr/bin/systemctl restart jarvis-agents-voice.service
```

Then validate syntax and permissions and regenerate cached phrases before
restarting the voice service:

```bash
sudo visudo -c
sudo -n -l -U shadowfax
python3 -m py_compile clients/voice/local_commands.py clients/voice/diagnostics.py clients/voice/voice_interface.py
.venv-voice/bin/python clients/voice/local_audio.py generate
sudo systemctl restart jarvis-agents-voice.service
```

For the initial test, first say "upload diagnostics" and check Railway for
the report ID. Then check `git status --short`, keep Jarvis stationary,
speak "update Jarvis", and intentionally do **not** confirm on the first
attempt. After the confirmation expires, perform the full command while
observing `journalctl -fu jarvis-voice-update.service`. An already-current
repository reports "Already up to date" without restarting any services.

**Limitations:** The updater does not install Python dependencies, apply
systemd unit changes, modify ROS configuration or automatically roll back.
A failed Git pull leaves the running stack alone; a failure during service
restart requires manual attention. This is a narrowly bounded first sprint.

## Core-matched offline voice clips and wake acknowledgment

The Pi voice listener retains the **existing head listening animation**. After
detecting "Hey Jarvis", it pauses microphone capture, plays the locally cached
**"I'm here."** recording, and only then opens a **fresh microphone capture**
for the user command. Say **"Hey Jarvis"**, wait for **"I'm here"**, then give
the command. Same-breath "Hey Jarvis, upload diagnostics" is no longer
reliably captured because the acknowledgment plays before command capture.
If nothing is said within 5 seconds after the acknowledgment, it returns to
wake-word listening without calling Core. Ordinary follow-up conversation
still uses the existing wake-free follow-up window.

The fixed phrases are created using the **currently selected Core ElevenLabs
voice**, then stored locally as WAV files. No network or LLM is required to
speak any installed phrase. In particular, diagnostics say only
"Diagnostics uploaded." rather than reading the report ID; the ID remains
in Core's Railway logs. The offline command recognizer remains Vosk and
confirmation commands are unchanged even though prompts are shorter.

The audio sync is **manual and only needed after changing the Core voice or
adding a new phrase**. It fetches a strictly allowlisted list and validates all
WAV responses before atomically replacing individual cache files. It refuses
to run unless Core's configured speech provider is ElevenLabs. If Core has
been switched back to Piper, do not run sync until the intended voice is
configured. The local audio cache isn't automatically overwritten on boot.

### Deployment sequence

1. Deploy the updated Core to Railway (the authenticated
   `/local-audio/manifest` and `/local-audio/render` endpoints must be live).
2. Park and disarm the robot. On the Pi, check for uncommitted modifications,
   then pull from GitHub:

```bash
cd ~/jarvis
git status --short
git pull --ff-only
sudo install -m 0644 ops/systemd/jarvis-local-audio-sync.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start jarvis-local-audio-sync.service
sudo journalctl -u jarvis-local-audio-sync.service -n 40 --no-pager
cat ~/jarvis/cache/local_voice/manifest.json
```

3. Check the manifest provider, voice ID and model against Core. Only after
   a successful sync, restart **voice only**:

```bash
python3 -m py_compile clients/voice/local_audio.py clients/voice/voice_interface.py clients/voice/local_commands.py
sudo systemctl restart jarvis-agents-voice.service
sudo journalctl -u jarvis-agents-voice.service -n 40 --no-pager
```

4. Say "Hey Jarvis", listen for "I'm here", and then say "upload diagnostics".
   Expect "Diagnostics uploaded." and a new Railway report. Next test
   "update Jarvis" **without confirming**, verifying the shortened
   confirmation prompt. Do not test motor arming as part of voice validation.

**Audio fallback policy:** fixed local responses never launch Piper, including
at wake. If "I'm here" is missing, the service logs the failure and still
listens; for destructive actions, a failed acknowledgment blocks execution
as before. If a required phrase isn't cached, repeat the audio sync instead
of changing the speech provider. Voice selection and API costs are incurred
only during explicit sync, not per local command.
