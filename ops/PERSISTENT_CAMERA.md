# Persistent low-rate camera worker (Pi 4, isolated libcamera 0.3)

This is an **opt-in Pi service**; the existing two-photo camera capture remains
the default whenever the worker socket does not exist. No Railway deployment is
required: Core still receives the same two JPEGs at -25°/+25° and analyzes them
as before.

## Architecture

- `jarvis-camera.service`: a Python server on a protected Unix socket at
  `/run/jarvis-camera/camera.sock`, with OpenCV JPEG encoding and health
  reporting.
- `camera_native.cpp`: native, long-lived libcamera 0.3 application compiled
  *against the existing isolated source/build*. It holds one camera session
  open and requests a frame every 2 seconds by default, without writing
  background images to storage.
- A voice inspection still owns the head servo (one controller), moves to
  -25° and +25°, waits 650 ms each, then requests a **new frame** after each
  servo move. Frame encoding is performed by the worker and returned in memory.
- No image history, disk cache, automatic analysis, or extra LLM requests.
  Temporary raw frames for explicit capture are unlinked immediately.
- Worker startup failures leave the original isolated-libcamera capture path
  available because no socket is published. If the service is running but a
  capture fails, the error is reported rather than opening the same camera
  through a second process.
- The background frames are discarded after acquisition; CPU and sensor
  activity are **not zero** at idle. The driver may also stream internally
  while the camera is started. Measure actual Pi load before keeping enabled.

## Installation

From `shadowfax` on the Pi, ensure the existing isolated libcamera source at
`/home/shadowfax/src/libcamera-0.3` is present and its `build` is usable.
**Do not replace the system libcamera library**.

```bash
cd ~/jarvis
git pull --ff-only
python3 -m py_compile clients/voice/camera_worker.py \
  clients/voice/environment_camera.py

# Compile the native worker in the same isolated libcamera environment used
# by the currently working camera utility. Compilation is Pi-local.
bash ops/build_camera_worker.sh

sudo install -m 0644 ops/systemd/jarvis-camera.service \
  /etc/systemd/system/jarvis-camera.service
sudo systemctl daemon-reload
sudo systemctl enable --now jarvis-camera.service
sudo systemctl status jarvis-camera.service --no-pager
journalctl -u jarvis-camera.service -n 50 --no-pager

# Restart the voice program so it uses the updated worker-aware capture code.
sudo systemctl restart jarvis-agents-voice.service
```

If the build script prints a libcamera version other than **0.3.x**, stop and
inspect which pkg-config paths are resolving; do not assume that linking to
Ubuntu's older libcamera is safe. If the isolated build lacks pkg-config
metadata, the native worker must be linked directly against the matching
isolated headers and libraries rather than silently linking the system one.

## Verify worker independently

```bash
# Socket only allows the shadowfax user (0700 runtime directory, 0600 socket).
/usr/bin/python3 - <<'PY'
import asyncio, json
async def main():
    r,w=await asyncio.open_unix_connection('/run/jarvis-camera/camera.sock')
    w.write(b'{"command":"status"}\n'); await w.drain()
    print((await r.readline()).decode().strip())
    w.close(); await w.wait_closed()
asyncio.run(main())
PY
```

Expected: `ok: true`, uptime, captures, and native CPU/RSS figures.

Then say: **"Jarvis, inspect your environment."** Log should show
`camera_backend=persistent_worker` and two `camera_capture` timings.

## Resource monitoring

```bash
# Total camera systemd service memory/CPU time:
systemctl show jarvis-camera.service \
  -p ActiveState -p MainPID -p MemoryCurrent -p CPUUsageNSec

# Live CPU and resident memory:
ps -eo pid,ppid,pcpu,rss,comm | grep -E 'camera_native|camera_worker|meson'

# Periodic worker measurements, every 60 seconds:
journalctl -u jarvis-camera.service -f -o cat

# Compare camera timings against legacy:
journalctl -u jarvis-agents-voice.service -f -o cat \
  | grep --line-buffered 'VISION PROFILE'
```

The camera worker logs process-tree RSS (MiB) and CPU usage as percentage
of **one CPU core** over a roughly one-minute interval. A multicore Pi may
report aggregate application CPU greater than 100% if it uses multiple cores.
Both the worker process and libcamera/native subprocess count against system
RAM; systemd `MemoryCurrent` additionally includes related allocations and
may be more useful for total memory.

## Configure frame rate

Low-rate defaults to one requested background frame per 2 seconds (0.5 fps).
To experiment with 5-second intervals (0.2 fps):

```bash
sudo systemctl edit jarvis-camera.service
```

Add:

```ini
[Service]
Environment=JARVIS_CAMERA_INTERVAL_SECONDS=5
```

Then `sudo systemctl daemon-reload && sudo systemctl restart jarvis-camera.service`.

Note: libcamera may maintain internal streaming even when user-space
requests are spaced out; this setting only limits *requested* background
captures. More aggressive interval increases risk of stale exposure after
a large lighting change. Explicit inspection frames are always requested
*after* the servo settles, regardless of background rate.

## Rollback

```bash
sudo systemctl disable --now jarvis-camera.service
sudo systemctl restart jarvis-agents-voice.service
```

The inspection helper automatically returns to the prior working isolated
libcamera subprocess if the worker socket is absent. This does not affect
ROS, navigation, or motors.

## First-run qualifications

C++ API/build compatibility and camera sensor scheduling have not been
verified on the physical Pi. If compilation fails, the service cannot start
or the camera stalls between low-rate requests, collect the build output and
`journalctl -u jarvis-camera.service -n 100 --no-pager` for targeted fixes.
Keep the old capture path until two successful inspections are recorded.
