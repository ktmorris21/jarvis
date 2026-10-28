# Jarvis Pi management tools

The shared Core ability registry advertises the same Pi management functions
to the Realtime voice model and the desktop Agents SDK.

## Architecture

`Agent or Realtime model -> Core execute_tool -> Core command bus ->
picar-control bridge on Pi -> fixed, allowlisted local operation ->
COMMAND_RESULT -> model`

`jarvis-control@shadowfax.service` runs independently of mapping and
Realtime. Stopping mapping will **not** remove the control link.

## First-time Pi installation

After merging and Railway has deployed the Core changes:

```bash
cd ~/jarvis
git pull --ff-only origin main

# Reuse the existing ROS bridge environment file containing JARVIS_URL
# and JARVIS_TOKEN; its permissions must restrict unauthorized readers.
sudo install -m 0644 ops/systemd/jarvis-control@.service \
  /etc/systemd/system/jarvis-control@.service
sudo systemctl daemon-reload
sudo systemctl enable --now jarvis-control@shadowfax.service
sudo systemctl status jarvis-control@shadowfax.service --no-pager
journalctl -u jarvis-control@shadowfax.service -n 40 --no-pager
```

The control bridge uses `/usr/bin/python3` (the same interpreter as the
ROS bridge), and needs the system-wide `websockets` Python package.

## Exact systemd permissions

Because the bridge runs as `shadowfax`, it must be granted *only*
the service operations it is allowed to perform. Edit a new sudoers file:

```bash
sudo visudo -f /etc/sudoers.d/jarvis-control
```

Insert (verify local binary paths with `command -v systemctl`):

```text
shadowfax ALL=(root) NOPASSWD: /usr/bin/systemctl start jarvis-mapping@shadowfax.service, /usr/bin/systemctl stop jarvis-mapping@shadowfax.service
```

Then verify that the permissions work without a password:

```bash
sudo -n -l -U shadowfax
```

**Do not add** unrestricted `systemctl`, arbitrary shell commands, or
`NOPASSWD: ALL`. The bridge always selects this fixed unit itself.

**Important:** start/stop controls the **entire ROS mapping stack**, which
contains the LiDAR driver. It is not an isolated laser motor toggle. Status
through `get_lidar_service` reports systemd state; `get_robot_status`
reports actual scan freshness.

## Audio configuration

The bridge uses ALSA mixer controls, not a synthetic software gain applied
to the Realtime PCM stream. The default commands are:

```bash
amixer -D default sget Speaker
amixer -D default sget Capture
```

Depending on the attached Jabra USB device, the available mixer controls may
have different names or may not support hardware volume/gain adjustments.
Discover them **on the Pi**:

```bash
amixer scontrols
aplay -l
arecord -l
```

Configure in `/etc/jarvis/bridge.env` as necessary:

```dotenv
JARVIS_ALSA_DEVICE=default
JARVIS_SPEAKER_CONTROL=Speaker
JARVIS_MIC_CONTROL=Capture
```

The bridge reports an explicit error if a control is missing. Do not invent
a successful result. If the USB audio hardware lacks ALSA mixer controls,
we should build a PipeWire or software PCM gain adapter instead.

## Optional remote reboot (disabled by default)

Reboot is disruptive and requires a second deliberate local setup step.
The service template sets `JARVIS_ALLOW_REMOTE_REBOOT=0`. It is therefore
unavailable after initial installation even if the model requests it.

To enable, create a `systemctl edit jarvis-control@shadowfax.service` drop-in:

```ini
[Service]
Environment=JARVIS_ALLOW_REMOTE_REBOOT=1
```

Then separately add this **exact** command to the above sudoers rule:

```text
/usr/bin/systemctl reboot
```

Run `sudo systemctl daemon-reload` and restart
`jarvis-control@shadowfax.service`. Jarvis must have an explicit
*reboot now* confirmation from the user before calling `reboot_pi` with
the fixed `REBOOT JARVIS NOW` phrase. The bridge returns before initiating
the reboot, after a three-second delay. This is model-mediated confirmation,
**not** a cryptographic or physical approval gate.

