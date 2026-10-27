# PiCar-X Realtime voice boot service

This service runs the existing `clients/voice/realtime_conversation.py` continuously
on the Pi. It listens locally for **Hey Jarvis**, requests short-lived OpenAI
Realtime credentials from Railway Core, and streams conversation audio directly
to OpenAI. When the conversation ends, it resumes local wake-word listening.

## One-time migration on the Pi

These commands assume the existing install is `/home/shadowfax/jarvis`,
the working Realtime virtualenv is `.venv-voice`, and Core authentication is
already in `/etc/jarvis/voice.env`.

```bash
cd ~/jarvis
git pull --ff-only

# Stop manual Realtime testing first (Ctrl-C in that terminal).
sudo systemctl disable --now jarvis-voice.service
sudo install -m 0644 deploy/systemd/jarvis-realtime.service /etc/systemd/system/jarvis-realtime.service
sudo systemctl daemon-reload
sudo systemctl enable --now jarvis-realtime.service

systemctl status jarvis-realtime.service --no-pager
journalctl -u jarvis-realtime.service -n 60 --no-pager
```

The service starts at boot and automatically restarts if the client exits with an
error. It uses `/etc/jarvis/voice.env` for `JARVIS_INTERFACE_TOKEN`, so there
must be no interactive token prompt under systemd. No permanent OpenAI API key is
needed on the Pi. Make sure the env file defines `JARVIS_INTERFACE_TOKEN` and
that Railway Core is available before testing.

To follow live logs:

```bash
sudo journalctl -u jarvis-realtime.service -f
```

Verify the unit is enabled, the old unit is disabled, and only one listener
is running:

```bash
systemctl is-enabled jarvis-realtime.service
systemctl is-enabled jarvis-voice.service
systemctl is-active jarvis-realtime.service
```

## Returning to the legacy voice service

```bash
sudo systemctl disable --now jarvis-realtime.service
sudo systemctl enable --now jarvis-voice.service
```

To return to Realtime again:

```bash
sudo systemctl disable --now jarvis-voice.service
sudo systemctl enable --now jarvis-realtime.service
```

Both services share the physical audio device. Do not run them simultaneously,
including an additional manually launched Realtime client.

## Changing the unit

When editing the tracked unit file in GitHub, subsequent `git pull` operations
do not automatically update the installed copy. Reinstall and reload it:

```bash
sudo install -m 0644 deploy/systemd/jarvis-realtime.service /etc/systemd/system/jarvis-realtime.service
sudo systemctl daemon-reload
sudo systemctl restart jarvis-realtime.service
```

Edits to Core-hosted `jarvis_identity.md` and `jarvis_voice.md` are loaded at
the beginning of each new Realtime session after Railway deploys. Those do
not require a service restart.