Do not enable remote reboot in an untrusted shared-voice environment. It
also does not imply any permission for shutdown, arbitrary scripts, updates,
or terminal access.

## Usage and smoke tests

- Voice: “Jarvis, what are your microphone and speaker levels?”
- Desktop: `say Set your speaker volume to 45 percent.`
- Voice: “Jarvis, is your mapping service running?”
- Desktop: `say Stop the mapping stack.`
- Desktop: `say Start the mapping stack.`
- Optional only after enabling: explicit request to reboot and confirm now.

If audio controls fail, inspect the control bridge log. If Core reports
`Target interface 'picar-control' is not connected`, check the Pi unit
and its token. The core and Pi must both be updated.

## Reboot recovery greeting

The existing Realtime voice service now announces **"Jarvis online and ready."**
the first time it starts successfully **after a physical Pi boot**.

- This announcement uses a separate short-lived Realtime speech session with
  the same `ash` voice as normal speech.
- There is **no** microphone input, function execution, transcript record,
  or follow-up listening window. After playback, the one-off session closes,
  and Jarvis returns directly to the local "Hey Jarvis" wake-word listener.
- The voice client compares the Linux kernel boot ID to a last-announced
  marker under `/tmp`. Restarting `jarvis-realtime.service` in the same
  physical boot will **not** repeat the announcement once it succeeded.
- On first installation the marker is absent, so it also announces once
  when the updated voice service starts, even without reboot.
- If the greeting cannot be produced (e.g. Core/API or audio unavailable),
  the error is logged and normal listening still starts. The marker is not
  recorded; a subsequent voice service restart retries the greeting.
- The notice confirms the **voice service is ready**, not that all ROS or
  LiDAR services are healthy. Later we can change the wording to summarize
  verified subsystem readiness.


## Timed driving (opt-in, supervised testing)

Core advertises `drive_timed(direction, duration_seconds)` with direction
`forward`, `backward`, `left`, or `right`. Left and right mean **driving
forward while steering**; the PiCar-X cannot rotate in place. Commands are
limited to 0.1–5 seconds, speed 20 (PiCar-X scale), steering ±25 degrees.
The local control bridge stops the motors in `finally` after every drive,
on cancellation, and after WebSocket disconnect. `stop_driving` cancels
an active drive independently of the waiting model command.

**Important:** This initial version has **no active LiDAR collision veto,**
no drop-off detection, no hardware watchdog, and no guaranteed instant
voice interruption: the wake-word client may not be listening while it
waits for a tool response. Keep the robot in direct sight, use a clear
floor and a readily accessible physical power stop. This is supervised
testing only, not autonomous driving.

Motion remains locally disabled unless explicitly enabled. First make
sure no other process owns the PiCar-X motor controller (including the
legacy `body_services.picar.main` process), then update the Pi:

```bash
cd ~/jarvis
git pull --ff-only origin main
sudo systemctl edit jarvis-control@shadowfax.service
```

Put this in the editor (use `sudo EDITOR=vim systemctl edit ...` to force vim):

```ini
[Service]
Environment=JARVIS_ENABLE_MOTION=1
```

Then apply and check:

```bash
sudo systemctl daemon-reload
sudo systemctl restart jarvis-control@shadowfax.service
sudo systemctl show jarvis-control@shadowfax.service -p Environment
journalctl -u jarvis-control@shadowfax.service -n 40 --no-pager
```

Test **with the drive wheels raised first**: say "Jarvis, forward one
second" and "Jarvis, right one second". Verify physically that the
right turn actually steers right; reverse the ±25 degree sign mapping
in `control_bridge.py` if servo calibration makes it opposite.

To disable again, remove the drop-in override for
`JARVIS_ENABLE_MOTION` and restart the unit. Default is disabled.

Current version executes one timed segment at a time. Compound requests
should be handled as consecutive separate model tool calls, not as a
pre-scheduled multi-segment queue. Emergency stop via speech still
depends on the voice client being able to listen and invoke the tool;
use physical power-off for an immediate stop.
